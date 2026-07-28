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
while IFS= read -r line; do
    ref="$(printf '%s' "$line" | sed -E 's/^\s*-?\s*uses:\s*[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+@([^ ]+).*/\1/')"
    if [[ ! "$ref" =~ ^[0-9a-f]{40}$ ]]; then
        fail "unpinned action ref (not a commit SHA): $line"
    fi
done < <(grep -E '^\s*-?\s*uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@' "$TMPL")

if [[ "$FAIL" -eq 0 ]]; then
    echo '{"checked":"'"$TMPL"'","status":"pass"}'
fi

exit "$FAIL"
