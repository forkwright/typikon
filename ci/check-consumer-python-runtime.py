#!/usr/bin/env python3
"""Bind generated consumer validation to one importable, hash-locked runtime."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITHUB_TEMPLATE = ROOT / "ci" / "github-workflow.yml.tmpl"
KANON_TEMPLATE = ROOT / "ci" / "kanon-ci.toml.tmpl"
GATE_WORKFLOW = ROOT / ".github" / "workflows" / "gate-attestation.yml"
REQUIREMENTS_IN = ROOT / "ci" / "consumer-python-requirements.in"
REQUIREMENTS_LOCK = ROOT / "ci" / "consumer-python-requirements.lock"
VALIDATOR = ROOT / "bin" / "typikon-validate"

SETUP_PIN = "5fda3b95a4ea91299a34e894583c3862153e4b97"

sys.path.insert(0, str(ROOT / "ci"))
import toollock  # noqa: E402

# Derived, not copied: the version this check expects and the version the
# templates render are now the same fact read from one file.
PYTHON_VERSION = toollock.by_name(toollock.load(ROOT / "ci" / "tool-lock.toml"))["python"].version


def render_from_lock(path: Path) -> str:
    """The template as a consumer receives it, with every placeholder resolved."""
    completed = subprocess.run(
        [sys.executable, str(ROOT / "ci" / "render-template.py"),
         "--project-name", "fixture", str(path)],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"{path.name} does not render: {completed.stderr.strip()}")
    return completed.stdout

LOCK_PATH = "themes/typikon/ci/consumer-python-requirements.lock"
IMPORT_PROBE = (
    "from jsonschema import Draft202012Validator; "
    "from referencing import Registry, Resource; "
    "from referencing.jsonschema import DRAFT202012"
)


def named_yaml_step(source: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    if source.count(marker) != 1:
        raise ValueError(f"workflow must carry exactly one {name!r} step")
    start = source.index(marker)
    end = source.find("\n      - ", start + len(marker))
    return source[start:] if end == -1 else source[start : end + 1]


def named_toml_stage(source: str, name: str) -> str:
    marker = f"[stages.{name}]\n"
    if source.count(marker) != 1:
        raise ValueError(f"forge template must carry exactly one {name!r} stage")
    start = source.index(marker)
    end = source.find("\n[stages.", start + len(marker))
    return source[start:] if end == -1 else source[start : end + 1]


def require_once(block: str, needle: str, label: str, errors: list[str]) -> None:
    if block.count(needle) != 1:
        errors.append(f"{label} must appear exactly once")


def yaml_run_commands(block: str) -> list[str]:
    lines = block.splitlines()
    if lines.count("        run: |") != 1:
        raise ValueError("workflow step must carry exactly one block run command")
    start = lines.index("        run: |") + 1
    commands = []
    for line in lines[start:]:
        if line and not line.startswith("          "):
            break
        command = line[10:] if line else ""
        if command and not command.lstrip().startswith("#"):
            commands.append(command)
    return commands


def toml_commands(block: str) -> list[str]:
    lines = block.splitlines()
    if lines.count('cmd = """') != 1:
        raise ValueError("forge stage must carry exactly one cmd block")
    start = lines.index('cmd = """') + 1
    commands = []
    for line in lines[start:]:
        if line == '"""':
            break
        if line and not line.lstrip().startswith("#"):
            commands.append(line)
    return commands


