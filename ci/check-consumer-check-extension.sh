#!/usr/bin/env bash
set -euo pipefail

# check-consumer-check-extension — regression test for the consumer gate
# extension point (forkwright/typikon#117).
#
# WHY: bin/typikon-refresh re-renders ci/github-workflow.yml.tmpl wholesale
# on every bump, with no per-consumer opt-in short of the all-or-nothing
# `# typikon: local` decline marker (#94). Without a declared extension
# point, a consumer wanting its own gate check (e.g. a price-vs-source-of-
# truth check) must choose between diverging from every future substrate
# hardening change or shipping an unchecked claim. This script proves three
# things hold together, not just that the template text looks right:
#   1. the rendered template carries a hashFiles-guarded step in the right
#      place (after the browser-gate/teardown steps, before deploy);
#   2. bin/typikon-refresh — the real script, not a re-implementation of its
#      logic — preserves that step when it re-renders a consumer instance;
#   3. the step's own `run:` command, executed under the same presence
#      test hashFiles() performs, actually fails the job when the
#      consumer's script fails. A hook that runs but cannot fail the build
#      is the defect this fleet keeps finding.
#
# Usage:
#     ci/check-consumer-check-extension.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPL="$ROOT/ci/github-workflow.yml.tmpl"

FAIL=0
fail() {
    echo "FAIL: $1" >&2
    FAIL=1
}

# ── Part 1 — the template itself: presence, guard, placement ──────────

STEP_LINE="$(grep -n '^\s*- name: Consumer checks$' "$TMPL" | head -1 | cut -d: -f1 || true)"
TEARDOWN_LINE="$(grep -n '^\s*- name: Tear down static server$' "$TMPL" | head -1 | cut -d: -f1 || true)"
DEPLOY_LINE="$(grep -n '^\s*- name: Deploy to Cloudflare Pages$' "$TMPL" | head -1 | cut -d: -f1 || true)"

if [[ -z "$STEP_LINE" ]]; then
    fail "no 'Consumer checks' step in ${TMPL}"
else
    grep -qF "if: hashFiles('ci/consumer-check.sh') != ''" "$TMPL" \
        || fail "'Consumer checks' step is not guarded by hashFiles('ci/consumer-check.sh') != ''"
    grep -qF 'run: bash ci/consumer-check.sh' "$TMPL" \
        || fail "'Consumer checks' step does not run 'bash ci/consumer-check.sh'"
    if [[ -n "$TEARDOWN_LINE" && "$STEP_LINE" -le "$TEARDOWN_LINE" ]]; then
        fail "'Consumer checks' step (line ${STEP_LINE}) is not after 'Tear down static server' (line ${TEARDOWN_LINE}) — it must run after browser-gate teardown so it can inspect built output"
    fi
    if [[ -n "$DEPLOY_LINE" && "$STEP_LINE" -ge "$DEPLOY_LINE" ]]; then
        fail "'Consumer checks' step (line ${STEP_LINE}) is not before 'Deploy to Cloudflare Pages' (line ${DEPLOY_LINE}) — a failure must block deploy"
    fi
fi

# ── Part 2 — round trip through the real typikon-refresh ──────────────

# WARNING: never point TYPIKON_ROOT at this checkout. typikon-refresh's
# step 1 unconditionally runs `git pull --ff-only origin main` inside
# TYPIKON_ROOT — against this worktree's own feature branch that would
# refuse (diverged from origin/main) or, worse, mutate shared git state.
# Build an isolated fake typikon source tree instead, so the refresh
# exercises real script logic against a throwaway git remote.
WORK="$(mktemp -d -t typikon-consumer-check-check.XXXXXX)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

FAKE_TYPIKON="$WORK/fake-typikon"
CONSUMER="$WORK/consumer"

mkdir -p "$FAKE_TYPIKON/ci" "$FAKE_TYPIKON/bin"
cp "$TMPL" "$FAKE_TYPIKON/ci/github-workflow.yml.tmpl"
cp "$ROOT/ci/kanon-ci.toml.tmpl" "$FAKE_TYPIKON/ci/kanon-ci.toml.tmpl"
cp "$ROOT/bin/typikon-refresh" "$FAKE_TYPIKON/bin/typikon-refresh"
cp "$ROOT/bin/typikon-defaults.sh" "$FAKE_TYPIKON/bin/typikon-defaults.sh"
chmod +x "$FAKE_TYPIKON/bin/typikon-refresh"
echo 'name = "fake-typikon"' > "$FAKE_TYPIKON/theme.toml"

