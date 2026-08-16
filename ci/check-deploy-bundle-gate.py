#!/usr/bin/env python3
"""check-deploy-bundle-gate — regression test for the deploy control-file bundle
gate (forkwright/typikon#48).

WHY: ci/validate-deploy-bundle.py is what stands between a broken or missing
_headers/_redirects/404.html and a green deploy. Before this script existed,
the same claim held for the Cloudflare production-branch halt
(forkwright/typikon#63) with zero fixture coverage, and the issue's own
re-derivation found "the assertion is present and nothing would catch its
removal" was the more durable defect. This proves the equivalent claim does
NOT hold here: deletion and corruption fixtures for every required member
(forkwright/typikon#48's "Desired correction") each drive the SHIPPED
ci/validate-deploy-bundle.py — invoked as the real subprocess GitHub Actions
runs, not a reimplementation of its checks — to a nonzero exit before any of
them would reach Wrangler.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
VALIDATE = THEME_ROOT / "ci" / "validate-deploy-bundle.py"

GOOD_HEADERS = "/*\n  X-Frame-Options: DENY\n\n/assets/*\n  Cache-Control: public, max-age=31536000\n"
GOOD_REDIRECTS = "# comment\n/old /new 301\n/blog/:slug /posts/:slug 301!\n"
GOOD_404 = "<!doctype html><html><body>Not found</body></html>"

BASE_FILES = {
    "_headers": GOOD_HEADERS,
    "_redirects": GOOD_REDIRECTS,
    "404.html": GOOD_404,
}


def bundle(overrides: dict[str, str | None]) -> dict[str, str]:
    """BASE_FILES with `overrides` applied; a None value means "omit this file"."""
    files = dict(BASE_FILES)
    for name, content in overrides.items():
        if content is None:
            files.pop(name, None)
        else:
            files[name] = content
    return files


# (label, files-to-write, expect_pass)
CASES: list[tuple[str, dict[str, str], bool]] = [
    ("all present and well-formed", bundle({}), True),
    ("missing _headers", bundle({"_headers": None}), False),
    ("missing _redirects", bundle({"_redirects": None}), False),
    ("missing 404.html", bundle({"404.html": None}), False),
    ("empty 404.html", bundle({"404.html": ""}), False),
    ("404.html with no HTML content", bundle({"404.html": "plain text, no angle brackets"}), False),
    # header assignment with no leading whitespace before any path pattern —
    # a real, common corruption (an editor stripping leading indentation).
    ("_headers orphaned assignment", bundle({"_headers": "  X-Frame-Options: DENY\n/*\n  Content-Security-Policy: default-src 'self'\n"}), False),
    # the same corruption ONE LINE LATER: indentation lost on a header that
    # follows an already-valid path pattern. Byte-for-byte this reads like a
    # second path pattern to a naive "unindented == new block" reading, so
    # it is the case a position-only check (flag only the file's first line)
    # cannot catch — Cloudflare still drops it silently at serve time.
    ("_headers assignment loses indentation after a pattern", bundle({"_headers": "/*\n  X-Frame-Options: DENY\nX-Content-Type-Options: nosniff\n"}), False),
    # indented line that is not a Name: value pair.
    ("_headers missing colon", bundle({"_headers": "/*\n  X-Frame-Options DENY\n"}), False),
    ("_redirects wrong field count", bundle({"_redirects": "/old\n"}), False),
    ("_redirects bad destination", bundle({"_redirects": "/old bar 301\n"}), False),
    ("_redirects bad status code", bundle({"_redirects": "/old /new 999999\n"}), False),
]


def run_case(files: dict[str, str], workdir: Path) -> subprocess.CompletedProcess:
    public = workdir / "public"
    public.mkdir(exist_ok=True)
    for name in list(BASE_FILES):
        (public / name).unlink(missing_ok=True)
    for name, content in files.items():
        (public / name).write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(VALIDATE), str(public)],
        capture_output=True,
        text=True,
        check=False,
        # WHY cwd=workdir: validate-deploy-bundle.py writes its receipt under
        # RUNNER_TEMP, falling back to the CURRENT DIRECTORY when unset (as
        # here). Without pinning cwd, that fallback would drop a stray
        # deploy-bundle-receipt.json into wherever this test happened to be
        # invoked from on every one of the CASES below — the same class of
        # hygiene defect forkwright/typikon#63 PR #146 found and fixed for a
        # hardcoded /tmp path, relocated to cwd instead of eliminated.
        cwd=workdir,
    )


def main() -> int:
    if not VALIDATE.exists():
        print(f"check-deploy-bundle-gate: {VALIDATE} not found", file=sys.stderr)
        return 2

    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="typikon-deploy-bundle-gate-") as td:
        workdir = Path(td)
        for label, files, expect_pass in CASES:
            proc = run_case(files, workdir)
            passed = proc.returncode == 0
            if passed != expect_pass:
                want = "pass" if expect_pass else "fail"
                failed.append(
                    f"{label}: expected to {want}, got exit={proc.returncode}\n"
                    f"    stdout: {proc.stdout.strip()}\n"
                    f"    stderr: {proc.stderr.strip()}"
                )

    if failed:
        for line in failed:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(f'{{"checked": {len(CASES)}, "passed": {len(CASES)}, "failed": 0}}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
