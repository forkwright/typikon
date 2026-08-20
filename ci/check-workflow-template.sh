#!/usr/bin/env bash
set -euo pipefail
# check-workflow-template — regression test for consumer-facing GH Actions
# hardening in ci/github-workflow.yml.tmpl.
#
# WHY: this template is copied verbatim into every typikon-consuming site's
# .github/workflows/deploy.yml, so any gap here becomes a gap in every
# consumer. It must always carry: a top-level concurrency group (so
# overlapping pushes queue rather than race), a least-privilege top-level
# permissions block, persist-credentials: false on checkout, and every
# actions/* reference pinned to a commit SHA rather than a mutable
# major-version tag. typikon's own .github/workflows/gate-attestation.yml
# follows this same hardening pattern; this script proves the consumer
# template matches it.
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

# Every `uses: owner/repo@REF` must pin REF to a 40-char commit SHA, not a
# mutable tag/branch. A trailing `# vX` comment naming the human-readable
# version is fine and expected.
# WARNING: this loop must see EVERY `uses:` line and classify it, including
# `owner/repo/subdir@ref` (a composite action in a subdirectory — a real and
# common shape). A `uses:` line the classifier cannot match must FAIL rather
# than be silently skipped, or an unrecognized shape passes unpinned.
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

# Immutable pins alone do not prove that an action's embedded runtime is still
# supported. The former checkout/setup-node v4 pins both declared Node 20;
# GitHub only kept them running by forcing an unreviewed Node 24 fallback. Bind
# the consumer template to the reviewed Node-24-backed releases and preserve
# its deliberate no-package-cache behavior under setup-node v5.
checkout_node24_pin="fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"
setup_node24_pin="a0853c24544627f65ddf259abe73b1d18a591444"
checkout_node20_pin="11d5960a326750d5838078e36cf38b85af677262"
setup_node20_pin="49933ea5288caeca8642d1e84afbd3f7d6820020"
if ! python3 - "$TMPL" "$checkout_node24_pin" "$setup_node24_pin" "$checkout_node20_pin" "$setup_node20_pin" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
checkout_pin, setup_pin, old_checkout_pin, old_setup_pin = sys.argv[2:]
lines = path.read_text(encoding="utf-8").splitlines()
# YAML block-scalar bodies are data, not mappings. In particular, shell text
# inside `run: |` must not be able to impersonate executable action records.
block_header = re.compile(
    r"^(?P<indent>\s*)(?:-\s+)?[^#:\n][^:\n]*:\s*[>|][+-]?\s*(?:#.*)?$"
)
structural = []
scalar_parent_indent = None
for index, line in enumerate(lines):
    if scalar_parent_indent is not None:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent > scalar_parent_indent:
            continue
        scalar_parent_indent = None
    structural.append((index, line))
    if match := block_header.match(line):
        scalar_parent_indent = len(match.group("indent"))

uses_pattern = re.compile(
    r"^(?P<indent>\s*)(?P<dash>-\s+)?uses:\s+"
    r"(?P<action>actions/(?:checkout|setup-node))@(?P<pin>[0-9a-f]{40})"
    r"(?:\s+#.*)?$"
)
records = []
for index, line in structural:
    match = uses_pattern.match(line)
    if match:
        records.append((index, match))


def owning_step(index, match):
    """Return (start, list-indent) only for an item under jobs.<job>.steps."""
    def preceding_parent(before, child_indent):
        for candidate_index, line in reversed(structural):
            if candidate_index >= before or not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent < child_indent:
                return candidate_index, indent, line.strip()
        return None

    uses_indent = len(match.group("indent"))
    if match.group("dash"):
        step_start, step_indent = index, uses_indent
    else:
        owner = preceding_parent(index, uses_indent)
        if owner is None:
            return None
        step_start, step_indent, owner_text = owner
        if step_indent != uses_indent - 2 or not owner_text.startswith("- "):
            return None

    steps_parent = preceding_parent(step_start, step_indent)
    if steps_parent is None:
        return None
    steps_index, steps_indent, steps_text = steps_parent
    if steps_indent != step_indent - 2 or steps_text != "steps:":
        return None

    job_parent = preceding_parent(steps_index, steps_indent)
    if job_parent is None:
        return None
    job_index, job_indent, job_text = job_parent
    if (
        job_indent != steps_indent - 2
        or not re.fullmatch(r"[A-Za-z0-9_.-]+:\s*(?:#.*)?", job_text)
        or job_text == "jobs:"
    ):
        return None

    jobs_parent = preceding_parent(job_index, job_indent)
    if jobs_parent is None:
        return None
    _, jobs_indent, jobs_text = jobs_parent
    if jobs_indent != job_indent - 2 or jobs_text != "jobs:":
        return None
    return step_start, step_indent

expected = {
    "actions/checkout": checkout_pin,
    "actions/setup-node": setup_pin,
}
for action, pin in expected.items():
    matches = [(index, match) for index, match in records if match.group("action") == action]
    if (
        len(matches) != 1
        or matches[0][1].group("pin") != pin
        or owning_step(*matches[0]) is None
    ):
        print(f"{action} must appear exactly once at reviewed pin {pin}", file=sys.stderr)
        raise SystemExit(1)
if any(match.group("pin") in {old_checkout_pin, old_setup_pin} for _, match in records):
    print("obsolete Node-20-backed action pin remains executable", file=sys.stderr)
    raise SystemExit(1)

def direct_with_values(action, key):
    action_index, action_match = next(
        (index, match) for index, match in records if match.group("action") == action
    )
    step_start, step_indent = owning_step(action_index, action_match)
    step_end = len(lines)
    for index, line in structural:
        if index <= step_start:
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < step_indent or (indent == step_indent and line.lstrip().startswith("- ")):
            step_end = index
            break

    with_index = None
    with_indent = None
    for index, line in structural:
        if index <= action_index or index >= step_end:
            continue
        if line.strip() == "with:":
            indent = len(line) - len(line.lstrip())
            if indent == step_indent + 2:
                with_index = index
                with_indent = indent
                break
    if with_index is None or with_indent is None:
        return []

    values = []
    key_pattern = re.compile(r"^\s*" + re.escape(key) + r":\s*(\S+)\s*(?:#.*)?$")
    for index, line in structural:
        if index <= with_index or index >= step_end:
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= with_indent:
            break
        match = key_pattern.match(line)
        if match and indent == with_indent + 2:
            values.append(match.group(1))
    return values


if direct_with_values("actions/checkout", "persist-credentials") != ["false"]:
    print("checkout with: must contain exactly persist-credentials: false", file=sys.stderr)
    raise SystemExit(1)
if direct_with_values("actions/setup-node", "package-manager-cache") != ["false"]:
    print("setup-node with: must contain exactly package-manager-cache: false", file=sys.stderr)
    raise SystemExit(1)
PY
then
    fail "Node-action runtime/cache contract is not satisfied"
fi

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
