#!/usr/bin/env bash
set -euo pipefail
# asset-provenance — fail closed on undeclared third-party provenance metadata
# in shipped image assets.
#
# Usage:
#     ci/asset-provenance.sh <consumer-site-root>
#
# Walks every .png/.jpg/.jpeg/.svg under <root>/public for an embedded C2PA
# (JUMBF) provenance manifest, using real container parsing rather than a
# byte search for "c2pa" — see ci/asset-provenance-scan.py for why: that
# search both false-positives (the token inside an SVG comment) and
# false-negatives (a JUMBF label that carries no contiguous ASCII, or a
# manifest split across multiple JPEG APP11 segments).
#
# Takes the consumer-site root, not the built public/ dir directly (unlike
# csp-enforce.sh), because declaring intended provenance reads the
# consumer's own config.toml — a stray third-party manifest and a site's
# deliberate Content Credentials both parse identically; only the
# consumer's declaration tells them apart.
#
# A found manifest on a path the consumer has NOT listed in config.toml's
# `extra.c2pa_declared_assets` glob list fails the build, naming the
# offending path, the container, and the manifest's label where the
# manifest carries one. That label is a self-declared JUMBF field, not a
# cryptographically verified issuer — the issuer is not recoverable
# without a COSE/X.509 parser (see the scanner's module docstring and
# forkwright/typikon#148).
#
# Exit:
#   0  no undeclared manifests found
#   1  undeclared manifest(s) found (printed with path + container + label)
#   2  invocation error

usage() {
    echo "usage: ci/asset-provenance.sh <consumer-site-root>" >&2
    exit 2
}

[[ $# -ne 1 ]] && usage
ROOT="$(realpath "$1")"
[[ -d "$ROOT" ]] || { echo "error: $ROOT is not a directory" >&2; exit 2; }

PUBLIC="$ROOT/public"
[[ -d "$PUBLIC" ]] || { echo "error: $PUBLIC is not a directory (zola build did not run)" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mapfile -t FILES < <(find "$PUBLIC" -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.svg' \))

[[ ${#FILES[@]} -eq 0 ]] && {
    echo "warn: no .png/.jpg/.jpeg/.svg files under $PUBLIC" >&2
    exit 0
}

SCAN_ERR="$(mktemp)"
trap 'rm -f "$SCAN_ERR"' EXIT

status=0
python3 "$SCRIPT_DIR/asset-provenance-scan.py" \
    --public-root "$PUBLIC" \
    --config "$ROOT/config.toml" \
    "${FILES[@]}" 2>"$SCAN_ERR" || status=$?

if [[ $status -eq 2 ]]; then
    cat "$SCAN_ERR" >&2
    exit 2
elif [[ $status -eq 1 ]]; then
    VIOLATIONS=$(grep -c 'undeclared C2PA manifest present' "$SCAN_ERR" || true)
    echo "asset-provenance: undeclared manifest(s) found:" >&2
    cat "$SCAN_ERR" >&2
    echo "" >&2
    echo "asset-provenance: reported label(s) above are self-declared JUMBF fields, not verified issuers — see forkwright/typikon#148." >&2
    echo "asset-provenance: $VIOLATIONS asset(s) carry undeclared provenance metadata." >&2
    echo "Fix by stripping the manifest from the asset, or declaring it in config.toml:" >&2
    echo '    [extra]' >&2
    echo '    c2pa_declared_assets = ["/img/your-asset.jpg"]' >&2
    exit 1
fi

cat "$SCAN_ERR" >&2  # any declared-manifest notes
echo "asset-provenance: ok (${#FILES[@]} image/svg files scanned, 0 undeclared manifests)"
exit 0
