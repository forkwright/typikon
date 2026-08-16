#!/usr/bin/env python3
"""validate-deploy-bundle — enforce + hash the Cloudflare deploy control-file bundle.

WHY: the "Copy _headers + _redirects + 404 into public/" workflow step only
proved _headers and _redirects existed and copied byte-identically; it left
public/404.html unchecked (a `[ -f ... ] && cp` short-circuit skipped a
missing 404 silently, exit 0) and validated no file's CONTENT — a syntax
error in _headers (e.g. an un-indented header line, orphaned before any
path pattern) or in _redirects (a malformed status code) copies clean and
Cloudflare Pages then silently ignores the broken directive at serve time.
A green gate does not mean the deployed security/routing contract is the
one the repo declares (forkwright/typikon#48).

This script is the sole enforcement point for ci/deploy-manifest.toml: it
reads the manifest (never re-lists members inline — one fact, one place),
fails before deploy when a required member is missing or fails its named
syntax check, and emits a redacted, machine-readable receipt (sha256 +
byte count per present member) so the exact deployed bundle is provable
after the fact, not just asserted at build time.

Usage:
    validate-deploy-bundle.py <public-dir>

Exit:
    0  every required member present and well-formed; receipt printed
    1  a required member is missing or malformed (diagnostics on stderr)
    2  invocation error (bad path, unreadable manifest)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = THEME_ROOT / "ci" / "deploy-manifest.toml"

# WHY a strict token pattern: RFC 7230 field-name is a token of these chars.
# Anything else in the "Name" position of a would-be header line means the
# line is not a header assignment at all — most often an un-indented path
# pattern that got indented by a stray copy/paste and would otherwise be
# silently swallowed as a bogus header.
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_REDIRECT_CODE_RE = re.compile(r"^[0-9]{3}!?$")


def _looks_like_orphaned_header(stripped: str) -> bool:
    """True when an UNINDENTED line has the shape of a header assignment.

    Cloudflare path-pattern lines are URLs: a bare path (`/...`) or an
    absolute `https://...` target (per Cloudflare's own docs, "absolute
    URLs must begin with https"). A column-0 line that is instead a valid
    `Name: value` pair — a real header token before the first `:` — cannot
    be a path pattern under that rule, so it is a header assignment that
    lost its leading whitespace, not a legitimate second block.
    """
    if stripped.startswith("/") or stripped.startswith("https://"):
        return False
    name, sep, _value = stripped.partition(":")
    return bool(sep) and bool(_HEADER_NAME_RE.match(name))


def check_headers_syntax(text: str) -> list[str]:
    """Validate Cloudflare _headers block syntax.

    A path-pattern line starts at column 0; every line indented with
    leading whitespace is a `Name: value` header assignment scoped to the
    most recent path-pattern line above it. A header line before any path
    pattern is an orphan — Cloudflare has no path to apply it to, so it is
    silently dropped rather than erroring, which is exactly the "copies
    clean, does nothing" failure mode this check exists to catch.

    WARNING: that same silent drop is not limited to the FIRST line of the
    file. A header line that loses its leading whitespace anywhere after
    the first path pattern reads, byte-for-byte, exactly like a second
    valid path pattern — a naive "any unindented line starts a new block"
    reading treats it as one and reports zero errors, while Cloudflare
    still drops the orphaned assignment at serve time. `_looks_like_orphaned_header`
    is what distinguishes the two: a genuine path pattern is a URL, an
    orphaned header assignment is not.
    """
    errors: list[str] = []
    seen_pattern = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        if raw[0] not in (" ", "\t"):
            stripped = raw.strip()
            if _looks_like_orphaned_header(stripped):
                errors.append(f"line {lineno}: header assignment outside any indented block (missing leading whitespace, ignored by Cloudflare): {stripped!r}")
                continue
            seen_pattern = True
            continue
        # Indented line: must be a Name: value header assignment.
        if not seen_pattern:
            errors.append(f"line {lineno}: header assignment before any path pattern (orphaned, ignored by Cloudflare): {raw.strip()!r}")
            continue
        stripped = raw.strip()
        if ":" not in stripped:
            errors.append(f"line {lineno}: header line has no ':' separator: {stripped!r}")
            continue
        name, _, _value = stripped.partition(":")
        if not _HEADER_NAME_RE.match(name):
            errors.append(f"line {lineno}: invalid header name {name!r}")
    return errors


def check_redirects_syntax(text: str) -> list[str]:
    """Validate Cloudflare _redirects line syntax.

    Each non-comment, non-blank line is `source destination [code]`. Source
    and destination are whitespace-delimited fields (Cloudflare's own parser
    splits on runs of whitespace, so this mirrors that rather than assuming
    single spaces). An optional trailing status code must be a 3-digit HTTP
    status, with an optional trailing `!` (force flag).
    """
    errors: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) not in (2, 3):
            errors.append(f"line {lineno}: expected 'source destination [code]', got {len(fields)} field(s): {line!r}")
            continue
        source, destination = fields[0], fields[1]
        if not source.startswith("/"):
            errors.append(f"line {lineno}: source must start with '/': {source!r}")
        # WHY: validating a Cloudflare _redirects DESTINATION field's own
        # scheme prefix, not calling a URL — http:// is a legal redirect
        # target the site owner writes; this line makes no request.
        dest_ok = destination.startswith("/") or destination.startswith("http://") or destination.startswith("https://")  # kanon:ignore SECURITY/insecure-transport -- redirect-destination prefix check, no request made
        if not dest_ok:
            errors.append(f"line {lineno}: destination must start with '/', 'http://', or 'https://': {destination!r}")
        if len(fields) == 3 and not _REDIRECT_CODE_RE.match(fields[2]):
            errors.append(f"line {lineno}: status code must be 3 digits (optionally trailed by '!'): {fields[2]!r}")
    return errors


def check_html_syntax(data: bytes) -> list[str]:
    """Best-effort corruption check for the copied 404 page.

    NOTE: not full HTML5 conformance — that is Zola's job at build time,
    upstream of this step. This only catches the failure mode a copy step
    can itself introduce: a truncated write or an accidental zero-byte
    file landing at the expected path and passing an existence-only check.
    """
    if len(data) == 0:
        return ["file is empty"]
    if b"<" not in data:
        return ["file contains no '<' — does not look like HTML"]
    return []


SYNTAX_CHECKS = {
    "headers": lambda data: check_headers_syntax(data.decode("utf-8", errors="replace")),
    "redirects": lambda data: check_redirects_syntax(data.decode("utf-8", errors="replace")),
    "html": check_html_syntax,
    "none": lambda data: [],
}


def load_manifest() -> list[dict]:
    with MANIFEST_PATH.open("rb") as fh:
        doc = tomllib.load(fh)
    return doc.get("member", [])


def build_receipt(public_dir: Path, manifest: list[dict]) -> tuple[dict, list[str]]:
    failures: list[str] = []
    members: dict[str, dict] = {}

    for entry in manifest:
        name = entry["name"]
        required = bool(entry.get("required", False))
        syntax = entry.get("syntax", "none")
        path = public_dir / name
        present = path.is_file()

        if not present:
            members[name] = {"required": required, "present": False}
            if required:
                failures.append(f"required deploy control file '{name}' is missing from {public_dir}")
            continue

        data = path.read_bytes()
        syntax_errors = SYNTAX_CHECKS.get(syntax, SYNTAX_CHECKS["none"])(data)
        members[name] = {
            "required": required,
            "present": True,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "syntax": syntax,
            "syntax_ok": not syntax_errors,
        }
        if syntax_errors:
            for e in syntax_errors:
                failures.append(f"'{name}' failed {syntax} syntax check — {e}")

    receipt = {
        "deploy_bundle_manifest": str(MANIFEST_PATH.relative_to(THEME_ROOT)),
        "members": members,
        "ok": not failures,
    }
    return receipt, failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate-deploy-bundle.py <public-dir>", file=sys.stderr)
        return 2
    public_dir = Path(argv[1])
    if not public_dir.is_dir():
        print(f"error: {public_dir} is not a directory", file=sys.stderr)
        return 2
    if not MANIFEST_PATH.is_file():
        print(f"error: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        return 2

    manifest = load_manifest()
    receipt, failures = build_receipt(public_dir, manifest)

    # WHY RUNNER_TEMP over a bare /tmp literal: a hardcoded shared path is
    # the exact class of defect a sibling fixture harness for the Cloudflare
    # branch-assert step found and fixed (forkwright/typikon#63 PR #146) —
    # concurrent runs collide on one path and the file outlives its run.
    # RUNNER_TEMP is GitHub Actions' own per-job scratch directory; falling
    # back to the current directory (rather than /tmp) keeps a local/test
    # invocation from writing outside its own working tree.
    receipt_dir = Path(os.environ.get("RUNNER_TEMP") or ".")
    receipt_path = receipt_dir / "deploy-bundle-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # NOTE: the receipt is written to `receipt_path` and to stdout (which
    # GitHub Actions captures as the step's log) only — not appended to
    # GITHUB_STEP_SUMMARY. This script also runs once per CASE from
    # ci/check-deploy-bundle-gate.py's fixture harness, inside the same job
    # when that harness itself runs under Actions (it inherits the parent
    # environment); a step-summary write would accumulate one block per
    # fixture case rather than once per real deploy.
    print(json.dumps(receipt, sort_keys=True))

    if failures:
        for f in failures:
            print(f"::error::{f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
