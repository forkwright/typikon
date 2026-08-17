#!/usr/bin/env bash
set -euo pipefail

# check-fixture-discovery — regression test for forkwright/typikon#169.
#
# WHY: ci/run-fixtures.sh used to hand-list every fixture script by name, one
# line per file. Every branch adding a fixture edited that same shared block,
# so two concurrent fixture-adding branches conflicted there deterministically
# -- proven four times in one day on one branch (#169's own evidence table).
# The fix derives the no-arg fixture set from the filesystem (ci/check-*.sh,
# ci/check-*.py, minus the small named set that takes positional arguments)
# instead of declaring it, and fails closed rather than passing vacuously if
# discovery finds nothing to run.
#
# This script proves both properties against the REAL ci/run-fixtures.sh (its
# `--list` mode: discover, print, exit -- never running the discovered
# fixtures themselves, so this stays cheap and never triggers a zola/lychee/
# pa11y build):
#   1. [the #169 fix itself] dropping a new no-arg check-*.sh/check-*.py file
#      into a ci/-shaped directory makes run-fixtures.sh --list report it,
#      with NO edit to run-fixtures.sh -- proven by diffing the runner's own
#      bytes before and after, not just by reading its output.
#   2. [REQUIRED NEGATIVE FIXTURE] a ci/-shaped directory containing zero
#      check-*.sh/check-*.py files makes run-fixtures.sh refuse (nonzero
#      exit), never a silent/vacuous pass -- exercised by mutating the real,
#      shipped run-fixtures.sh (removing just the empty-set guard block),
#      watching it wrongly print nothing and exit 0 against that same empty
#      directory, then restoring the original bytes and watching it correctly
#      refuse. Restore is verified byte-identical before this script trusts
#      anything past that point.
#   3. the two positional-argument fixtures (check-workflow-template.sh,
#      check-xml-output.sh) are excluded from the auto-run set against the
#      REAL ci/ directory, and a known real no-arg fixture is present --
#      guards the exclusion mechanism's own correctness, not just its
#      existence.
#
# NOTE: takes no arguments -- run as ci/check-fixture-discovery.sh.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT/ci/run-fixtures.sh"
[[ -f "$RUNNER" ]] || { echo "error: $RUNNER not found" >&2; exit 2; }

FAIL=0
fail() {
    echo "FAIL: $1" >&2
    FAIL=1
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ── 1. auto-discovery: a new fixture file needs no runner edit ────────────
DISCOVER_DIR="$WORK/discover-ci"
mkdir -p "$DISCOVER_DIR"
printf '#!/usr/bin/env bash\nexit 0\n' > "$DISCOVER_DIR/check-selftest-probe.sh"
chmod +x "$DISCOVER_DIR/check-selftest-probe.sh"

RUNNER_BEFORE_SHA="$(sha256sum "$RUNNER" | cut -d' ' -f1)"
listed="$(FIXTURE_CI_DIR="$DISCOVER_DIR" "$RUNNER" --list || true)"
RUNNER_AFTER_SHA="$(sha256sum "$RUNNER" | cut -d' ' -f1)"

if [[ "$RUNNER_BEFORE_SHA" != "$RUNNER_AFTER_SHA" ]]; then
    fail "run-fixtures.sh's own bytes changed just from discovery running -- this script must never mutate the runner it is testing"
fi
if ! grep -qxF "check-selftest-probe.sh" <<<"$listed"; then
    fail "dropping check-selftest-probe.sh into a ci/-shaped directory did not make run-fixtures.sh --list report it (got: ${listed:-<empty>}) -- discovery is not deriving from the filesystem"
fi

# ── 2. REQUIRED NEGATIVE FIXTURE: empty discovery must refuse, not pass ───
EMPTY_DIR="$WORK/empty-ci"
mkdir -p "$EMPTY_DIR"
touch "$EMPTY_DIR/not-a-check.txt"  # WHY: present but non-matching, proves the glob (not "dir is empty") is what's checked

RUNNER_ORIGINAL="$(cat "$RUNNER")"

# WHY: strip the empty-set guard block (between the "_fixtures=()" reset and
# the "--list" branch) to reproduce what run-fixtures.sh looked like before
# this property existed, then watch it wrongly pass. Restored unconditionally
# in the trap below even if an assertion here raises.
restore_runner() {
    printf '%s' "$RUNNER_ORIGINAL" > "$RUNNER"
}
trap 'restore_runner; rm -rf "$WORK"' EXIT

python3 - "$RUNNER" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
start = 'if [[ "${#_fixtures[@]}" -eq 0 ]]; then'
end = 'fi\n\nif [[ "${1:-}" == "--list" ]]'
i = text.index(start)
j = text.index(end)
open(path, "w").write(text[:i] + text[j + 3:])
PY

mutated_rc=0
mutated_out="$(FIXTURE_CI_DIR="$EMPTY_DIR" "$RUNNER" --list 2>&1)" || mutated_rc=$?

restore_runner
if [[ "$(cat "$RUNNER")" != "$RUNNER_ORIGINAL" ]]; then
    fail "run-fixtures.sh did not restore byte-identical after the guard-removal mutation -- the real runner is left corrupted"
fi

if [[ "$mutated_rc" -eq 0 ]]; then
    : # expected: pre-guard shape vacuously passes on zero discovered fixtures
else
    fail "the guard-removed runner was expected to vacuously pass (exit 0) on an empty ci/ dir to prove the guard is the thing preventing it, but exited $mutated_rc: $mutated_out"
fi

guarded_rc=0
guarded_out="$(FIXTURE_CI_DIR="$EMPTY_DIR" "$RUNNER" --list 2>&1)" || guarded_rc=$?
if [[ "$guarded_rc" -eq 0 ]]; then
    fail "the restored (guarded) runner exited 0 against a ci/ dir with zero check-*.sh/check-*.py files -- vacuous pass, the exact #169 'Fail if the glob matches nothing' regression"
elif [[ "$guarded_out" != *"vacuous pass"* ]]; then
    fail "the restored runner correctly failed (exit $guarded_rc) but without the expected 'vacuous pass' message; got: $guarded_out"
fi

# ── 3. exclusion correctness against the REAL ci/ directory ───────────────
real_listed="$("$RUNNER" --list)"
for excluded in check-workflow-template.sh check-xml-output.sh; do
    if grep -qxF "$excluded" <<<"$real_listed"; then
        fail "$excluded is a positional-argument fixture (invoked explicitly, with its argument, later in run-fixtures.sh) but appeared in the auto-run --list output -- it would now run twice, once with no argument"
    fi
done
if ! grep -qxF "check-triad-schema.py" <<<"$real_listed"; then
    fail "check-triad-schema.py (a known real no-arg fixture) is missing from run-fixtures.sh --list against the real ci/ directory"
fi

if [[ "$FAIL" -eq 0 ]]; then
    echo '{"checked":"fixture-discovery","status":"pass"}'
fi

exit "$FAIL"
