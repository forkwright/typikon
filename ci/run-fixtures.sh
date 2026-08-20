#!/usr/bin/env bash
# Run typikon's consumer-site fixture gate from the repository root.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# WHY(forkwright/typikon#169): overridable only so ci/check-fixture-discovery.sh
# can point discovery at a scratch ci/-shaped directory and exercise the
# discovery + empty-set guard below without running the real (zola/lychee/
# pa11y-dependent, slow) fixture suite. Unset in every real invocation, so
# production behavior always resolves to the ROOT-derived ci/ directory below.
FIXTURE_CI_DIR="${FIXTURE_CI_DIR:-$ROOT/ci}"

# WHY: these check-* scripts take positional arguments (a template path, a
# built-site dir) and are invoked explicitly, with those arguments, further
# down. The no-arg glob discovery below cannot express that call shape, so
# each exclusion is named here with the reason it is not auto-run.
#
# A check that needs BUILT output belongs here by construction, not by choice:
# discovery runs before any example is built, so a no-arg invocation of one
# either fails on its usage line or -- worse -- inspects a directory that does
# not exist yet and reports a vacuous pass.
declare -A ARG_TAKING_FIXTURES=(
    [check-workflow-template.sh]="invoked below with github-workflow.yml.tmpl"
    [check-xml-output.sh]="invoked below per-example against the built public/ dir"
    [check-faq-rendering.py]="invoked below against sample-shop's built public/ dir"
    [check-product-sale-state.py]="invoked below against sample-shop's built public/ dir"
)

mapfile -t _discovered < <(
    find "$FIXTURE_CI_DIR" -maxdepth 1 -type f \( -name 'check-*.sh' -o -name 'check-*.py' \) -printf '%f\n' \
        | LC_ALL=C sort
)

# WHY(forkwright/typikon#169 "Fail if the glob matches nothing, rather than
# reporting a vacuous pass"): a runner that discovers zero fixtures and
# exits 0 is the empty-keep-set defect class, just in a new shape.
_fixtures=()
for _f in "${_discovered[@]}"; do
    [[ -n "${ARG_TAKING_FIXTURES[$_f]:-}" ]] && continue
    _fixtures+=("$_f")
done

if [[ "${#_fixtures[@]}" -eq 0 ]]; then
    echo "run-fixtures: ci/check-*.sh + ci/check-*.py under $FIXTURE_CI_DIR found ${#_discovered[@]} file(s), ${#ARG_TAKING_FIXTURES[@]} of them excluded (arg-taking) -- 0 left to run. Refusing to report a vacuous pass." >&2
    exit 1
fi

if [[ "${1:-}" == "--list" ]]; then
    printf '%s\n' "${_fixtures[@]}"
    exit 0
fi

for _f in "${_fixtures[@]}"; do
    case "$_f" in
        *.py) python3 "$FIXTURE_CI_DIR/$_f" ;;
        *.sh) "$FIXTURE_CI_DIR/$_f" ;;
    esac
done

"$ROOT/ci/check-workflow-template.sh" "$ROOT/ci/github-workflow.yml.tmpl"

"$ROOT/bin/typikon-check" "$ROOT/examples/sample-blog"
"$ROOT/bin/typikon-check" "$ROOT/examples/sample-shop"

# typikon-check's zola-build-local stage must have populated public-local/
# with a loopback-base_url rebuild for the two lines above to have made
# this a meaningful check — see ci/local-base-gate-check.sh.
"$ROOT/ci/local-base-gate-check.sh" "$ROOT/examples/sample-blog"
"$ROOT/ci/local-base-gate-check.sh" "$ROOT/examples/sample-shop"

# The XML feeds are the only built output no other stage parses. Checked against
# public/ (the production build) rather than public-local/, since that is what
# consumers deploy.
"$ROOT/ci/check-xml-output.sh" "$ROOT/examples/sample-blog/public"
"$ROOT/ci/check-xml-output.sh" "$ROOT/examples/sample-shop/public"

# sample-shop only: its faq.md carries the colliding-question and script-breakout
# fixture content this check exists to witness. Pointed at the production build
# for the same reason as the feeds above.
"$ROOT/ci/check-faq-rendering.py" "$ROOT/examples/sample-shop/public"

# sample-shop only: four product states prove that catalog price remains
# visible while checkout, shipping, and Offer URLs fail closed on sourced
# readiness. The checker also exercises the paired-fact JSON Schema contract.
python3 "$ROOT/ci/check-product-sale-state.py" "$ROOT/examples/sample-shop/public"
