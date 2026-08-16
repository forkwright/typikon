#!/usr/bin/env python3
"""check-init-favicon-path — regression test for bin/typikon-init's config.toml scaffold.

WHY: forkwright/typikon#110's fix routes templates/base.html's favicon <link> through
config.extra.favicon_path (ci/check-favicon-path.py proves the template side). The
issue's Desired correction is explicit that the key belongs in config.toml [extra]
alongside logo_path — bin/typikon-init's scaffold is the literal artifact a new
consumer starts from, and a fix that only touches the template leaves every freshly
scaffolded site with no visible way to discover the key exists.

Runs the real bin/typikon-init against a throwaway destination. The theme submodule
step is pointed at this checkout instead of the forge (TYPIKON_THEME_REPO(_GH)) and
cloned over the local-path transport (GIT_ALLOW_PROTOCOL=file — git blocks that
transport for submodules by default, CVE-2022-39253), so the check needs neither
network nor a running local forge.

WHY the env is fully isolated, not inherited (typikon#141 finding 4): a fixture that
spreads the caller's ambient `os.environ` into the subprocess only incidentally
exercises bin/typikon-init:301-316's no-identity fallback branch on a machine that
happens to start with no git identity configured (GH Actions runners do; most
operator/dev boxes and future CI images do not). Both cases below build an isolated
HOME with GIT_CONFIG_NOSYSTEM=1 and no inherited GIT_AUTHOR_*/GIT_COMMITTER_* vars,
so `git config user.email`/`user.name` inside bin/typikon-init has nothing ambient
left to resolve regardless of the box this runs on:

- Case A seeds no identity at all — this is the fallback branch itself. Before
  bin/typikon-init:301-316 existed, this case reproduced the exact CI failure
  (`fatal: empty ident name ... not allowed`, exit 128) that blocked this PR's own
  first CI run (gate / full-gate-build, run 31824469160). Reverting the fallback
  and re-running this script reproduces that failure again — see the PR body for
  the exact revert/re-run/restore sequence.
- Case B seeds a real identity in the isolated HOME's .gitconfig — this proves the
  fallback does NOT engage when a caller has their own identity configured, and
  that the scaffold commit carries THAT identity rather than the fallback's fixed
  one. Without this case, a fixture that only forces the fallback branch cannot
  distinguish "falls back when needed" from "always overrides."

NOTE: runs standalone (no examples/ site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
INIT_SCRIPT = THEME_ROOT / "bin" / "typikon-init"

FAVICON_LINE_RE = re.compile(r'^\s*#?\s*favicon_path\s*=\s*"([^"]+)"', re.MULTILINE)

# WHY: passed through, never inherited wholesale — the isolation this fixture
# exists to provide would be silently undone by spreading os.environ back in.
_PASSTHROUGH_KEYS = ("PATH", "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR")


def _isolated_env(isolated_home: Path, *, seed_identity: bool) -> dict[str, str]:
    env = {key: os.environ[key] for key in _PASSTHROUGH_KEYS if key in os.environ}
    env["HOME"] = str(isolated_home)
    # WHY: blocks /etc/gitconfig (or any packaged system-level identity) from
    # resolving user.name/user.email out from under the isolation — without
    # this, Case A is not actually a no-identity environment on a box whose
    # system config carries one.
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_ALLOW_PROTOCOL"] = "file"
    env["TYPIKON_THEME_REPO"] = str(THEME_ROOT)
    env["TYPIKON_THEME_REPO_GH"] = str(THEME_ROOT)
    if seed_identity:
        (isolated_home / ".gitconfig").write_text(
            "[user]\n\tname = Isolated Test\n\temail = isolated-test@example.invalid\n",
            encoding="utf-8",
        )
    return env


def _run_init(env: dict[str, str], dest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INIT_SCRIPT), "probe-site", str(dest)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _scaffold_commit_author(dest: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(dest), "log", "-1", "--format=%an <%ae>"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip()


def _check_favicon_key(config: Path) -> str | None:
    """Return an error string, or None if config.toml scaffolds favicon_path correctly."""
    if not config.is_file():
        return f"{config} was not created"
    text = config.read_text(encoding="utf-8")
    match = FAVICON_LINE_RE.search(text)
    if match is None:
        return "scaffolded config.toml [extra] carries no favicon_path key (forkwright/typikon#110)"
    if match.group(1) != "img/favicon.svg":
        return (
            f"scaffolded favicon_path default is {match.group(1)!r}, expected "
            "'img/favicon.svg' (must match base.html's default so an unset key is a no-op)"
        )
    return None


def main() -> int:
    failures: list[str] = []

    # Case A: no ambient git identity anywhere the isolated env can see.
    # This is the fallback branch — bin/typikon-init:301-316 must engage it
    # and still complete, using the fixed typikon-init identity.
    with tempfile.TemporaryDirectory(prefix="typikon-init-favicon-noident-home-") as home_tmp, \
         tempfile.TemporaryDirectory(prefix="typikon-init-favicon-noident-dest-") as dest_tmp:
        env = _isolated_env(Path(home_tmp), seed_identity=False)
        dest = Path(dest_tmp) / "probe-site"
        result = _run_init(env, dest)
        if result.returncode != 0:
            failures.append(
                f"no-identity case: bin/typikon-init exited {result.returncode} "
                f"(expected 0 — the no-identity fallback should have engaged):\n{result.stderr}"
            )
        else:
            err = _check_favicon_key(dest / "config.toml")
            if err is not None:
                failures.append(f"no-identity case: {err}")
            author = _scaffold_commit_author(dest, env)
            if author != "typikon-init <typikon-init@localhost>":
                failures.append(
                    "no-identity case: expected scaffold commit author "
                    f"'typikon-init <typikon-init@localhost>' (the fallback identity), got {author!r}"
                )

    # Case B: a real identity IS configured in the isolated HOME. The
    # fallback must NOT engage, and the commit must carry that identity, not
    # the fallback's fixed one — proves the fix is a fallback, not an
    # override.
    with tempfile.TemporaryDirectory(prefix="typikon-init-favicon-ident-home-") as home_tmp, \
         tempfile.TemporaryDirectory(prefix="typikon-init-favicon-ident-dest-") as dest_tmp:
        env = _isolated_env(Path(home_tmp), seed_identity=True)
        dest = Path(dest_tmp) / "probe-site"
        result = _run_init(env, dest)
        if result.returncode != 0:
            failures.append(
                f"real-identity case: bin/typikon-init exited {result.returncode} "
                f"(expected 0):\n{result.stderr}"
            )
        else:
            err = _check_favicon_key(dest / "config.toml")
            if err is not None:
                failures.append(f"real-identity case: {err}")
            author = _scaffold_commit_author(dest, env)
            if author != "Isolated Test <isolated-test@example.invalid>":
                failures.append(
                    "real-identity case: expected scaffold commit author "
                    "'Isolated Test <isolated-test@example.invalid>' (the caller's own identity, "
                    f"untouched by the fallback), got {author!r}"
                )

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(
        "OK: bin/typikon-init scaffolds config.toml [extra] with a favicon_path key "
        "defaulted to img/favicon.svg in both a genuinely identity-less environment "
        "(fallback engages, commit uses the fixed typikon-init identity) and one with "
        "a real git identity configured (fallback stays out of the way, commit uses "
        "the caller's own identity)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
