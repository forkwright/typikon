#!/usr/bin/env python3
"""check-tool-lock — regression test for the one-lock toolchain contract
(forkwright/typikon#58).

WHY: the defect was not that a checksum was wrong. It was that a version and
its checksum lived in different places, so bumping one and not the other was a
single forgetful edit — and the checks that existed proved the four copies
agreed with EACH OTHER, which stays true when all four are wrong for a newly
bumped version. This proves three separate things, because any one alone still
permits the defect:

1. The lock refuses to describe a toolchain it cannot guarantee (a version
   contract wearing a hash's clothes, a URL that can name a different release
   than the checksum, two tools claiming one placeholder).
2. The generated surfaces DERIVE, so "the copies disagree" is unrepresentable
   rather than merely currently-false. A literal reintroduced into a template
   fails here.
3. The surfaces that CANNOT be generated — typikon's own gate workflow — match
   the lock, and never resolve a tool through `latest`.

The version-versus-checksum binding itself is proved by driving the shipped
--verify-upstream path over `file://` URLs, so the assertion is deterministic
and needs no network: a lock whose hash does not describe its version's
artifact must fail, and the same lock with the right hash must pass.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
CI = THEME_ROOT / "ci"
LOCK = CI / "tool-lock.toml"
TOOLLOCK = CI / "toollock.py"
RENDER = CI / "render-template.py"
DEFAULTS = THEME_ROOT / "bin" / "typikon-defaults.sh"
OWN_GATE = THEME_ROOT / ".github" / "workflows" / "gate-attestation.yml"
GENERATED = (CI / "github-workflow.yml.tmpl", CI / "kanon-ci.toml.tmpl")

sys.path.insert(0, str(CI))
import toollock  # noqa: E402

INSTALL_LINE = re.compile(r"\b(npm\s+(?:install|i)\b|pip\s+install\b|cargo\s+install\b)")


def install_lines(text: str) -> list[str]:
    """Lines that actually resolve a dependency.

    WHY not a substring scan of the whole file: the first draft of this check
    flagged three files for `@latest`, and all three hits were comments
    explaining why `@latest` is not used. A guard that fires on the prose
    documenting the guard is noise, and noise is what gets a check silenced.
    A full-line comment is skipped; a trailing comment on an install line is
    deliberately still read, because that is where a disabled pin hides.
    """
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if INSTALL_LINE.search(stripped):
            out.append(stripped)
    return out

MINIMAL = """schema_version = 1

[[tool]]
name = "demo"
kind = "archive"
version = "1.0.0"
sha256 = "{sha}"
url = "{url}"
placeholder_version = "DEMO_VERSION"
placeholder_sha256 = "DEMO_SHA256"
"""

# (label, lock body, expect_load_ok)
LOCK_CASES: list[tuple[str, str, bool]] = [
    ("npm entry carrying a sha256 it cannot honour", """schema_version = 1
[[tool]]
name = "demo"
kind = "npm"
version = "1.0.0"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
""", False),
    ("archive with no sha256", """schema_version = 1
[[tool]]
name = "demo"
kind = "archive"
version = "1.0.0"
url = "https://example.test/v{version}.tar.gz"
""", False),
    ("archive url that cannot name its version", """schema_version = 1
[[tool]]
name = "demo"
kind = "archive"
version = "1.0.0"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
url = "https://example.test/fixed.tar.gz"
""", False),
    ("two tools claiming one placeholder", """schema_version = 1
[[tool]]
name = "a"
kind = "npm"
version = "1"
integrity = "registry-version-pin"
placeholder_version = "SHARED"
[[tool]]
name = "b"
kind = "npm"
version = "2"
integrity = "registry-version-pin"
placeholder_version = "SHARED"
""", False),
    ("one tool declared twice", """schema_version = 1
[[tool]]
name = "dup"
kind = "npm"
version = "1"
integrity = "registry-version-pin"
[[tool]]
name = "dup"
kind = "npm"
version = "2"
integrity = "registry-version-pin"
""", False),
    ("npm entry with no integrity statement", """schema_version = 1
