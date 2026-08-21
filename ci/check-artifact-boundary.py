#!/usr/bin/env python3
"""check-artifact-boundary — regression test for the agent-corpus boundary
(forkwright/typikon#188).

WHY: `extra.agent_corpus_exposure = "repository"` is a promise about bytes that
reach the public web. Before this, the field was inert — typed nowhere, checked
nowhere — so validation output overstated what the substrate guaranteed. This
proves two separate things, because either alone would be a false comfort:

1. The shipped ci/validate-artifact-boundary.py refuses every shape of the leak,
   driven as the real subprocess the pipelines run, not a reimplementation.
2. The stage is actually WIRED, in a position where it can still block. A
   checker nothing calls is worth exactly nothing, and #48's own re-derivation
   found "the assertion is present and nothing would catch its removal" to be
   the more durable defect. So removal or reordering fails here.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
VALIDATE = THEME_ROOT / "ci" / "validate-artifact-boundary.py"
WORKFLOW_TMPL = THEME_ROOT / "ci" / "github-workflow.yml.tmpl"
KANON_TMPL = THEME_ROOT / "ci" / "kanon-ci.toml.tmpl"
LOCAL_GATE = THEME_ROOT / "bin" / "typikon-check"

DECLARED = 'base_url = "https://example.test"\n[extra]\nagent_corpus_exposure = "repository"\n'
UNDECLARED = 'base_url = "https://example.test"\n'

# (label, config.toml body, {relative path: kind}, expect_pass)
# kind: "file" writes an empty file; "dir" makes a directory;
#       "link:<target>" makes a symlink with that literal target.
CASES: list[tuple[str, str, dict[str, str], bool]] = [
    ("clean tree, boundary declared", DECLARED, {"public/index.html": "file"}, True),
    ("llms.txt at the tree root", DECLARED, {"public/llms.txt": "file"}, False),
    ("llms.txt nested deep", DECLARED, {"public/a/b/c/llms.txt": "file"}, False),
    # A case-preserving filesystem holds this happily and a case-insensitive
    # host serves it as llms.txt, so matching one spelling would admit the leak.
    ("LLMS.TXT differing only in case", DECLARED, {"public/LLMS.TXT": "file"}, False),
    ("_llm directory at the root", DECLARED, {"public/_llm": "dir"}, False),
    ("_llm directory nested", DECLARED, {"public/a/_llm": "dir"}, False),
    ("_LLM directory differing only in case", DECLARED, {"public/_LLM": "dir"}, False),
    ("file inside a nested _llm component", DECLARED, {"public/a/_llm/facts.toml": "file"}, False),
    # Renaming is the cheap way around a name check: the served path says
    # "docs" while every byte behind it is the corpus.
    ("directory symlink renaming _llm", DECLARED, {"public/docs": "link:../_llm"}, False),
    ("file symlink named llms.txt", DECLARED, {"public/llms.txt": "link:../_llm/facts.toml"}, False),
    # public-local/ ships nothing itself, but it is what pa11y and playwright
    # serve, so a leak there is a leak to every browser assertion downstream.
    ("leak only in public-local", DECLARED, {"public/index.html": "file", "public-local/llms.txt": "file"}, False),
    # The field is optional. A consumer that never claimed the boundary is not
    # violating it, and failing here would punish a legitimate posture.
    ("no declaration, corpus present", UNDECLARED, {"public/llms.txt": "file"}, True),
]


def build(tmp: Path, config_body: str, entries: dict[str, str]) -> Path:
    root = tmp / "site"
    (root / "public").mkdir(parents=True, exist_ok=True)
    (root / "public-local").mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(config_body, encoding="utf-8")
    for rel, kind in entries.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "dir":
            target.mkdir(exist_ok=True)
        elif kind.startswith("link:"):
            os.symlink(kind[len("link:"):], target)
        else:
            target.write_text("", encoding="utf-8")
    return root


def run_cases() -> list[str]:
    failures: list[str] = []
    for label, config_body, entries, expect_pass in CASES:
        with tempfile.TemporaryDirectory() as td:
            root = build(Path(td), config_body, entries)
            proc = subprocess.run(
                [sys.executable, str(VALIDATE), "--root", str(root), "public", "public-local"],
                cwd=root, capture_output=True, text=True,
            )
        passed = proc.returncode == 0
        if passed != expect_pass:
            want = "pass" if expect_pass else "fail"
            failures.append(
                f"{label}: expected {want}, got exit {proc.returncode}"
                f" (stdout={proc.stdout.strip()!r} stderr={proc.stderr.strip()!r})"
            )
    return failures


def check_missing_tree() -> list[str]:
    """An absent rendered tree must be an error, never a silent pass.

    WHY its own case: this is the difference between "the boundary held" and
    "there was nothing to check", and collapsing the two is precisely how an
    inert guard reports success forever.
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "site"
        root.mkdir(parents=True)
        (root / "config.toml").write_text(DECLARED, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(VALIDATE), "--root", str(root), "public", "public-local"],
            cwd=root, capture_output=True, text=True,
        )
    if proc.returncode == 0:
        return ["absent rendered trees: expected fail, got exit 0"]
    return []


