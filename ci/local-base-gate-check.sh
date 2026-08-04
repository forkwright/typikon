#!/usr/bin/env bash
# local-base-gate-check — prove the browser-based gates (pa11y, playwright)
# are pointed at a loopback build, not the site's production origin.
#
# Usage:
#     ci/local-base-gate-check.sh <consumer-site-root>
#
# Regression coverage for forkwright/typikon#29: the CI/local gate used
# to build once with the site's production base_url and serve that same
# public/ to pa11y and playwright. Any get_url()-derived absolute
# reference baked into the rendered HTML (canonical link, og:url,
# JSON-LD, a consumer's own get_url()'d asset href, ...) then pointed
# the browser at the LIVE deployed site instead of the commit under
# test — a change could pass browser gates by matching what's already
# in production, or fail them by mismatching a local-only fix.
#
# bin/typikon-check and the CI templates now build a second copy,
# public-local/, with --base-url http://127.0.0.1:8080 — the only copy
# the browser gates ever see. This script proves that copy exists and
# that its HTML carries no reference to the site's configured
# production origin.
#
# Scoped to *.html, same rationale as ci/csp-enforce.sh: a browser
# rendering a page only loads what an HTML reference points it at.
# Non-HTML output (atom.xml, sitemap.xml, robots.txt) can legitimately
# carry an absolute production URL — an Atom <author><uri> is a portable
# identifier by convention, not a resource the browser gates fetch — so
# checking those would flag correct output as a regression.
#
# Exit:
#   0  public-local/ exists, contains *.html files, and none of them
#      reference the site's configured production base_url host
#   1  regression: public-local/ missing/empty, or its HTML leaks the
#      production origin
#   2  invocation error

set -uo pipefail

usage() {
    echo "usage: ci/local-base-gate-check.sh <consumer-site-root>" >&2
    exit 2
}

[[ $# -ne 1 ]] && usage
ROOT="$(realpath "$1")"
[[ -f "$ROOT/config.toml" ]] || { echo "error: $ROOT has no config.toml" >&2; exit 2; }

LOCAL_DIR="$ROOT/public-local"
if [[ ! -d "$LOCAL_DIR" ]]; then
    echo "local-base-gate-check: $LOCAL_DIR does not exist — the loopback-base_url" >&2
    echo "  build never ran. Browser gates would fall back to serving public/," >&2
    echo "  the production build (forkwright/typikon#29)." >&2
    exit 1
fi

mapfile -t FILES < <(find "$LOCAL_DIR" -type f -name '*.html')
if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "local-base-gate-check: no *.html files under $LOCAL_DIR" >&2
    exit 1
fi

BASE_URL=$(grep -E '^base_url\s*=' "$ROOT/config.toml" \
    | head -1 \
    | sed -E 's/^base_url\s*=\s*"([^"]+)".*/\1/' \
    | sed 's:/$::')
BASE_HOST=$(printf '%s' "$BASE_URL" | sed -E 's|^https?://||' | sed -E 's|/.*$||')

if [[ -z "$BASE_HOST" ]]; then
    echo "local-base-gate-check: could not read base_url from $ROOT/config.toml" >&2
    exit 2
fi

LEAKS=$(grep -rlF "$BASE_HOST" "${FILES[@]}" 2>/dev/null || true)
if [[ -n "$LEAKS" ]]; then
    echo "local-base-gate-check: public-local/ references production host '$BASE_HOST':" >&2
    echo "$LEAKS" >&2
    echo "" >&2
    echo "The build served to pa11y/playwright must be built with a loopback" >&2
    echo "base_url so nothing in it resolves to the deployed site." >&2
    exit 1
fi

if ! grep -rlF "127.0.0.1:8080" "${FILES[@]}" >/dev/null 2>&1; then
    echo "local-base-gate-check: no file under public-local/ references" >&2
    echo "  127.0.0.1:8080 — the loopback rebuild does not look like it ran" >&2
    echo "  with --base-url http://127.0.0.1:8080." >&2
    exit 1
fi

echo "local-base-gate-check: ok (${#FILES[@]} *.html files under public-local/, no production-host references, loopback references present)"
exit 0