[[tool]]
name = "demo"
kind = "npm"
version = "1.0.0"
""", False),
    ("a schema version this reader does not speak", """schema_version = 99
[[tool]]
name = "demo"
kind = "npm"
version = "1"
integrity = "registry-version-pin"
""", False),
]


def check_lock_validation() -> list[str]:
    failures: list[str] = []
    for label, body, expect_ok in LOCK_CASES:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tool-lock.toml"
            path.write_text(body, encoding="utf-8")
            try:
                toollock.load(path)
                loaded = True
            except toollock.LockError:
                loaded = False
        if loaded != expect_ok:
            want = "load" if expect_ok else "be refused"
            failures.append(f"lock case {label!r}: expected to {want}, it did not")
    try:
        toollock.load(LOCK)
    except toollock.LockError as exc:
        failures.append(f"the shipped ci/tool-lock.toml does not validate: {exc}")
    return failures


def check_version_hash_binding() -> list[str]:
    """The defect itself: a version whose checksum describes a different artifact.

    Driven over file:// so the proof is deterministic. This is the one check in
    the repository that verifies a hash against the ARTIFACT rather than against
    another copy of the hash.
    """
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        artifact = tmp / "demo-1.0.0.tar.gz"
        artifact.write_bytes(b"the bytes that version 1.0.0 actually ships")
        real = hashlib.sha256(artifact.read_bytes()).hexdigest()
        url = f"file://{tmp}/demo-{{version}}.tar.gz"

        good = tmp / "good.toml"
        good.write_text(MINIMAL.format(sha=real, url=url), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(RENDER), "--lock", str(good), "--verify-upstream"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            failures.append(
                f"--verify-upstream rejected a correct version/hash pair: {proc.stderr.strip()}"
            )

        wrong = tmp / "wrong.toml"
        wrong.write_text(MINIMAL.format(sha="0" * 64, url=url), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(RENDER), "--lock", str(wrong), "--verify-upstream"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            failures.append(
                "--verify-upstream accepted a hash that does not describe the artifact; "
                "the version/checksum binding is not actually proved"
            )
    return failures


def check_generated_surfaces_derive() -> list[str]:
    """Templates must carry placeholders, never a literal version or checksum."""
    failures: list[str] = []
    for path in GENERATED:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(THEME_ROOT)
        for placeholder in ("{{ ZOLA_VERSION }}", "{{ ZOLA_SHA256 }}",
                            "{{ LYCHEE_VERSION }}", "{{ LYCHEE_SHA256 }}",
                            "{{ PA11Y_CI_VERSION }}", "{{ PLAYWRIGHT_VERSION }}"):
            if placeholder not in text:
                failures.append(f"{rel}: missing {placeholder}")
        if re.search(r"SHA256(?::|=)\s*[0-9a-f]{64}", text):
            failures.append(
                f"{rel}: carries a literal 64-hex checksum; it must render from the lock "
                "so a version and its checksum cannot be bumped separately"
            )
        for line in install_lines(text):
            for unbounded in ("@latest", "@next", "@*"):
                if unbounded in line:
                    failures.append(f"{rel}: resolves a dependency through {unbounded}: {line}")
    return failures


def check_rendering() -> list[str]:
    """Rendering must produce no leftover placeholder, and must refuse an unknown one."""
    failures: list[str] = []
    for path in GENERATED:
        proc = subprocess.run(
            [sys.executable, str(RENDER), "--project-name", "fixture", str(path)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            failures.append(f"{path.name}: does not render: {proc.stderr.strip()}")
            continue
        leftover = re.findall(r"(?<!\$)\{\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}\}", proc.stdout)
        if leftover:
            failures.append(f"{path.name}: rendered output still carries {sorted(set(leftover))}")
        # A GitHub Actions expression is not a typikon placeholder and must survive.
        if "${{ github." in path.read_text(encoding="utf-8") and "${{ github." not in proc.stdout:
            failures.append(f"{path.name}: rendering consumed a GitHub Actions expression")

    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "bad.tmpl"
        bad.write_text("x={{ NOT_IN_THE_LOCK }}\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(RENDER), str(bad)], capture_output=True, text=True,
        )
        if proc.returncode == 0:
            failures.append(
                "an undeclared placeholder rendered successfully; a typo would ship a "
                "literal brace sequence into a consumer's workflow"
            )
    return failures


def check_own_gate_matches_lock() -> list[str]:
    """typikon's own gate is not generated, so it is held to the lock by comparison."""
    failures: list[str] = []
    text = OWN_GATE.read_text(encoding="utf-8")
    rel = OWN_GATE.relative_to(THEME_ROOT)
    tools = toollock.by_name(toollock.load(LOCK))

    for line in install_lines(text):
        for unbounded in ("@latest", "@next"):
            if unbounded in line:
                failures.append(
                    f"{rel}: resolves a dependency through {unbounded}. This gate certifies "
                    "the templates it ships, so running newer tools than consumers get means "
                    f"the thing certified is not the thing tested: {line}"
                )

    expectations = [
        (r"^\s*ZOLA_VERSION=([0-9][^\s]*)$", "zola", "version"),
        (r"ZOLA_SHA256(?::|=)\s*([0-9a-f]{64})", "zola", "sha256"),
        (r"^\s*LYCHEE_VERSION=([0-9][^\s]*)$", "lychee", "version"),
        (r"LYCHEE_SHA256(?::|=)\s*([0-9a-f]{64})", "lychee", "sha256"),
        (r"pa11y-ci@([0-9][^\s]*)", "pa11y-ci", "version"),
        (r"@playwright/test@([0-9][^\s]*)", "@playwright/test", "version"),
    ]
    for pattern, name, field in expectations:
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            failures.append(f"{rel}: no {name} {field} found")
            continue
        want = getattr(tools[name], field)
        if match.group(1) != want:
            failures.append(f"{rel}: {name} {field} is {match.group(1)}, the lock says {want}")
    return failures


