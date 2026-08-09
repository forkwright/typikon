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

if [[ "$FAIL" -eq 0 ]]; then
    echo '{"checked":"'"$TMPL"'","status":"pass"}'
fi

exit "$FAIL"
