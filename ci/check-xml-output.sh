#!/usr/bin/env bash
set -euo pipefail

# check-xml-output — the built XML feeds must be well-formed and start at byte zero.
#
# WHY this exists as its own stage: every other gate stage reads HTML. sitemap.xml and
# atom.xml are rendered by Tera templates whose output nothing parsed, so a template
# could emit text ahead of the XML declaration and the whole gate stayed green — the
# feed is served, indexed, and rejected by strict consumers with no local signal.
#
# WARNING: byte zero is the load-bearing part, not just well-formedness. A leading
# blank line or stray character makes the declaration non-first, which several XML
# parsers reject outright even though the rest of the document is valid.
#
# Usage:
#     ci/check-xml-output.sh <built-output-dir>

usage() {
    echo "usage: ci/check-xml-output.sh <built-output-dir>" >&2
    exit 2
}

[[ $# -ne 1 ]] && usage
OUT="$(realpath "$1")"
[[ -d "$OUT" ]] || { echo "error: $OUT is not a directory" >&2; exit 2; }

FAIL=0
CHECKED=0

for name in sitemap.xml atom.xml; do
    path="$OUT/$name"
    [[ -f "$path" ]] || continue
    CHECKED=$((CHECKED + 1))
    if ! python3 - "$path" <<'PY'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
raw = open(path, "rb").read()
declaration = b'<?xml version="1.0" encoding="UTF-8"?>'
if not raw.startswith(declaration):
    head = raw[:60].decode("utf-8", "replace").replace("\n", "\\n")
    print(f"{path}: XML declaration is not at byte zero; file begins {head!r}", file=sys.stderr)
    sys.exit(1)
try:
    ET.parse(path)
except ET.ParseError as exc:
    print(f"{path}: strict XML parse failed: {exc}", file=sys.stderr)
    sys.exit(1)
PY
    then
        FAIL=1
    fi
done

if [[ "$CHECKED" -eq 0 ]]; then
    echo "check-xml-output: no sitemap.xml or atom.xml under $OUT" >&2
    exit 1
fi

[[ "$FAIL" -eq 0 ]] || exit 1
echo "check-xml-output: ok ($CHECKED file(s) well-formed, declaration at byte zero)"
