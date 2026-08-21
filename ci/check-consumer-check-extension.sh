#!/usr/bin/env bash
set -euo pipefail

# check-consumer-check-extension — regression test for the consumer gate
# extension point (forkwright/typikon#117).
#
# WHY: bin/typikon-refresh re-renders both ci/github-workflow.yml.tmpl and
# ci/kanon-ci.toml.tmpl wholesale on every bump, with no per-consumer opt-in
# short of the all-or-nothing `# typikon: local` decline marker (#94).
# CLAUDE.md states forge is primary and GitHub is the executable fallback,
# so the extension point must exist on BOTH rendered pipelines — a consumer
# running the primary (forge) pipeline must get the same hook a GitHub-only
# consumer gets, or the "fallback" path is the only one an extension
# actually reaches. Without a declared extension point on both, a consumer
# wanting its own gate check (e.g. a price-vs-source-of-truth check) must
# choose between diverging from every future substrate hardening change or
# shipping an unchecked claim. This script proves, for EACH of the two
# rendered pipelines, that:
#   1. the rendered template carries a guarded stage/step in the right
#      place (after the browser-gate/teardown stage, before deploy);
#   2. bin/typikon-refresh — the real script, not a re-implementation of its
#      logic — preserves that stage/step when it re-renders a consumer
#      instance;
#   3. the stage/step's own command, executed under the same presence
#      test each pipeline performs, actually fails the build when the
#      consumer's script fails, and is a clean no-op when the consumer
#      ships no ci/consumer-check.sh at all. A hook that runs but cannot
#      fail the build is the defect this fleet keeps finding; a hook that
#      errors out when a consumer simply doesn't use the extension point
#      is the opposite defect and just as real.
#
# NOTE: usage — ci/check-consumer-check-extension.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GH_TMPL="$ROOT/ci/github-workflow.yml.tmpl"
TOML_TMPL="$ROOT/ci/kanon-ci.toml.tmpl"

FAIL=0
fail() {
    echo "FAIL: $1" >&2
    FAIL=1
}

# ── Part 1 — GitHub template: presence, guard, placement ──────────────

STEP_LINE="$(grep -n '^\s*- name: Consumer checks$' "$GH_TMPL" | head -1 | cut -d: -f1 || true)"
TEARDOWN_LINE="$(grep -n '^\s*- name: Tear down static server$' "$GH_TMPL" | head -1 | cut -d: -f1 || true)"
DEPLOY_LINE="$(grep -n '^\s*- name: Deploy to Cloudflare Pages$' "$GH_TMPL" | head -1 | cut -d: -f1 || true)"

if [[ -z "$STEP_LINE" ]]; then
    fail "no 'Consumer checks' step in ${GH_TMPL}"
else
    grep -qF "if: hashFiles('ci/consumer-check.sh') != ''" "$GH_TMPL" \
        || fail "'Consumer checks' step is not guarded by hashFiles('ci/consumer-check.sh') != ''"
    grep -qF 'run: bash ci/consumer-check.sh' "$GH_TMPL" \
        || fail "'Consumer checks' step does not run 'bash ci/consumer-check.sh'"
    if [[ -n "$TEARDOWN_LINE" && "$STEP_LINE" -le "$TEARDOWN_LINE" ]]; then
        fail "'Consumer checks' step (line ${STEP_LINE}) is not after 'Tear down static server' (line ${TEARDOWN_LINE}) — it must run after browser-gate teardown so it can inspect built output"
    fi
    if [[ -n "$DEPLOY_LINE" && "$STEP_LINE" -ge "$DEPLOY_LINE" ]]; then
        fail "'Consumer checks' step (line ${STEP_LINE}) is not before 'Deploy to Cloudflare Pages' (line ${DEPLOY_LINE}) — a failure must block deploy"
    fi
fi

# ── Part 1b — forge (kanon-ci.toml) template: presence, guard, placement ──