# WARNING: a caller's process tree (a git hook invoking this script) can export
# GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE. Without unsetting them first, the `git
# init` calls below would silently no-op against that ambient repo instead of
# creating the isolated fixtures this script depends on, and every following
# `git add`/`git commit`/`git clone` would land on the CALLER's live repo.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

git -C "$FAKE_TYPIKON" init -q -b main
git -C "$FAKE_TYPIKON" -c user.email=fixture@typikon.test -c user.name=fixture add -A
git -C "$FAKE_TYPIKON" -c user.email=fixture@typikon.test -c user.name=fixture commit -q -m init

mkdir -p "$CONSUMER/themes" "$CONSUMER/ci"
git -C "$CONSUMER" init -q -b main
git clone -q "$FAKE_TYPIKON" "$CONSUMER/themes/typikon"

cat > "$CONSUMER/ci/consumer-check.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
chmod +x "$CONSUMER/ci/consumer-check.sh"

if ! REFRESH_LOG="$(cd "$CONSUMER" && TYPIKON_PROJECT_NAME=fixture-consumer "$CONSUMER/themes/typikon/bin/typikon-refresh" 2>&1)"; then
    fail "bin/typikon-refresh exited non-zero against the fixture consumer:"
    echo "$REFRESH_LOG" >&2
fi

RENDERED="$CONSUMER/.github/workflows/deploy.yml"
if [[ ! -f "$RENDERED" ]]; then
    fail "typikon-refresh did not render ${RENDERED}"
else
    grep -qF "if: hashFiles('ci/consumer-check.sh') != ''" "$RENDERED" \
        || fail "rendered ${RENDERED} lost the hashFiles guard — a refresh would silently drop a consumer's gate check"
fi

# ── Part 3 — a failing consumer script actually fails the job ─────────

# Simulate hashFiles()'s presence test the same way GitHub Actions
# evaluates it (a glob match against files in the workspace), then run
# the step's own extracted `run:` command with the consumer root as
# cwd — matching ${GITHUB_WORKSPACE} — rather than re-deriving the command
# by hand, so a corrupted rendered command would be caught here too.
if [[ -f "$RENDERED" ]]; then
    # WARNING: the step body carries a comment line between `if:` and
    # `run:` (see the template), so a fixed-offset `grep -A1` silently
    # captures the comment instead — evaluating a comment is a no-op that
    # exits 0 and reads as "the check passed" no matter what the
    # consumer's script does. Scan forward from the `if:` line for the
    # first actual `run:` line instead of assuming a fixed offset.
    RUN_CMD="$(awk '
        /if: hashFiles\(.ci\/consumer-check\.sh.\) != ./ { found=1; next }
        found && /^\s*run:\s*/ { sub(/^\s*run:\s*/, ""); print; exit }
    ' "$RENDERED")"
    if [[ -z "$RUN_CMD" ]]; then
        fail "could not extract the 'Consumer checks' step's run: command from ${RENDERED}"
    else
        if compgen -G "$CONSUMER/ci/consumer-check.sh" >/dev/null; then
            if ! (cd "$CONSUMER" && eval "$RUN_CMD"); then
                fail "a passing ci/consumer-check.sh (exit 0) still failed the step — hashFiles/run wiring is broken"
            fi
        else
            fail "hashFiles presence test found no ci/consumer-check.sh even though the fixture created one"
        fi

        cat > "$CONSUMER/ci/consumer-check.sh" <<'SH'
#!/usr/bin/env bash
exit 1
SH
        chmod +x "$CONSUMER/ci/consumer-check.sh"
        if (cd "$CONSUMER" && eval "$RUN_CMD"); then
            fail "a failing ci/consumer-check.sh (exit 1) did not fail the step — a hook that cannot fail the build is the defect this fleet keeps finding"
        fi
    fi
fi

if [[ "$FAIL" -eq 0 ]]; then
    echo '{"checked":"consumer-check-extension-point","status":"pass"}'
fi

exit "$FAIL"
