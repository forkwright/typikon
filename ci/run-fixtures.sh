#!/usr/bin/env bash
# Run typikon's consumer-site fixture gate from the repository root.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "$ROOT/ci/check-triad-schema.py"
python3 "$ROOT/ci/check-consumer-schema-registry.py"
python3 "$ROOT/ci/check-page-template-cascade.py"
python3 "$ROOT/ci/check-font-coverage.py"
python3 "$ROOT/ci/check-release-config.py"
python3 "$ROOT/ci/check-asset-provenance.py"
python3 "$ROOT/ci/check-favicon-path.py"
python3 "$ROOT/ci/check-init-favicon-path.py"
python3 "$ROOT/ci/check-control-contrast.py"
python3 "$ROOT/ci/check-home-heading.py"
python3 "$ROOT/ci/check-interactive-contrast.py"
python3 "$ROOT/ci/check-interactive-contrast-selftest.py"
"$ROOT/ci/check-workflow-template.sh" "$ROOT/ci/github-workflow.yml.tmpl"
"$ROOT/ci/check-consumer-check-extension.sh"
"$ROOT/ci/check-fixture-corpus-exemption.sh"

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