def check_defaults_refuses_drifting_override() -> list[str]:
    """A version override cannot carry a checksum, so it must abort its caller.

    WHY this is its own case: an earlier draft returned nonzero from the failing
    pin and then ran the next one, which succeeded — so the sourced file exited
    0 and the refusal permitted exactly what it refused. Nothing but running a
    real caller would have caught that.
    """
    caller = (
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'ZOLA_VERSION="${TYPIKON_ZOLA_VERSION:-}"\n'
        'WRANGLER_VERSION="${TYPIKON_WRANGLER_VERSION:-}"\n'
        f'. "{DEFAULTS}"\n'
        'echo REACHED\n'
    )
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "caller.sh"
        script.write_text(caller, encoding="utf-8")
        script.chmod(0o755)
        clean = subprocess.run(["bash", str(script)], capture_output=True, text=True)
        drift = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True,
            env={**dict(__import__("os").environ), "TYPIKON_ZOLA_VERSION": "0.0.1-not-locked"},
        )
    failures: list[str] = []
    if clean.returncode != 0 or "REACHED" not in clean.stdout:
        failures.append(f"typikon-defaults.sh fails without an override: {clean.stderr.strip()}")
    if drift.returncode == 0 or "REACHED" in drift.stdout:
        failures.append(
            "a drifting TYPIKON_ZOLA_VERSION did not abort its caller; the refusal is "
            "printed but not enforced"
        )
    return failures


def main() -> int:
    failures: list[str] = []
    for check in (
        check_lock_validation,
        check_version_hash_binding,
        check_generated_surfaces_derive,
        check_rendering,
        check_own_gate_matches_lock,
        check_defaults_refuses_drifting_override,
    ):
        failures += check()
    if failures:
        print("check-tool-lock: FAIL", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(
        f"check-tool-lock: ok ({len(LOCK_CASES)} lock-validation cases, the version/checksum "
        "binding over file://, both generated surfaces deriving, rendering fail-closed, the "
        "own-gate comparison, and the override refusal actually aborting)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