def validate_github(source: str) -> list[str]:
    errors: list[str] = []
    try:
        setup = named_yaml_step(source, "Set up pinned Python for typikon-validate")
        install = named_yaml_step(source, "Install locked Python deps for typikon-validate")
        validate = named_yaml_step(source, "typikon-validate (frontmatter schemas)")
    except ValueError as exc:
        return [str(exc)]

    require_once(
        setup,
        f"        uses: actions/setup-python@{SETUP_PIN} # v7.0.0\n",
        "reviewed setup-python action",
        errors,
    )
    if source.count("uses: actions/setup-python@") != 1:
        errors.append("workflow must carry exactly one setup-python action")
    require_once(setup, "        id: python\n", "setup-python output id", errors)
    require_once(
        setup,
        f"          python-version: '{PYTHON_VERSION}'\n",
        "exact Python version",
        errors,
    )
    python_env = "          PYTHON: ${{ steps.python.outputs.python-path }}\n"
    require_once(install, python_env, "install interpreter output binding", errors)
    require_once(validate, python_env, "validator interpreter output binding", errors)
    expected_install = [
        '"$PYTHON" -m pip install --disable-pip-version-check --no-cache-dir '
        f'--only-binary=:all: --require-hashes -r {LOCK_PATH}',
        '"$PYTHON" -m pip check',
        f'"$PYTHON" -I -c \'{IMPORT_PROBE}\'',
    ]
    expected_validate = ['"$PYTHON" -I themes/typikon/bin/typikon-validate .']
    try:
        if yaml_run_commands(install) != expected_install:
            errors.append("dependency install must be the exact ordered locked command set")
        if yaml_run_commands(validate) != expected_validate:
            errors.append("validator must use the exact setup-python output interpreter")
    except ValueError as exc:
        errors.append(str(exc))
    if any(
        token in block
        for block in (setup, install, validate)
        for token in ("        if:", "        continue-on-error:", "        shell:")
    ):
        errors.append("Python setup, install, and validation steps must be unconditional")
    if "pip install --user" in setup + install:
        errors.append("consumer dependency install must not consult an ambient user site")
    if not source.index(setup) < source.index(install) < source.index(validate):
        errors.append("Python setup and install must precede typikon-validate")
    return errors


def validate_kanon(source: str) -> list[str]:
    errors: list[str] = []
    try:
        install = named_toml_stage(source, "install-python-deps")
        validate = named_toml_stage(source, "typikon-validate")
        consumer = named_toml_stage(source, "consumer-checks")
    except ValueError as exc:
        return [str(exc)]

    expected_install = [
        "set -euo pipefail",
        "python3 -m venv --clear .kanon-ci/python",
        ".kanon-ci/python/bin/python -m pip install --disable-pip-version-check "
        f"--no-cache-dir --only-binary=:all: --require-hashes -r {LOCK_PATH}",
        ".kanon-ci/python/bin/python -m pip check",
        f".kanon-ci/python/bin/python -I -c '{IMPORT_PROBE}'",
    ]
    expected_validate = [
        "set -euo pipefail",
        ".kanon-ci/python/bin/python -I themes/typikon/bin/typikon-validate .",
    ]
    try:
        if toml_commands(install) != expected_install:
            errors.append("forge install must be the exact ordered locked command set")
        if toml_commands(validate) != expected_validate:
            errors.append("forge validator must use the exact venv interpreter")
    except ValueError as exc:
        errors.append(str(exc))
    require_once(
        consumer,
        '  PATH="$PWD/.kanon-ci/python/bin:$PATH" bash ci/consumer-check.sh\n',
        "forge consumer-check venv PATH",
        errors,
    )
    if "pip install --user" in install:
        errors.append("forge dependency install must not consult an ambient user site")
    return errors


def validate_typikon_gate(source: str) -> list[str]:
    errors: list[str] = []
    sequence = (
        "        python3 -m venv --clear .gate-python\n"
        "        .gate-python/bin/python -m pip install --disable-pip-version-check "
        "--no-cache-dir --only-binary=:all: --require-hashes "
        "-r ci/consumer-python-requirements.lock\n"
        "        .gate-python/bin/python -m pip install --disable-pip-version-check "
        "--no-cache-dir --only-binary=:all: fonttools==4.62.1 Brotli==1.2.0 "
        "PyYAML==6.0.3\n"
        "        .gate-python/bin/python -m pip check\n"
        f"        .gate-python/bin/python -I -c '{IMPORT_PROBE}'\n"
    )
    require_once(source, sequence, "Typikon gate locked dependency sequence", errors)
    if re.search(r"pip install[^\n]*jsonschema(?:==|\s|$)", source):
        errors.append("Typikon gate must consume jsonschema only through the shared lock")
    require_once(
        source,
        '        PATH="$PWD/.gate-python/bin:$PATH" ci/run-fixtures.sh\n',
        "Typikon gate fixture venv PATH",
        errors,
    )
    return errors


def normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def input_requirements(source: str) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for number, raw in enumerate(source.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match:
            raise ValueError(f"requirements.in:{number}: dependency must use exact == pin")
        name = normalize(match.group(1))
        if name in requirements:
            raise ValueError(f"requirements.in:{number}: duplicate dependency {name}")
        requirements[name] = match.group(2)
    if set(requirements) != {"jsonschema", "referencing"}:
        raise ValueError("requirements.in must name exactly jsonschema and referencing")
    return requirements


def locked_requirements(source: str) -> dict[str, tuple[str, set[str]]]:
    requirements: dict[str, tuple[str, set[str]]] = {}
    current: str | None = None
    header = re.compile(
        r"^([A-Za-z0-9_.-]+)==([^ ;\\]+)(?:\s*;\s*.+)?\s+\\$"
    )
    hashed = re.compile(r"^    --hash=sha256:([0-9a-f]{64})(?: \\)?$")
    for number, raw in enumerate(source.splitlines(), 1):
        if not raw or raw.lstrip().startswith("#"):
            continue
        if match := header.fullmatch(raw):
            name = normalize(match.group(1))
            if name in requirements:
                raise ValueError(f"requirements.lock:{number}: duplicate dependency {name}")
            requirements[name] = (match.group(2), set())
            current = name
            continue
        if match := hashed.fullmatch(raw):
            if current is None:
                raise ValueError(f"requirements.lock:{number}: hash has no dependency")
            requirements[current][1].add(match.group(1))
            continue
        raise ValueError(f"requirements.lock:{number}: unsupported or unhashed input")
    if not requirements:
        raise ValueError("requirements.lock has no dependencies")
    missing = sorted(name for name, (_, hashes) in requirements.items() if not hashes)
    if missing:
        raise ValueError(f"requirements.lock entries lack hashes: {', '.join(missing)}")
    return requirements


def validate_requirements(input_source: str, lock_source: str) -> list[str]:
    try:
        direct = input_requirements(input_source)
        locked = locked_requirements(lock_source)
    except ValueError as exc:
        return [str(exc)]
    errors = []
    for name, version in direct.items():
        if name not in locked:
            errors.append(f"lock omits direct dependency {name}")
        elif locked[name][0] != version:
            errors.append(f"lock pins {name} {locked[name][0]}, expected {version}")
    return errors


def exercise_missing_dependency_error() -> None:
    with tempfile.TemporaryDirectory(prefix="typikon-missing-dependency-") as tmp:
        Path(tmp, "referencing.py").write_text(
            "raise ImportError('fixture unavailable', name='referencing')\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = tmp
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), "."],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 2:
        raise RuntimeError(f"missing dependency fixture exited {result.returncode}")
    try:
        payload = json.loads(result.stderr.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("missing dependency fixture did not emit JSON") from exc
    expected = {
        "error": "Python dependency unavailable: referencing",
        "requirements": "ci/consumer-python-requirements.lock",
    }
    if payload != expected:
        raise RuntimeError(f"missing dependency fixture emitted {payload!r}")


def main() -> int:
    if len(sys.argv) not in {1, 3}:
        print(
            f"usage: {Path(sys.argv[0]).name} [github-workflow kanon-config]",
            file=sys.stderr,
        )
        return 2
    github_path = Path(sys.argv[1]) if len(sys.argv) == 3 else GITHUB_TEMPLATE
    kanon_path = Path(sys.argv[2]) if len(sys.argv) == 3 else KANON_TEMPLATE
    # WHY rendered rather than raw: these two files are templates, and since
    # forkwright/typikon#58 their pinned versions are {{ PLACEHOLDERS }} filled
    # from ci/tool-lock.toml. Asserting against the raw text would check a
    # placeholder rather than the pin a consumer actually receives, and the
    # mutants below would mutate a name instead of a value.
    github = render_from_lock(github_path)
    kanon = render_from_lock(kanon_path)
    gate = GATE_WORKFLOW.read_text(encoding="utf-8")
    input_source = REQUIREMENTS_IN.read_text(encoding="utf-8")
    lock_source = REQUIREMENTS_LOCK.read_text(encoding="utf-8")

    errors = validate_github(github) + validate_kanon(kanon) + validate_typikon_gate(gate)
    errors += validate_requirements(input_source, lock_source)
    if errors:
        for error in errors:
            print(f"check-consumer-python-runtime: FAIL: {error}", file=sys.stderr)
        return 1

    github_mutants = {
        "wrong-action-pin": github.replace(SETUP_PIN, "a" * 40, 1),
        "wrong-python": github.replace(PYTHON_VERSION, "3.14.0", 1),
        "unhashed-install": github.replace("--require-hashes ", "", 1),
        "missing-pip-check": github.replace('          "$PYTHON" -m pip check\n', "", 1),
        "missing-referencing-probe": github.replace(IMPORT_PROBE, "import jsonschema", 1),
        "conditional-install": github.replace(
            "      - name: Install locked Python deps for typikon-validate\n",
            "      - name: Install locked Python deps for typikon-validate\n        if: false\n",
            1,
        ),
        "continue-on-error": github.replace(
            "      - name: Install locked Python deps for typikon-validate\n",
            "      - name: Install locked Python deps for typikon-validate\n        continue-on-error: true\n",
            1,
        ),
        "nonexecuting-shell": github.replace(
            "      - name: Install locked Python deps for typikon-validate\n",
            "      - name: Install locked Python deps for typikon-validate\n        shell: echo\n",
            1,
        ),
        "early-exit": github.replace(
            '        run: |\n          "$PYTHON" -m pip install',
            '        run: |\n          exit 0\n          "$PYTHON" -m pip install',
            1,
        ),
        "ignored-install-failure": github.replace(
            f"-r {LOCK_PATH}\n",
            f"-r {LOCK_PATH} || true\n",
            1,
        ),
        "ambient-install-python": github.replace(
            '"$PYTHON" -m pip install', "python3 -m pip install", 1
        ),
        "second-setup-python": github.replace(
            "      - name: Setup Node.js\n",
            "      - uses: actions/setup-python@"
            + SETUP_PIN
            + " # v7.0.0\n        with:\n          python-version: '3.12.14'\n\n"
            + "      - name: Setup Node.js\n",
            1,
        ),
        "ambient-validator": github.replace(
            '"$PYTHON" -I themes/typikon/bin/typikon-validate .',
            "themes/typikon/bin/typikon-validate .",
            1,
        ),
    }
    for label, mutant in github_mutants.items():
        if not validate_github(mutant):
            print(f"check-consumer-python-runtime: FAIL: accepted {label} mutant", file=sys.stderr)
            return 1

    kanon_mutants = {
        "user-site": kanon.replace(
            "python3 -m venv --clear .kanon-ci/python\n",
            "python3 -m pip install --user jsonschema\n",
            1,
        ),
        "unhashed-forge": kanon.replace("--require-hashes ", "", 1),
        "forge-early-exit": kanon.replace(
            "set -euo pipefail\npython3 -m venv",
            "set -euo pipefail\nexit 0\npython3 -m venv",
            1,
        ),
        "ignored-forge-install": kanon.replace(
            f"-r {LOCK_PATH}\n",
            f"-r {LOCK_PATH} || true\n",
            1,
        ),
        "ambient-consumer-check": kanon.replace(
            'PATH="$PWD/.kanon-ci/python/bin:$PATH" bash ci/consumer-check.sh',
            "bash ci/consumer-check.sh",
            1,
        ),
        "ambient-forge-validator": kanon.replace(
            ".kanon-ci/python/bin/python -I themes/typikon/bin/typikon-validate .",
            "themes/typikon/bin/typikon-validate .",
            1,
        ),
    }
    for label, mutant in kanon_mutants.items():
        if not validate_kanon(mutant):
            print(f"check-consumer-python-runtime: FAIL: accepted {label} mutant", file=sys.stderr)
            return 1

    gate_mutants = {
        "gate-unhashed": gate.replace("--require-hashes ", "", 1),
        "gate-missing-import": gate.replace(IMPORT_PROBE, "import jsonschema", 1),
        "gate-raw-jsonschema": gate.replace(
            "fonttools==4.62.1", "jsonschema==4.26.0 fonttools==4.62.1", 1
        ),
    }
    for label, mutant in gate_mutants.items():
        if not validate_typikon_gate(mutant):
            print(f"check-consumer-python-runtime: FAIL: accepted {label} mutant", file=sys.stderr)
            return 1

    bad_hash = lock_source.replace("--hash=sha256:", "--hash=sha256:bad", 1)
    if not validate_requirements(input_source, bad_hash):
        print("check-consumer-python-runtime: FAIL: accepted malformed hash mutant", file=sys.stderr)
        return 1
    drifted_input = input_source.replace("jsonschema==4.26.0", "jsonschema==4.25.1", 1)
    if not validate_requirements(drifted_input, lock_source):
        print("check-consumer-python-runtime: FAIL: accepted source/lock drift", file=sys.stderr)
        return 1

    try:
        exercise_missing_dependency_error()
    except RuntimeError as exc:
        print(f"check-consumer-python-runtime: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "check-consumer-python-runtime: ok "
        f"({github_path}, {kanon_path}, lock, dependency error)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
