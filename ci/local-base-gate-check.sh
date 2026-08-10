#!/usr/bin/env bash
set -euo pipefail

# WARNING: -e matters here. Every failure path in this script exits explicitly and
# the script ends in `exit 0`, so without it an UNEXPECTED command failure — a
# missing grep, an unreadable path — falls through to that `exit 0` and the gate
# reports pass on its own internal error. Sibling scripts (csp-enforce.sh,
# run-fixtures.sh) already set it; bin/typikon-check deliberately does not, because
# it accumulates per-stage verdicts instead of exiting at the first failure.

# local-base-gate-check — prove the browser-based gates (pa11y, playwright)
# are pointed at a loopback build, not the site's production origin.
#
# Usage:
#     ci/local-base-gate-check.sh <consumer-site-root>
#
# WHY: the browser gates (pa11y, playwright) must exercise the commit
# under test, not the site's live production origin — see #29 for the
# regression this guards against. bin/typikon-check and the CI templates
# each build a second copy, public-local/, against a loopback base_url for
# the browser gates to consume; this script proves that copy exists and
# that its HTML carries no reference to the site's configured production
# origin.
#
# NOTE: the two producers do not agree on the port, and this check does not
# require them to. bin/typikon-check allocates a free one per run (#51); the
# CI templates pass a fixed 127.0.0.1:8080. What is asserted here is the
# absence of the production origin, which holds for either.
#
# NOTE: scoped to *.html, same rationale as ci/csp-enforce.sh: a browser
# rendering a page only loads what an HTML reference points it at. Non-HTML
# output (atom.xml, sitemap.xml, robots.txt) can legitimately carry an
# absolute production URL — an Atom <author><uri> is a portable identifier
# by convention, not a resource the browser gates fetch — so checking those
# would flag correct output as a regression.
#
# Exit:
#   0  public-local/ exists, contains *.html files, and none of them
#      reference the site's configured production base_url host
#   1  regression: public-local/ missing/empty, or its HTML leaks the
#      production origin
#   2  invocation error

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

# WARNING: match the loopback HOST, not a fixed port. typikon-check now binds an
# OS-allocated port so a stale server cannot intercept the gate on a known one;
# a literal :8080 here would fail every correct run.
if ! grep -rlE "127\.0\.0\.1:[0-9]+" "${FILES[@]}" >/dev/null 2>&1; then
    echo "local-base-gate-check: no file under public-local/ references" >&2
    echo "  127.0.0.1:<port> — the loopback rebuild does not look like it ran" >&2
    echo "  with a loopback --base-url." >&2
    exit 1
fi

echo "local-base-gate-check: ok (${#FILES[@]} *.html files under public-local/, no production-host references, loopback references present)"
exit 0
