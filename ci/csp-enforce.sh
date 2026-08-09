#!/usr/bin/env bash
set -euo pipefail
# csp-enforce — make the strict CSP load-bearing.
#
# Usage:
#     ci/csp-enforce.sh <built-public-dir>
#
# Scans the rendered HTML output for shapes that the strict CSP
# (default-src 'self'; script-src 'self'; style-src 'self'; ...) would
# block at runtime. Any hit fails the build with the offending file
# path. Without this gate, a stray inline <script> ships to production
# and the visitor sees a broken page (CSP refuses, no fallback).
#
# WHY an HTML parser (ci/csp-scan.py) and not line-oriented regex: a
# regex gate reads the file one line at a time and only recognizes
# double-quoted attribute values, so a script body spanning multiple
# lines, a single-quoted or unquoted attribute, an uppercase tag/handler
# name, or an HTML-entity-encoded value all pass unflagged even though
# a browser under this CSP blocks every one of them. csp-scan.py parses
# with the stdlib html.parser, so it reasons about elements and
# normalized attribute values instead of line shapes.
#
# Patterns checked (see csp-scan.py for the authoritative language):
#   1. <script>...non-empty content...</script>           inline JS
#   2. <style>...non-empty content...</style>             inline CSS
#   3. on<event>="..."                                    event handler
#   4. style="..."                                        inline style attribute
#   5. javascript:                                         legacy JS URL
#
# Allowlisted (no false positive):
#   - <script src="..." defer></script>      external script ref (no body)
#   - <style></style>                         empty inline style (rare; allowed)
#   - <link rel="stylesheet" href="...">      external stylesheet ref
#
# Exit:
#   0  no violations
#   1  violations found (printed with file path + matched line)
#   2  invocation error

usage() {
    echo "usage: ci/csp-enforce.sh <built-public-dir>" >&2
    exit 2
}

[[ $# -ne 1 ]] && usage
ROOT="$(realpath "$1")"
[[ -d "$ROOT" ]] || { echo "error: $ROOT is not a directory" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Restrict to HTML output. Other built artifacts (CSS, JS, fonts) are
# self-evidently first-party because the browser only loads them when
# a CSP-allowed reference points at them — the CSP enforcement happens
# at the HTML-reference level.
mapfile -t FILES < <(find "$ROOT" -type f -name '*.html')

[[ ${#FILES[@]} -eq 0 ]] && {
    echo "warn: no .html files under $ROOT" >&2
    exit 0
}

SCAN_ERR="$(mktemp)"
trap 'rm -f "$SCAN_ERR"' EXIT

status=0
python3 "$SCRIPT_DIR/csp-scan.py" "${FILES[@]}" 2>"$SCAN_ERR" || status=$?

if [[ $status -eq 2 ]]; then
    cat "$SCAN_ERR" >&2
    exit 2
elif [[ $status -eq 1 ]]; then
    VIOLATIONS=$(wc -l <"$SCAN_ERR")
    echo "csp-enforce: violations found:" >&2
    cat "$SCAN_ERR" >&2
    echo "" >&2
    echo "csp-enforce: $VIOLATIONS violation(s) — strict CSP would block in production." >&2
    echo "Fix by extracting to /css/ /js/ files and referencing via <link>/<script src>." >&2
    exit 1
fi

echo "csp-enforce: ok (${#FILES[@]} HTML files scanned, 0 violations)"
exit 0
