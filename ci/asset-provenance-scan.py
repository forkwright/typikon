#!/usr/bin/env python3
"""asset-provenance-scan — container-aware C2PA/JUMBF manifest detector.

Parses PNG chunks, JPEG segments, and SVG XML with real container/format
readers instead of a literal byte search for "c2pa" — the same rationale
csp-scan.py already established for CSP, applied one layer down (see
ci/csp-enforce.sh header). A literal-string search on these three formats
both false-positives (the token in an SVG <!-- comment -->, which an XML
parser never surfaces as an element) and false-negatives (a JUMBF label
field carrying no human-readable text, or a manifest split byte-wise
across multiple JPEG APP11 marker segments with no single contiguous
run of the string anywhere in the file).

Detection is gated on presence in the exact channel each container format
reserves for embedding a JUMBF box (PNG's `caBX` ancillary chunk, JPEG's
APP11 marker segments carrying a `JP` common identifier, SVG's namespaced
<c2pa:manifest> element) — not on successfully decoding the manifest's
internal structure. A channel carrying bytes is already the positive
signal regardless of whether those bytes parse further, which is what
keeps this fail-closed against a still-valid manifest whose internals
this stdlib-only parser cannot fully walk (INVARIANT below).

INVARIANT: a manifest's true issuer lives inside an X.509 certificate
embedded in a COSE-signed claim several JUMBF box levels deeper, CBOR/
ASN.1-encoded — outside stdlib reach without a new dependency (forbidden
by forkwright/typikon#137). The JUMBF description box's optional `label`
field is the deepest identifying string this parser can reach; it is
reported as-is and never fabricated when absent.

Usage:
    ci/asset-provenance-scan.py --public-root <dir> --config <config.toml> <file> [<file> ...]

Exit:
    0  no undeclared manifests found
    1  undeclared manifest(s) found (each printed to stderr as
       "<path>: <CONTAINER>: undeclared C2PA manifest present (label=<label-or-unknown>)")
    2  invocation error (config.toml's extra.c2pa_declared_assets is present
       but not a list of strings)
"""

from __future__ import annotations

import argparse
import base64
import binascii
import fnmatch
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

PNG_SIGNATURE = bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))
JPEG_SOI = b"\xff\xd8"
_JPEG_NO_LENGTH_MARKERS = frozenset({0x01, *range(0xD0, 0xDA)})  # TEM, RSTn, SOI, EOI
_JPEG_SOS = 0xDA
_JPEG_APP11 = 0xEB
_JUMBF_APP11_CI = b"JP"  # ISO/IEC 19566-5 Annex B common identifier for a JUMBF box segment

CONTAINER_DISPLAY = {"png": "PNG", "jpeg": "JPEG", "svg": "SVG"}


def iter_jumbf_boxes(data: bytes):
    """Yield (box_type, payload) for each top-level ISO-base-media-style box in data.

    NOTE: JUMBF reuses the ISO/IEC 14496-12 box framing (4-byte length,
    4-byte type, with a 1-extended 8-byte length for boxes over 4GiB).
    Malformed input degrades to "yield nothing" rather than raising, since
    a channel already carrying bytes is the detection signal (see module
    docstring) — this walk only enriches with a label, never gates.
    """
    pos = 0
    end = len(data)
    while pos + 8 <= end:
        length = int.from_bytes(data[pos : pos + 4], "big")
        box_type = data[pos + 4 : pos + 8]
        header_len = 8
        if length == 1:
            if pos + 16 > end:
                return
            length = int.from_bytes(data[pos + 8 : pos + 16], "big")
            header_len = 16
        box_end = end if length == 0 else pos + length
        if box_end <= pos or box_end > end:
            return
        yield box_type, data[pos + header_len : box_end]
        pos = box_end


