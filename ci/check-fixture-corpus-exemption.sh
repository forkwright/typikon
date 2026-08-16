#!/usr/bin/env bash
set -euo pipefail

# check-fixture-corpus-exemption — regression test for forkwright/typikon#122.
#
# WHY: .github/workflows/gate-attestation.yml calls forkwright/.github's
# hybrid-gate.yml reusable with a docs_only_exemption input. The reusable's
# classifier (check-trailer job, "Check for docs-only changeset" step) treats
# every changed path matching *.md/docs/*/llms.txt as documentation and skips
# full-gate-build. examples/*/content/**.md is NOT documentation -- it is the
# fixture corpus ci/run-fixtures.sh builds and asserts against (bin/typikon-
# check zola-builds examples/sample-blog and examples/sample-shop). A diff
# confined to that corpus matched the pattern and skipped the one job that
# would have caught a broken fixture -- proven empirically by #120 (run
# 31339059510: three green checks, full-gate-build never ran, on a PR that
# touched only the two fixture files reproduced below).
#
# WHY this repo cannot use the pattern-level exemption at all: the classifier
# lives in forkwright/.github (a separate repo, pinned by SHA below) and keys
# on file extension alone -- it has no notion of "gate input" vs
# "documentation" to parameterize per-caller. typikon's fix is therefore
# local: docs_only_exemption is false in gate-attestation.yml, so
# full-gate-build always runs regardless of what changed. The fleet-wide fix
# (teach the shared classifier to exclude gate-input globs like examples/**)
# is out of scope here -- a shared reusable used by every fleet Rust+Zola
# repo wants deliberate review, not a drive-by edit from a single-repo fix
# (#122's own "Desired correction" section says so explicitly).
#
# WHAT this proves, as a negative case:
#   1. [control] the corpus-only diff below DOES match the shared
#      classifier's bare path pattern -- i.e. this really is the shape #120
#      hit, not a pattern this script invented.
#   2. [regression guard] applying THIS repo's actual configured
#      docs_only_exemption value (read from the real workflow file, never
#      hardcoded here) to that same diff yields NOT exempt. This fails loudly
#      if gate-attestation.yml is ever edited back to docs_only_exemption:
#      true without the shared classifier also being parameterized -- the
#      exact regression #122 reports.
#
# NOTE: the case pattern below is a manual mirror of forkwright/.github's
# hybrid-gate.yml "Check for docs-only changeset" step, at the SHA
# gate-attestation.yml currently pins (read below, not hardcoded). It cannot
# import that file -- a workflow_call reusable in another repo, not a local
# composite action -- so this is structural duplication, the same shape
# hybrid-gate.yml's own fleet-git-credentials comment names when it
# duplicates aletheia's guard by hand. A divergence here would make
# assertion 1 pass vacuously instead of failing loudly, so re-verify this
# pattern by hand against forkwright/.github on any SHA bump.
#
# Usage:
#     ci/check-fixture-corpus-exemption.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW="$ROOT/.github/workflows/gate-attestation.yml"
[[ -f "$WORKFLOW" ]] || { echo "error: $WORKFLOW not found" >&2; exit 2; }

FAIL=0
fail() {
    echo "FAIL: $1" >&2
    FAIL=1
}

# ── read this repo's actual configured value, not an assumed one ──────
EXEMPTION_LINE="$(grep -E '^[[:space:]]*docs_only_exemption:[[:space:]]*(true|false)[[:space:]]*$' "$WORKFLOW" || true)"
if [[ -z "$EXEMPTION_LINE" ]]; then
    echo "FAIL: no 'docs_only_exemption: true|false' input line found in $WORKFLOW -- cannot verify the exemption predicate" >&2
    exit 1
fi
DOCS_ONLY_EXEMPTION="$(printf '%s' "$EXEMPTION_LINE" | grep -oE 'true|false')"

PIN_SHA="$(grep -oE 'hybrid-gate\.yml@[0-9a-f]{40}' "$WORKFLOW" | cut -d@ -f2 || true)"

# ── the known-bad diff: PR #120's exact fixture-only changeset ────────
DIFF_PATHS=(
    "examples/sample-shop/content/sizing.md"
    "examples/sample-shop/content/sizing-timed.md"
)
for p in "${DIFF_PATHS[@]}"; do
    [[ -f "$ROOT/$p" ]] || fail "fixture path $p no longer exists -- update this script's known-bad diff to a current fixture-corpus change"
done

# ── mirror of hybrid-gate.yml's check-trailer docs-only pattern ───────
# case *.md|docs/*|llms.txt -- verbatim from the pinned SHA's
# "Check for docs-only changeset" step; see the NOTE above.
pattern_match=true
for p in "${DIFF_PATHS[@]}"; do
    case "$p" in
        *.md | docs/* | llms.txt) ;;
        *) pattern_match=false ;;
    esac
done

# 1. Control: the corpus-only diff really does match the bare pattern, so
#    this is a faithful reproduction of #122's known-bad case.
if [[ "$pattern_match" != true ]]; then
    fail "control failed: ${DIFF_PATHS[*]} do not match the shared classifier's docs-only pattern (*.md|docs/*|llms.txt) -- this script no longer reproduces #122's known-bad case, pick fixture-corpus paths that do"
fi

# 2. Regression guard: the EFFECTIVE decision the reusable computes is
#    pattern_match gated by the caller's docs_only_exemption input -- see
#    hybrid-gate.yml's `if [ "$DOCS_ONLY_EXEMPTION" != "true" ]; then
#    docs_only=false; fi` short-circuit ahead of the pattern loop.
if [[ "$DOCS_ONLY_EXEMPTION" == "true" && "$pattern_match" == true ]]; then
    effective_docs_only=true
else
    effective_docs_only=false
fi

if [[ "$effective_docs_only" == true ]]; then
    fail "gate-attestation.yml (docs_only_exemption: ${DOCS_ONLY_EXEMPTION}, hybrid-gate.yml@${PIN_SHA:-unknown}) would classify a diff confined to ${DIFF_PATHS[*]} as docs-only and skip full-gate-build -- this is #122: the fixture corpus is not documentation. Set docs_only_exemption: false in ${WORKFLOW}."
fi

if [[ "$FAIL" -eq 0 ]]; then
    echo '{"checked":"fixture-corpus-exemption","status":"pass","docs_only_exemption":"'"$DOCS_ONLY_EXEMPTION"'","pinned_sha":"'"${PIN_SHA:-unknown}"'"}'
fi

exit "$FAIL"