# WARNING: check the STAGES ARRAY entry and the [stages.consumer-checks]
# block separately. The array line declares the stage runs at all; the
# block declares what it runs. A template could carry one without the
# other (a stage listed but never defined, or defined but never scheduled)
# and either half missing means the extension point doesn't actually fire.
ARR_STAGE_LINE="$(grep -nF '"consumer-checks",' "$TOML_TMPL" | head -1 | cut -d: -f1 || true)"
ARR_TEARDOWN_LINE="$(grep -nF '"teardown-static-server",' "$TOML_TMPL" | head -1 | cut -d: -f1 || true)"
ARR_DEPLOY_LINE="$(grep -nF '"deploy-cloudflare-pages",' "$TOML_TMPL" | head -1 | cut -d: -f1 || true)"
BLOCK_LINE="$(grep -nF '[stages.consumer-checks]' "$TOML_TMPL" | head -1 | cut -d: -f1 || true)"
BLOCK_TEARDOWN_LINE="$(grep -nF '[stages.teardown-static-server]' "$TOML_TMPL" | head -1 | cut -d: -f1 || true)"
BLOCK_DEPLOY_LINE="$(grep -nF '[stages.deploy-cloudflare-pages]' "$TOML_TMPL" | head -1 | cut -d: -f1 || true)"

if [[ -z "$ARR_STAGE_LINE" ]]; then
    fail "no 'consumer-checks' entry in the [pipeline] stages array of ${TOML_TMPL} — the GitHub fallback path gained the extension point but the forge-primary path (CLAUDE.md: 'Forge is primary; GitHub is the executable fallback') did not"
elif [[ -z "$ARR_TEARDOWN_LINE" || "$ARR_STAGE_LINE" -le "$ARR_TEARDOWN_LINE" || -z "$ARR_DEPLOY_LINE" || "$ARR_STAGE_LINE" -ge "$ARR_DEPLOY_LINE" ]]; then
    fail "'consumer-checks' stages-array entry (line ${ARR_STAGE_LINE}) is not between 'teardown-static-server' and 'deploy-cloudflare-pages'"
fi

if [[ -z "$BLOCK_LINE" ]]; then
    fail "no [stages.consumer-checks] block in ${TOML_TMPL}"
else
    grep -qF 'if [ -f ci/consumer-check.sh ]; then' "$TOML_TMPL" \
        || fail "[stages.consumer-checks] does not guard on ci/consumer-check.sh presence"
    grep -qF 'bash ci/consumer-check.sh' "$TOML_TMPL" \
        || fail "[stages.consumer-checks] does not run 'bash ci/consumer-check.sh'"
    if [[ -n "$BLOCK_TEARDOWN_LINE" && "$BLOCK_LINE" -le "$BLOCK_TEARDOWN_LINE" ]]; then
        fail "[stages.consumer-checks] block (line ${BLOCK_LINE}) is not after [stages.teardown-static-server] (line ${BLOCK_TEARDOWN_LINE})"
    fi
    if [[ -n "$BLOCK_DEPLOY_LINE" && "$BLOCK_LINE" -ge "$BLOCK_DEPLOY_LINE" ]]; then
        fail "[stages.consumer-checks] block (line ${BLOCK_LINE}) is not before [stages.deploy-cloudflare-pages] (line ${BLOCK_DEPLOY_LINE})"
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
cp "$GH_TMPL" "$FAKE_TYPIKON/ci/github-workflow.yml.tmpl"
cp "$TOML_TMPL" "$FAKE_TYPIKON/ci/kanon-ci.toml.tmpl"
cp "$ROOT/ci/consumer-python-requirements.in" "$FAKE_TYPIKON/ci/consumer-python-requirements.in"
cp "$ROOT/ci/consumer-python-requirements.lock" "$FAKE_TYPIKON/ci/consumer-python-requirements.lock"
cp "$ROOT/bin/typikon-refresh" "$FAKE_TYPIKON/bin/typikon-refresh"
cp "$ROOT/bin/typikon-defaults.sh" "$FAKE_TYPIKON/bin/typikon-defaults.sh"
# The render path reads ci/tool-lock.toml through ci/toollock.py, so a fake
# typikon root that omits them cannot render at all (forkwright/typikon#58).
cp "$ROOT/ci/tool-lock.toml" "$FAKE_TYPIKON/ci/tool-lock.toml"
cp "$ROOT/ci/toollock.py" "$FAKE_TYPIKON/ci/toollock.py"
cp "$ROOT/ci/render-template.py" "$FAKE_TYPIKON/ci/render-template.py"
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
    if ! "$ROOT/ci/check-workflow-template.sh" "$RENDERED" >/dev/null; then
        fail "rendered ${RENDERED} failed the canonical workflow-template contract"
    fi
    if ! python3 "$ROOT/ci/check-static-server-template.py" "$RENDERED" >/dev/null; then
        fail "rendered ${RENDERED} lost the direct static-server lifecycle contract"
    fi

    # Negative mutation proof: comments cannot satisfy an executable action
    # pin, and package-manager-cache belongs specifically to setup-node's
    # with: block. These are the false-positive shapes that whole-file grep
    # previously accepted.
    python3 - "$RENDERED" "$WORK" <<'PY'