def parse_jumd_label(payload: bytes) -> str | None:
    """Extract the optional human-readable label from a JUMBF Description Box payload.

    Layout (ISO/IEC 19566-5 5.2): 16-byte UUID, 1-byte toggles, then an
    ASCII/UTF-8 NUL-terminated label if the label-present bit (0x02) is set.
    """
    if len(payload) < 17:
        return None
    toggles = payload[16]
    if not toggles & 0x02:
        return None
    body = payload[17:]
    terminator = body.find(b"\x00")
    if terminator == -1:
        return None
    return body[:terminator].decode("utf-8", errors="replace") or None


def extract_manifest_label(blob: bytes) -> str | None:
    """Best-effort label for the manifest store, falling back to its first nested manifest box."""
    for box_type, payload in iter_jumbf_boxes(blob):
        if box_type != b"jumb":
            continue
        children = list(iter_jumbf_boxes(payload))
        if not children or children[0][0] != b"jumd":
            continue
        label = parse_jumd_label(children[0][1])
        if label:
            return label
        for child_type, child_payload in children[1:]:
            if child_type != b"jumb":
                continue
            grandchildren = list(iter_jumbf_boxes(child_payload))
            if grandchildren and grandchildren[0][0] == b"jumd":
                inner_label = parse_jumd_label(grandchildren[0][1])
                if inner_label:
                    return inner_label
        return None
    return None


def extract_png_manifest(data: bytes) -> bytes | None:
    """Return the caBX chunk's raw payload, or None if no caBX chunk is present.

    caBX is the ancillary PNG chunk type the C2PA spec reserves for embedding
    a JUMBF manifest store — its presence is the channel-level signal, walked
    chunk-by-chunk rather than searched for as a byte pattern.
    """
    if not data.startswith(PNG_SIGNATURE):
        return None
    pos = len(PNG_SIGNATURE)
    end = len(data)
    while pos + 8 <= end:
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunk_type = data[pos + 4 : pos + 8]
        data_start = pos + 8
        data_end = data_start + length
        if data_end + 4 > end:
            return None  # truncated chunk
        if chunk_type == b"caBX":
            return data[data_start:data_end]
        pos = data_end + 4  # skip the trailing CRC
    return None


def extract_jpeg_manifest(data: bytes) -> bytes | None:
    """Reassemble a JUMBF blob from APP11 marker segments, in packet-sequence order.

    A manifest larger than one APP11 payload (64KiB max, per JPEG's 16-bit
    segment length) is split across multiple segments sharing a box-instance
    number (En) and ordered by packet-sequence number (Z) — this is the
    exact shape ci/asset-provenance.sh's header names as a grep-defeating
    false negative. Segments are grouped by En and concatenated by Z before
    anything downstream sees a single contiguous blob.
    """
    if not data.startswith(JPEG_SOI):
        return None
    pos = len(JPEG_SOI)
    end = len(data)
    packets: dict[int, dict[int, bytes]] = {}
    while pos + 2 <= end:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1  # fill byte before the real marker
            continue
        if marker in _JPEG_NO_LENGTH_MARKERS:
            pos += 2
            continue
        if marker == _JPEG_SOS:
            break  # entropy-coded scan data follows; APP11 only appears in the header
        if pos + 4 > end:
            break
        seg_len = int.from_bytes(data[pos + 2 : pos + 4], "big")
        if seg_len < 2:
            break  # malformed: length field must include itself
        seg_start = pos + 4
        seg_end = pos + 2 + seg_len
        if seg_end > end:
            break
        if marker == _JPEG_APP11:
            payload = data[seg_start:seg_end]
            if len(payload) >= 8 and payload[:2] == _JUMBF_APP11_CI:
                box_instance = int.from_bytes(payload[2:4], "big")
                sequence = int.from_bytes(payload[4:8], "big")
                packets.setdefault(box_instance, {})[sequence] = payload[8:]
        pos = seg_end
    for instance_packets in packets.values():
        blob = b"".join(instance_packets[z] for z in sorted(instance_packets))
        if blob:
            return blob
    return None


