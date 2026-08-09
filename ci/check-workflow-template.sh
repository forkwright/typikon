#!/usr/bin/env bash
set -euo pipefail
# check-workflow-template — regression test for consumer-facing GH Actions
# hardening in ci/github-workflow.yml.tmpl.
#
# WHY: this template is copied verbatim into every typikon-consuming site's
# .github/workflows/deploy.yml. A prior version shipped without a
# concurrency group, without a least-privilege permissions block, with
# actions/checkout and actions/setup-node pinned to a mutable major-version
# tag instead of a commit SHA, and without persist-credentials: false on
# checkout — every consumer inherited the gap. typikon's own
# .github/workflows/gate-attestation.yml already follows this hardening
# pattern; this script proves the consumer template matches it.
#
# Usage:
#     ci/check-workflow-template.sh <path-to-template>

usage() {
    echo "usage: ci/check-workflow-template.sh <path-to-template>" >&2
    exit 2
}

[[ $# -ne 1 ]] && usage
TMPL="$1"
[[ -f "$TMPL" ]] || { echo "error: $TMPL not found" >&2; exit 2; }

FAIL=0

fail() {
    echo "FAIL: $1" >&2
    FAIL=1
}

grep -qE '^concurrency:' "$TMPL" || fail "no top-level concurrency: group (overlapping pushes queue stale deploys)"
grep -qE '^permissions:' "$TMPL" || fail "no top-level permissions: block (job defaults to broad GITHUB_TOKEN scope)"
grep -qE '^\s*persist-credentials:\s*false' "$TMPL" || fail "no persist-credentials: false on checkout"

# Every `uses: owner/repo@REF` must pin REF to a 40-char commit SHA, not a
# mutable tag/branch. A trailing `# vX` comment naming the human-readable
# version is fine and expected.
# WARNING: this loop must see EVERY `uses:` line, and must FAIL on a form it
# cannot classify rather than skip it. The previous version selected lines with
# a pattern requiring exactly `owner/repo@ref`, so any other shape matched
# nothing and was never pin-checked — silently. `owner/repo/subdir@ref` is a
# real and common action shape (a composite action in a subdirectory), and it
# fell straight through the check that exists to catch it.
while IFS= read -r line; do
    spec="$(printf '%s' "$line" \
        | sed -E 's/^[[:space:]]*-?[[:space:]]*uses:[[:space:]]*//' \
        | sed -E 's/[[:space:]]*#.*$//' \
        | sed -E 's/^["'"'"']//; s/["'"'"']$//' \
        | sed -E 's/[[:space:]]*$//')"
    case "$spec" in
        ./*|../*)
            # Local action: its code is in this repository, pinned by the commit under review.
            ;;
        docker://*)
            case "$spec" in
                *@sha256:*) ;;
                *) fail "docker action not pinned by digest: $line" ;;
            esac
            ;;
        */*@*)
            ref="${spec##*@}"
            if [[ ! "$ref" =~ ^[0-9a-f]{40}$ ]]; then
                fail "unpinned action ref (not a commit SHA): $line"
            fi
            ;;
        *)
            fail "unrecognised uses: form, cannot verify pinning: $line"
            ;;
    esac
done < <(grep -E '^[[:space:]]*-?[[:space:]]*uses:[[:space:]]' "$TMPL")

# WHY this check: wrangler's engines floor and the Node version this template
# ships are independent values that must agree. When they drifted, a consumer's
# deploy failed AFTER a green build with a message about Node, and nothing in
# the repo related the two. The floor is read from the registry so the check
# tracks the pinned version instead of a second copy of its requirement.
#
# WARNING: every probe below is `|| true`. This script runs under `set -e` with
# pipefail, and a grep that matches nothing exits non-zero — which would abort
# the whole check silently, turning a hardening step into a no-op.
node_major="$(grep -oE "node-version: '[0-9]+'" "$TMPL" 2>/dev/null | head -1 | grep -oE '[0-9]+' || true)"
wrangler_pin="$(grep -oE 'wrangler@[0-9]+\.[0-9]+\.[0-9]+' "$TMPL" 2>/dev/null | head -1 | cut -d@ -f2 || true)"
if [[ -z "$wrangler_pin" ]]; then
    # The template carries a {{ WRANGLER_VERSION }} placeholder; a rendered
    # instance carries the literal. Resolve the placeholder from the defaults.
    defaults="$(dirname "$0")/../bin/typikon-defaults.sh"
    wrangler_pin="$(grep -oE 'WRANGLER_VERSION:=[0-9.]+' "$defaults" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)"
fi
if [[ -n "$node_major" && -n "$wrangler_pin" ]]; then
    floor="$(curl -fsS --max-time 10 "https://registry.npmjs.org/wrangler/${wrangler_pin}" 2>/dev/null \
        | grep -oE '"node":"[^"]*"' | grep -oE '[0-9]+' | head -1 || true)"
    if [[ -z "$floor" ]]; then
        echo "note: npm registry unreachable; wrangler/Node pairing unverified" >&2
    elif [[ "$node_major" -lt "$floor" ]]; then
        fail "Node ${node_major} is below wrangler@${wrangler_pin} engines floor (>=${floor}) — the deploy fails after a green build"
    fi
fi

if [[ "$FAIL" -eq 0 ]]; then
    echo '{"checked":"'"$TMPL"'","status":"pass"}'
fi

exit "$FAIL"
