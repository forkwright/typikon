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
    curl      cats $CF_FIXTURE_JSON to stdout — the block's own redirect
              captures it, same as the real step
    npm       no-op
    wrangler  appends an invocation marker to $CF_WRANGLER_MARKER, so a bad
              fixture that reaches Wrangler is observable instead of silently
              "passing" because nothing checked

Invoked with `--noprofile --norc -eo pipefail`, matching GitHub Actions' actual
default shell for `run:` steps — a case that only halts because of `set -e`
(e.g. a jq parse error aborting the script) is still a real halt in production,
not a false pass in this harness.

WARNING: the extracted block is executed verbatim EXCEPT for one substitution —
the shipped step hardcodes its CF-response scratch file at SHIPPED_TMP_PATH
(a fixed, shared, world-writable location outside any per-run temp dir); see
namespace_shared_tmp_path() for why this harness redirects that one literal
before executing, and note this is a test-harness hygiene fix only — the
shipped step in ci/github-workflow.yml.tmpl still writes the real path, which
is a separate production concern this branch does not touch.

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

# NOTE: the literal the shipped step hardcodes for its CF-response scratch
# file (ci/github-workflow.yml.tmpl's `> /tmp/cf-edit.json` redirect and the
# three `jq` reads that follow it). Tracked as a constant, not a hardcoded
# string at each use, so extraction drift is a single comparison instead of
# four scattered ones.
SHIPPED_TMP_PATH = "/tmp/cf-edit.json"

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


def namespace_shared_tmp_path(block: str, target: Path) -> str:
    """Redirect the shipped step's hardcoded SHIPPED_TMP_PATH write to `target`.

    WARNING: this is a test-hygiene substitution, not a rewrite of the
    block's logic — it exists ONLY so re-executing the extracted step under
    this harness doesn't inherit the real, shared, world-writable path.
    Every occurrence is the same literal string (the redirect and the three
    `jq` reads after it), so a single str.replace covers all of them
    identically; nothing about the control flow being tested changes.

    INVARIANT: fails closed if SHIPPED_TMP_PATH is absent from `block` —
    silently no-op'ing here would mean the harness quietly went back to
    writing the real path the moment the shipped step's text changed.
    """
    if SHIPPED_TMP_PATH not in block:
        raise SystemExit(
            f"error: expected literal {SHIPPED_TMP_PATH!r} in the extracted "
            f"run: block under {STEP_MARKER!r} — the shipped step's scratch-file "
            "path changed and this harness's namespacing substitution needs updating"
        )
    return block.replace(SHIPPED_TMP_PATH, str(target))


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
        namespaced_block = namespace_shared_tmp_path(block, workdir / "cf-edit.json")
        script_path.write_text(namespaced_block)

        # WHY: proves the substitution above actually took — a real fixture
        # bug, confirmed on this branch, had every case reach through to the
        # shipped step's literal SHIPPED_TMP_PATH, so concurrent harness runs
        # collided on one shared world-writable file and it survived past the
        # TemporaryDirectory this run otherwise cleans up. Snapshotting
        # (exists, mtime) rather than just existence also catches the case
        # where the path was already present before this run started.
        shared_path = Path(SHIPPED_TMP_PATH)
        pre_state = (shared_path.exists(), shared_path.stat().st_mtime if shared_path.exists() else None)

        failed = []
        for label, fixture_body, expect_wrangler in CASES:
            rc, wrangler_ran = run_case(script_path, fixture_body, bindir, workdir)
            passed_ok = expect_wrangler and rc == 0 and wrangler_ran
            halted_ok = not expect_wrangler and rc != 0 and not wrangler_ran
            if not (passed_ok or halted_ok):
                want = "deploy" if expect_wrangler else "halt before Wrangler"
                got = f"exit={rc} wrangler_invoked={wrangler_ran}"
                failed.append(f"{label}: expected {want}, got {got}")

        post_state = (shared_path.exists(), shared_path.stat().st_mtime if shared_path.exists() else None)
        if post_state != pre_state:
            failed.append(
                f"hygiene: {SHIPPED_TMP_PATH} changed during the run — a fixture "
                "wrote the shared host path instead of the namespaced workdir copy"
            )

        if failed:
            for line in failed:
                print(f"FAIL: {line}", file=sys.stderr)
            return 1

        print(json.dumps({"checked": len(CASES), "passed": len(CASES), "failed": 0}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