def check_malformed_declaration() -> list[str]:
    """A value the config contract rejects must not be silently enforced as absent."""
    with tempfile.TemporaryDirectory() as td:
        root = build(Path(td), 'base_url = "https://x.test"\n[extra]\nagent_corpus_exposure = "private"\n',
                     {"public/index.html": "file"})
        proc = subprocess.run(
            [sys.executable, str(VALIDATE), "--root", str(root), "public", "public-local"],
            cwd=root, capture_output=True, text=True,
        )
    if proc.returncode == 0:
        return ['agent_corpus_exposure = "private": expected fail, got exit 0']
    return []


def check_hosted_wiring() -> list[str]:
    """The generated GitHub pipeline must call the checker, in a blocking position."""
    failures: list[str] = []
    text = WORKFLOW_TMPL.read_text(encoding="utf-8")
    if "validate-artifact-boundary.py" not in text:
        return [f"{WORKFLOW_TMPL.name}: does not invoke validate-artifact-boundary.py at all"]
    steps = [(i, line) for i, line in enumerate(text.splitlines()) if line.lstrip().startswith("- name:")]

    def index_of(fragment: str) -> int | None:
        for i, line in steps:
            if fragment in line:
                return i
        return None

    boundary = index_of("agent corpus stayed out")
    consumer = index_of("Consumer checks")
    receipt = index_of("Record Typikon consumer receipt")
    deploy = index_of("Deploy to Cloudflare Pages")
    if boundary is None:
        failures.append(f"{WORKFLOW_TMPL.name}: no step asserting the agent-corpus boundary")
        return failures
    for label, other in (("Consumer checks", consumer),):
        if other is not None and boundary < other:
            failures.append(
                f"{WORKFLOW_TMPL.name}: boundary step runs BEFORE '{label}', so it would "
                "assert a tree that stage can still write to"
            )
    for label, other in (("Record Typikon consumer receipt", receipt), ("Deploy to Cloudflare Pages", deploy)):
        if other is not None and boundary > other:
            failures.append(
                f"{WORKFLOW_TMPL.name}: boundary step runs AFTER '{label}', so the corpus "
                "would already be recorded or published before it is checked"
            )
    return failures


def check_kanon_wiring() -> list[str]:
    """The generated Kanon pipeline must define the stage AND schedule it.

    WHY both: `[pipeline] stages` is execution order in this file. A stage
    defined but left out of that list is inert, and reads as present.
    """
    failures: list[str] = []
    raw = KANON_TMPL.read_text(encoding="utf-8")
    if "validate-artifact-boundary.py" not in raw:
        failures.append(f"{KANON_TMPL.name}: does not invoke validate-artifact-boundary.py at all")
    try:
        parsed = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        return failures + [f"{KANON_TMPL.name}: is not parseable TOML: {exc}"]
    order = parsed.get("pipeline", {}).get("stages", [])
    stage = "assert-agent-corpus-boundary"
    if stage not in parsed.get("stages", {}):
        failures.append(f"{KANON_TMPL.name}: [stages.{stage}] is not defined")
    if stage not in order:
        failures.append(
            f"{KANON_TMPL.name}: '{stage}' is absent from [pipeline] stages, so it never runs"
        )
        return failures
    at = order.index(stage)
    if "consumer-checks" in order and at < order.index("consumer-checks"):
        failures.append(f"{KANON_TMPL.name}: '{stage}' is scheduled before consumer-checks")
    if "deploy-cloudflare-pages" in order and at > order.index("deploy-cloudflare-pages"):
        failures.append(f"{KANON_TMPL.name}: '{stage}' is scheduled after deploy-cloudflare-pages")
    return failures


def check_local_wiring() -> list[str]:
    """The local gate must run the checker, and must not treat it as skippable."""
    failures: list[str] = []
    text = LOCAL_GATE.read_text(encoding="utf-8")
    if "validate-artifact-boundary.py" not in text:
        return [f"{LOCAL_GATE.name}: does not invoke validate-artifact-boundary.py at all"]
    if "require_or_skip \"agent-corpus-boundary\"" in text or "require_or_skip 'agent-corpus-boundary'" in text:
        failures.append(
            f"{LOCAL_GATE.name}: the boundary stage is skippable; a skipped boundary "
            "reports a guarantee nothing checked"
        )
    call = text.index("validate-artifact-boundary.py")
    playwright = text.rfind("playwright-smoke")
    if playwright != -1 and call < playwright:
        failures.append(
            f"{LOCAL_GATE.name}: the boundary stage runs before the last stage that "
            "writes public-local/, so it would assert a non-final tree"
        )
    return failures


def main() -> int:
    if not VALIDATE.is_file():
        print(f"check-artifact-boundary: missing {VALIDATE}", file=sys.stderr)
        return 1
    failures: list[str] = []
    failures += run_cases()
    failures += check_missing_tree()
    failures += check_malformed_declaration()
    failures += check_hosted_wiring()
    failures += check_kanon_wiring()
    failures += check_local_wiring()

    if failures:
        print("check-artifact-boundary: FAIL", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(
        f"check-artifact-boundary: ok ({len(CASES)} corpus cases, absent-tree and "
        "malformed-declaration cases, and the stage's wiring in all three pipelines)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