import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
root = Path(sys.argv[2])

checkout = source.replace(
    "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    "actions/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    1,
)
checkout += "\n# actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09\n"
(root / "mutant-checkout.yml").write_text(checkout, encoding="utf-8")

setup = source.replace(
    "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444",
    "actions/setup-node@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    1,
)
setup += "\n# actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444\n"
(root / "mutant-setup.yml").write_text(setup, encoding="utf-8")

cache = source.replace("package-manager-cache: false", "# package-manager-cache: false", 1)
cache_pattern = re.compile(r"^(\s*)persist-credentials:\s*false\s*$", re.MULTILINE)
cache = cache_pattern.sub(
    lambda match: match.group(0) + "\n" + match.group(1) + "package-manager-cache: false",
    cache,
    1,
)
(root / "mutant-cache.yml").write_text(cache, encoding="utf-8")

scalar = source.replace(
    "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    "decoy/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    1,
).replace(
    "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444",
    "decoy/setup-node@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    1,
)
decoy = '''      - name: Decoy action text
        run: |
          uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09
          uses: actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444
          with:
            package-manager-cache: false

'''
scalar = scalar.replace("      - name: Install Zola\n", decoy + "      - name: Install Zola\n", 1)
(root / "mutant-run-scalar.yml").write_text(scalar, encoding="utf-8")

matrix = source.replace(
    "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    "decoy/checkout@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    1,
).replace(
    "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444",
    "decoy/setup-node@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    1,
)
matrix_decoy = '''    strategy:
      matrix:
        include:
          - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09
            with:
              persist-credentials: false
          - name: Decoy setup action
            uses: actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444
            with:
              package-manager-cache: false
'''
matrix = matrix.replace("    runs-on: ubuntu-latest\n", matrix_decoy + "    runs-on: ubuntu-latest\n", 1)
(root / "mutant-matrix-include.yml").write_text(matrix, encoding="utf-8")

persist = source.replace("persist-credentials: false", "# persist-credentials: false", 1)
persist = persist.replace(
    "          package-manager-cache: false\n",
    "          package-manager-cache: false\n          persist-credentials: false\n",
    1,
)
(root / "mutant-persist.yml").write_text(persist, encoding="utf-8")
PY
    for mutant in \
        "$WORK/mutant-checkout.yml" \
        "$WORK/mutant-setup.yml" \
        "$WORK/mutant-cache.yml" \
        "$WORK/mutant-run-scalar.yml" \
        "$WORK/mutant-matrix-include.yml" \
        "$WORK/mutant-persist.yml"
    do
        if "$ROOT/ci/check-workflow-template.sh" "$mutant" >/dev/null 2>&1; then
            fail "workflow-template checker accepted negative mutant ${mutant##*/}"
        fi
    done
fi

RENDERED_TOML="$CONSUMER/.kanon-ci.toml"
if [[ ! -f "$RENDERED_TOML" ]]; then
    fail "typikon-refresh did not render ${RENDERED_TOML}"
else
    grep -qF '"consumer-checks",' "$RENDERED_TOML" \
        || fail "rendered ${RENDERED_TOML} lost the 'consumer-checks' stages-array entry"
    grep -qF '[stages.consumer-checks]' "$RENDERED_TOML" \
        || fail "rendered ${RENDERED_TOML} lost the [stages.consumer-checks] block"
fi

if [[ -f "$RENDERED" && -f "$RENDERED_TOML" ]]; then
    [[ -f "$CONSUMER/themes/typikon/ci/consumer-python-requirements.lock" ]] \
        || fail "refreshed theme submodule lost the consumer Python dependency lock"
    if ! python3 "$ROOT/ci/check-consumer-python-runtime.py" "$RENDERED" "$RENDERED_TOML" >/dev/null; then
        fail "rendered consumer pipelines lost the locked Python runtime contract"
    fi
fi

# ── Part 3 — GitHub: a failing consumer script fails the job, ─────────
# ──            an absent one is a clean no-op                 ─────────

