#!/usr/bin/env python3
"""check-cf-deploy-gate — regression test for the Cloudflare production-branch halt.

WHY: ci/github-workflow.yml.tmpl's "Deploy to Cloudflare Pages" step reads the
Cloudflare PATCH response and must halt before Wrangler runs unless the body
reports `.success == true` AND `.result.production_branch` exactly equals the
branch being shipped (forkwright/typikon#63) — otherwise a green command path
can deploy under the wrong environment semantics. That halt existed with ZERO
fixture coverage: nothing would have caught its removal. This script extracts
the step's `run:` block VERBATIM from the template (no paraphrase, no rewrite)
and executes it under stubbed curl/npm/wrangler, so the fixtures exercise the
literal shipped shell text.

Stubs (installed ahead of the real tools on PATH):
    curl      cats $CF_FIXTURE_JSON to stdout — the block's own
              `> /tmp/cf-edit.json` redirect captures it, same as the real step
    npm       no-op
    wrangler  appends an invocation marker to $CF_WRANGLER_MARKER, so a bad
              fixture that reaches Wrangler is observable instead of silently
              "passing" because nothing checked

Invoked with `--noprofile --norc -eo pipefail`, matching GitHub Actions' actual
default shell for `run:` steps — a case that only halts because of `set -e`
(e.g. a jq parse error aborting the script) is still a real halt in production,
not a false pass in this harness.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = THEME_ROOT / "ci" / "github-workflow.yml.tmpl"
STEP_MARKER = "- name: Deploy to Cloudflare Pages"

MALFORMED_BODY = '{"success": true, "result": {'

# (label, response body written to the stubbed curl's stdout, expect Wrangler to run)
CASES: list[tuple[str, str, bool]] = [
    ("success", json.dumps({"success": True, "result": {"production_branch": "main"}}), True),
    (
        "unsuccessful",
        json.dumps({"success": False, "result": {"production_branch": "main"}, "errors": [{"message": "forbidden"}]}),
        False,
    ),
    ("malformed", MALFORMED_BODY, False),
    ("missing-result", json.dumps({"success": True}), False),
    ("wrong-branch", json.dumps({"success": True, "result": {"production_branch": "not-main"}}), False),
]


def extract_run_block(template_text: str) -> str:
    """The literal, dedented shell text of the Deploy step's `run:` block.

    WARNING: dedents by the block's OWN minimum indentation, not a hardcoded
    width — the template is hand-edited YAML and a reindent must not silently
    desync this from what actually ships.
    """
    lines = template_text.splitlines()
    try:
        step_idx = next(i for i, l in enumerate(lines) if STEP_MARKER in l)
    except StopIteration:
        raise SystemExit(f"error: step {STEP_MARKER!r} not found in {TEMPLATE}")
    step_indent = len(lines[step_idx]) - len(lines[step_idx].lstrip(" "))

    try:
        run_idx = next(i for i in range(step_idx, len(lines)) if lines[i].strip() == "run: |")
    except StopIteration:
        raise SystemExit(f"error: no 'run: |' block under {STEP_MARKER!r}")

    body = []
    for line in lines[run_idx + 1 :]:
        indent = len(line) - len(line.lstrip(" "))
        if line.strip() and indent <= step_indent and line.lstrip().startswith("- name:"):
            break  # next step at the same level — this step's block ended
        body.append(line)

    indents = [len(l) - len(l.lstrip(" ")) for l in body if l.strip()]
    if not indents:
        raise SystemExit(f"error: empty run: block under {STEP_MARKER!r}")
    pad = min(indents)
    return "\n".join(l[pad:] if l.strip() else "" for l in body)


def make_stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def run_case(script_path: Path, fixture_body: str, bindir: Path, workdir: Path) -> tuple[int, bool]:
    fixture_path = workdir / "cf-fixture.json"
    fixture_path.write_text(fixture_body)
    marker_path = workdir / "wrangler-invoked"
    marker_path.unlink(missing_ok=True)

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["GITHUB_REF"] = "refs/heads/main"
    env["CF_FIXTURE_JSON"] = str(fixture_path)
    env["CF_WRANGLER_MARKER"] = str(marker_path)
    env["CLOUDFLARE_API_TOKEN"] = "test-token"
    env["CLOUDFLARE_ACCOUNT_ID"] = "test-account"

    proc = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script_path)],
        env=env,
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    return proc.returncode, marker_path.exists()


def main() -> int:
    if not TEMPLATE.exists():
        print(f"check-cf-deploy-gate: {TEMPLATE} not found", file=sys.stderr)
        return 2

    block = extract_run_block(TEMPLATE.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="typikon-cf-gate-") as td:
        workdir = Path(td)
        bindir = workdir / "bin"
        bindir.mkdir()
        make_stub(bindir / "curl", 'cat "$CF_FIXTURE_JSON"')
        make_stub(bindir / "npm", "exit 0")
        make_stub(bindir / "wrangler", 'echo "WRANGLER_INVOKED $*" >> "$CF_WRANGLER_MARKER"')

        script_path = workdir / "deploy-step.sh"
        script_path.write_text(block)

        failed = []
        for label, fixture_body, expect_wrangler in CASES:
            rc, wrangler_ran = run_case(script_path, fixture_body, bindir, workdir)
            passed_ok = expect_wrangler and rc == 0 and wrangler_ran
            halted_ok = not expect_wrangler and rc != 0 and not wrangler_ran
            if not (passed_ok or halted_ok):
                want = "deploy" if expect_wrangler else "halt before Wrangler"
                got = f"exit={rc} wrangler_invoked={wrangler_ran}"
                failed.append(f"{label}: expected {want}, got {got}")

        if failed:
            for line in failed:
                print(f"FAIL: {line}", file=sys.stderr)
            return 1

        print(json.dumps({"checked": len(CASES), "passed": len(CASES), "failed": 0}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
