#!/usr/bin/env bash
set -euo pipefail
# csp-enforce — make the strict CSP load-bearing.
#
# Usage:
#     ci/csp-enforce.sh <built-public-dir>
#
# Greps the rendered HTML output for shapes that the strict CSP
# (default-src 'self'; script-src 'self'; style-src 'self'; ...) would
# block at runtime. Any hit fails the build with the offending file
# path. Without this gate, a stray inline <script> ships to production
# and the visitor sees a broken page (CSP refuses, no fallback).
#
# Patterns checked:
#   1. <script>...non-empty content...</script>           inline JS
#   2. <style>...non-empty content...</style>             inline CSS
#   3. on<event>="..."                                    event handler
#   4. style="..."                                        inline style attribute
#   5. javascript:                                         legacy JS URL
#
# Allowlisted (no false positive):
#   - <script src="..." defer></script>      external script ref (no body)
#   - <style></style>                         empty inline style (rare; allowed)
#
# Exit:
#   0  no violations
#   1  violations found (printed with file path + matched line)
#   2  invocation error

# Strict mode globally; the counting section below drops `-e` locally because
# its greps intentionally exit nonzero on no-match and must not abort.

usage() {
    echo "usage: ci/csp-enforce.sh <built-public-dir>" >&2
    exit 2
}

[[ $# -ne 1 ]] && usage
ROOT="$(realpath "$1")"
[[ -d "$ROOT" ]] || { echo "error: $ROOT is not a directory" >&2; exit 2; }

# Restrict to HTML output. Other built artifacts (CSS, JS, fonts) are
# self-evidently first-party because the browser only loads them when
# a CSP-allowed reference points at them — the CSP enforcement happens
# at the HTML-reference level.
mapfile -t FILES < <(find "$ROOT" -type f -name '*.html')

[[ ${#FILES[@]} -eq 0 ]] && {
    echo "warn: no .html files under $ROOT" >&2
    exit 0
}

VIOLATIONS=0
set +e  # count-and-continue: no-match greps below must not abort under -e

# 1. Inline <script>...body...</script>. The body must contain at least
#    one non-whitespace char. <script src="..." defer></script> is fine.
#    We greedy-match-against-line inside one line; then a multi-line check.
# WHY grep -l and not `grep -c | grep -v ':0$'`: with exactly ONE file in
# the list, grep -c omits the filename prefix and prints a bare count, so a
# clean build's `0` does not match the `:0$` filter and is counted as a
# violation. grep -l prints one line per MATCHING file and nothing otherwise,
# which is the quantity this check actually wants and needs no filtering.
inline_script_count=$(grep -lE '<script[^>]*>[[:space:]]*[^[:space:]<]' "${FILES[@]}" 2>/dev/null | wc -l)
if [[ $inline_script_count -gt 0 ]]; then
    echo "csp-enforce: inline <script>...content...</script> found:" >&2
    grep -nHE '<script[^>]*>[[:space:]]*[^[:space:]<]' "${FILES[@]}" >&2
    VIOLATIONS=$((VIOLATIONS + inline_script_count))
fi

# 2. Inline <style>...body...</style>.
# WHY grep -l and not `grep -c | grep -v ':0$'`: with exactly ONE file in
# the list, grep -c omits the filename prefix and prints a bare count, so a
# clean build's `0` does not match the `:0$` filter and is counted as a
# violation. grep -l prints one line per MATCHING file and nothing otherwise,
# which is the quantity this check actually wants and needs no filtering.
inline_style_count=$(grep -lE '<style[^>]*>[[:space:]]*[^[:space:]<]' "${FILES[@]}" 2>/dev/null | wc -l)
if [[ $inline_style_count -gt 0 ]]; then
    echo "csp-enforce: inline <style>...content...</style> found:" >&2
    grep -nHE '<style[^>]*>[[:space:]]*[^[:space:]<]' "${FILES[@]}" >&2
    VIOLATIONS=$((VIOLATIONS + inline_style_count))
fi

# 3. on<event>= handlers. Tight pattern: matches onclick=, onload=, etc.
#    Avoid false positives on attribute values that contain 'on' (e.g.,
#    aria-describedby="region-on-the-front") by anchoring before the `on`
#    to a tag-character context: whitespace, /, or =.
handler_count=$(grep -nHE '[[:space:]/]on[a-z]+="' "${FILES[@]}" 2>/dev/null | wc -l)
if [[ $handler_count -gt 0 ]]; then
    echo "csp-enforce: on*= event handlers found:" >&2
    grep -nHE '[[:space:]/]on[a-z]+="' "${FILES[@]}" >&2
    VIOLATIONS=$((VIOLATIONS + handler_count))
fi

# 4. Inline style="..." attributes. Strict CSP style-src 'self' blocks
#    these unless 'unsafe-inline' is in the policy (which typikon refuses).
inline_style_attr_count=$(grep -nHE '[[:space:]/]style="[^"]+"' "${FILES[@]}" 2>/dev/null | wc -l)
if [[ $inline_style_attr_count -gt 0 ]]; then
    echo "csp-enforce: inline style=\"...\" attributes found:" >&2
    grep -nHE '[[:space:]/]style="[^"]+"' "${FILES[@]}" >&2
    VIOLATIONS=$((VIOLATIONS + inline_style_attr_count))
fi

# 5. javascript: URLs (href="javascript:...", src="javascript:...").
js_url_count=$(grep -nHE '"javascript:' "${FILES[@]}" 2>/dev/null | wc -l)
if [[ $js_url_count -gt 0 ]]; then
    echo "csp-enforce: javascript: URLs found:" >&2
    grep -nHE '"javascript:' "${FILES[@]}" >&2
    VIOLATIONS=$((VIOLATIONS + js_url_count))
fi

if [[ $VIOLATIONS -gt 0 ]]; then
    echo "" >&2
    echo "csp-enforce: $VIOLATIONS violation(s) — strict CSP would block in production." >&2
    echo "Fix by extracting to /css/ /js/ files and referencing via <link>/<script src>." >&2
    exit 1
fi

echo "csp-enforce: ok (${#FILES[@]} HTML files scanned, 0 violations)"
exit 0