def extract_svg_manifest(data: bytes) -> bytes | None:
    """Base64-decode the text content of any element in a c2pa-* XML namespace.

    XML-parsed, so a `c2pa` substring inside a <!-- comment --> is never
    surfaced as an element — ElementTree's default parsing exposes only
    elements, attributes, and text, never comments.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    for elem in root.iter():
        tag = elem.tag
        if not isinstance(tag, str) or "}" not in tag:
            continue
        namespace = tag[1:].split("}", 1)[0]
        if "c2pa" not in namespace.lower():
            continue
        # WHY split()+join() rather than strip(): a pretty-printed manifest
        # element commonly wraps its base64 body across lines; only the
        # interior whitespace collapsing (not just the edges) keeps that
        # a valid decode instead of a spurious "empty" or malformed read.
        text = "".join((elem.text or "").split())
        if not text:
            continue
        try:
            blob = base64.b64decode(text, validate=False)
        except (binascii.Error, ValueError):
            continue
        if blob:
            return blob
    return None


_EXTRACTORS = {
    "png": extract_png_manifest,
    "jpeg": extract_jpeg_manifest,
    "svg": extract_svg_manifest,
}


def classify_container(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "png"
    if suffix in (".jpg", ".jpeg"):
        return "jpeg"
    if suffix == ".svg":
        return "svg"
    return None


def scan_file(path: Path) -> tuple[str, str | None] | None:
    """Return (container, label) if path carries an embedded manifest, else None."""
    container = classify_container(path)
    extractor = _EXTRACTORS.get(container) if container else None
    if extractor is None:
        return None
    blob = extractor(path.read_bytes())
    if blob is None:
        return None
    try:
        label = extract_manifest_label(blob)
    except Exception:
        # SAFETY: label extraction is enrichment, never the detection gate
        # (see module docstring INVARIANT) — a malformed inner box tree
        # must not suppress an already-established manifest finding.
        label = None
    return container, label


def load_declared_globs(config_path: Path) -> list[str]:
    """Read extra.c2pa_declared_assets from a consumer's config.toml.

    Absence of the file or the key means no declarations (empty list) —
    not every consumer opts into Content Credentials. A present-but-
    malformed value is a config authoring bug and fails closed rather
    than being silently ignored.
    """
    if not config_path.exists():
        return []
    with config_path.open("rb") as fh:
        config = tomllib.load(fh)
    declared = config.get("extra", {}).get("c2pa_declared_assets", [])
    if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
        raise ValueError(
            f"{config_path}: extra.c2pa_declared_assets must be a list of strings, got {declared!r}"
        )
    return declared


def is_declared(public_relative_path: str, globs: list[str]) -> bool:
    # WHY fnmatchcase, not fnmatch: fnmatch normalizes case per the host OS
    # (case-insensitive on Windows), which would make a declaration's match
    # set depend on which OS ran the gate. The gate must agree with itself
    # across GitHub Actions runners and a contributor's own machine.
    return any(fnmatch.fnmatchcase(public_relative_path, glob) for glob in globs)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)

    try:
        declared_globs = load_declared_globs(args.config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    public_root = args.public_root.resolve()
    violations = 0
    declared_hits = 0
    for file in args.files:
        found = scan_file(file)
        if found is None:
            continue
        container, label = found
        try:
            rel = "/" + file.resolve().relative_to(public_root).as_posix()
        except ValueError:
            rel = str(file)
        if is_declared(rel, declared_globs):
            declared_hits += 1
            continue
        violations += 1
        print(
            f"{file}: {CONTAINER_DISPLAY[container]}: undeclared C2PA manifest present "
            f"(label={label or 'unknown'})",
            file=sys.stderr,
        )

    if declared_hits:
        print(
            f"note: {declared_hits} declared C2PA manifest(s) allowed by extra.c2pa_declared_assets",
            file=sys.stderr,
        )

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
