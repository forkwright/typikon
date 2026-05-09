#!/usr/bin/env bash
# Run typikon's consumer-site fixture gate from the repository root.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT/bin/typikon-check" "$ROOT/examples/sample-blog"
"$ROOT/bin/typikon-check" "$ROOT/examples/sample-shop"
