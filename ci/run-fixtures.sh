#!/usr/bin/env bash
# Run typikon's consumer-site fixture gate from the repository root.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "$ROOT/ci/check-triad-schema.py"
python3 "$ROOT/ci/check-font-coverage.py"
python3 "$ROOT/ci/check-release-config.py"
"$ROOT/ci/check-workflow-template.sh" "$ROOT/ci/github-workflow.yml.tmpl"

"$ROOT/bin/typikon-check" "$ROOT/examples/sample-blog"
"$ROOT/bin/typikon-check" "$ROOT/examples/sample-shop"

# typikon-check's zola-build-local stage must have populated public-local/
# with a loopback-base_url rebuild for the two lines above to have made
# this a meaningful check — see ci/local-base-gate-check.sh.
"$ROOT/ci/local-base-gate-check.sh" "$ROOT/examples/sample-blog"
"$ROOT/ci/local-base-gate-check.sh" "$ROOT/examples/sample-shop"