# Simulate hashFiles()'s presence test the same way GitHub Actions
# evaluates it (a glob match against files in the workspace), then run
# the step's own extracted `run:` command with the consumer root as
# cwd — matching ${GITHUB_WORKSPACE} — rather than re-deriving the command
# by hand, so a corrupted rendered command would be caught here too.
gh_hashfiles_nonempty() {
    # WHY: hashFiles() returns '' when no file matches its glob and a
    # content hash otherwise — for a single fixed path (no glob magic)
    # that reduces to plain existence. Used both to decide whether the
    # step would run and, on removal, to prove it evaluates to skip.
    [[ -e "$1" ]]
}

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
        if gh_hashfiles_nonempty "$CONSUMER/ci/consumer-check.sh"; then
            if ! (cd "$CONSUMER" && eval "$RUN_CMD"); then
                fail "GitHub path: a passing ci/consumer-check.sh (exit 0) still failed the step — hashFiles/run wiring is broken"
            fi
        else
            fail "GitHub path: hashFiles presence test found no ci/consumer-check.sh even though the fixture created one"
        fi

        cat > "$CONSUMER/ci/consumer-check.sh" <<'SH'
#!/usr/bin/env bash
exit 1
SH
        chmod +x "$CONSUMER/ci/consumer-check.sh"
        if (cd "$CONSUMER" && eval "$RUN_CMD"); then
            fail "GitHub path: a failing ci/consumer-check.sh (exit 1) did not fail the step — a hook that cannot fail the build is the defect this fleet keeps finding"
        fi

        # Absent case: remove the script entirely and prove the GUARD
        # itself — not the run: command, which would legitimately error
        # if invoked against a missing file — evaluates to skip. This is
        # what actually makes the absent case a no-op on GitHub: the whole
        # step never executes.
        rm -f "$CONSUMER/ci/consumer-check.sh"
        if gh_hashfiles_nonempty "$CONSUMER/ci/consumer-check.sh"; then
            fail "GitHub path: hashFiles-equivalent presence test still true after removing ci/consumer-check.sh — the absent case would not be skipped"
        fi
    fi
fi

# ── Part 3b — forge (kanon-ci.toml): a failing consumer script fails ──
# ──             the stage, an absent one is a clean no-op            ──

if [[ -f "$RENDERED_TOML" ]]; then
    # Extract the [stages.consumer-checks] cmd = """ ... """ body verbatim
    # (rather than re-deriving it) so a corrupted rendered command is
    # caught here too, same rationale as the GitHub RUN_CMD extraction.
    TOML_CMD="$(awk '
        /^\[stages\.consumer-checks\]$/ { found=1; next }
        found && /^cmd = """$/ { incmd=1; next }
        found && incmd && /^"""$/ { exit }
        found && incmd { print }
    ' "$RENDERED_TOML")"
    if [[ -z "$TOML_CMD" ]]; then
        fail "could not extract the [stages.consumer-checks] cmd body from ${RENDERED_TOML}"
    else
        cat > "$CONSUMER/ci/consumer-check.sh" <<'SH'
#!/usr/bin/env bash
exit 0
SH
        chmod +x "$CONSUMER/ci/consumer-check.sh"
        if ! (cd "$CONSUMER" && eval "$TOML_CMD"); then
            fail "forge path: a passing ci/consumer-check.sh (exit 0) still failed [stages.consumer-checks]"
        fi

        cat > "$CONSUMER/ci/consumer-check.sh" <<'SH'
#!/usr/bin/env bash
exit 1
SH
        chmod +x "$CONSUMER/ci/consumer-check.sh"
        if (cd "$CONSUMER" && eval "$TOML_CMD"); then
            fail "forge path: a failing ci/consumer-check.sh (exit 1) did not fail [stages.consumer-checks] — the same class of defect the GitHub path was already hardened against"
        fi

        # Absent case: unlike GitHub, the forge stage has no separate
        # if:-guard — the presence test is INSIDE the extracted cmd body
        # itself ([ -f ci/consumer-check.sh ]). Proving the absent case is
        # a no-op here means actually running the extracted command with
        # no script present and confirming it exits clean, not merely
        # confirming a guard exists.
        rm -f "$CONSUMER/ci/consumer-check.sh"
        if ! (cd "$CONSUMER" && eval "$TOML_CMD"); then
            fail "forge path: [stages.consumer-checks] did not exit clean with no ci/consumer-check.sh present — an absent script must be a no-op, not a failure"
        fi
    fi
fi

if [[ "$FAIL" -eq 0 ]]; then
    echo '{"checked":"consumer-check-extension-point","status":"pass"}'
fi

exit "$FAIL"
