#!/usr/bin/env python3
"""check-asset-provenance — regression test for ci/asset-provenance.sh.

Constructs synthetic PNG, JPEG, and SVG fixtures byte-for-byte in Python
(no external encoder) and runs the real stage script against them, proving
end to end (not just the inner scanner module) that:

- a manifest embedded via each container's real C2PA channel fails the
  gate and the failure names the path, the container, and the label;
- an asset with no manifest passes;
- an asset whose manifest the consumer declared in config.toml passes;
- a JPEG manifest split across two APP11 segments is reassembled and
  still detected (forkwright/typikon#137's named JPEG case).

The PNG and JPEG manifest fixtures' labels are deliberately chosen to
contain no "c2pa" substring anywhere in their bytes, so a would-be
`grep -r c2pa` on those exact fixtures would find NOTHING — proof the
container parse catches what a literal byte search misses, per this
issue's own evidence (SVG is exempt: its real embedding channel is an
`xmlns:c2pa=...` declaration, so a grep on a genuine SVG manifest WOULD
match; SVG's false-positive case — "c2pa" appearing only inside an XML
comment, never a real manifest — is what clean.svg proves instead).

NOTE: runs standalone (no consumer site or zola build needed) as part of
ci/run-fixtures.sh.
"""

from __future__ import annotations

import base64
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
STAGE = THEME_ROOT / "ci" / "asset-provenance.sh"

LABEL_PNG = "acme-imaging-suite:png-manifest"
LABEL_PNG_LYING_LENGTH = "acme-imaging-suite:png-lying-length"
LABEL_JPEG_SINGLE = "acme-imaging-suite:jpeg-single-segment"
LABEL_JPEG_SPLIT = "acme-imaging-suite:jpeg-split-segment"
LABEL_SVG = "acme-imaging-suite:svg-manifest"
LABEL_DECLARED = "acme-imaging-suite:declared"

# INVARIANT: none of these labels contain "c2pa" — see module docstring.
for _label in (LABEL_PNG, LABEL_PNG_LYING_LENGTH, LABEL_JPEG_SINGLE, LABEL_JPEG_SPLIT, LABEL_SVG, LABEL_DECLARED):
    assert "c2pa" not in _label


# --- JUMBF construction (mirrors ci/asset-provenance-scan.py's reader) -----


def jumbf_box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def jumd_payload(label: str) -> bytes:
    uuid_placeholder = bytes(range(16))  # detection is channel-gated, not UUID-gated
    toggles = 0x02  # label-present
    return uuid_placeholder + bytes((toggles,)) + label.encode("utf-8") + b"\x00"


def manifest_store(label: str) -> bytes:
    return jumbf_box(b"jumb", jumbf_box(b"jumd", jumd_payload(label)))


# --- PNG ---------------------------------------------------------------


PNG_SIGNATURE = bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    # NOTE: CRC correctness is irrelevant to the scanner (it never verifies
    # it), but computing it for real keeps the fixture a valid PNG for any
    # other tool that might inspect it.
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", zlib.crc32(chunk_type + data))


def build_png(manifest_label: str | None) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1 RGBA
    chunks = [png_chunk(b"IHDR", ihdr)]
    if manifest_label is not None:
        chunks.append(png_chunk(b"caBX", manifest_store(manifest_label)))
    chunks.append(png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")))
    chunks.append(png_chunk(b"IEND", b""))
    return PNG_SIGNATURE + b"".join(chunks)


def build_png_with_lying_chunk(manifest_label: str) -> bytes:
    """A caBX manifest preceded by a private chunk whose declared length overflows past EOF.

    Regression fixture for the chunk-length-overflow bypass: a corrupt
    chunk's untrustworthy length must not end the scan before a genuine
    caBX chunk that follows it (forkwright/typikon#137 gate defect).
    """
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)  # 1x1 RGBA
    # WHY no payload/CRC on this chunk: the declared length (0xFFFFFFF0)
    # overflows the file's actual remaining bytes by construction, and the
    # genuine caBX header begins immediately after this chunk's 8-byte
    # frame -- exactly the shape a naive walker that trusts the declared
    # length to skip to the next chunk cannot reach.
    lying_chunk = struct.pack(">I", 0xFFFFFFF0) + b"zzZz"
    chunks = [
        png_chunk(b"IHDR", ihdr),
        lying_chunk,
        png_chunk(b"caBX", manifest_store(manifest_label)),
        png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")),
        png_chunk(b"IEND", b""),
    ]
    return PNG_SIGNATURE + b"".join(chunks)


# --- JPEG ----------------------------------------------------------------


def app11_segment(box_instance: int, sequence: int, chunk: bytes) -> bytes:
    payload = b"JP" + struct.pack(">H", box_instance) + struct.pack(">I", sequence) + chunk
    return b"\xff\xeb" + struct.pack(">H", len(payload) + 2) + payload


def build_jpeg(app11_segments: bytes) -> bytes:
    return b"\xff\xd8" + app11_segments + b"\xff\xd9"


def jpeg_single_segment(label: str) -> bytes:
    return build_jpeg(app11_segment(1, 1, manifest_store(label)))


def jpeg_split_segments(label: str) -> bytes:
    blob = manifest_store(label)
    midpoint = len(blob) // 2
    segments = app11_segment(1, 1, blob[:midpoint]) + app11_segment(1, 2, blob[midpoint:])
    return build_jpeg(segments)


# --- SVG -------------------------------------------------------------------


def build_svg_manifest(label: str) -> bytes:
    encoded = base64.b64encode(manifest_store(label)).decode("ascii")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:c2pa="http://c2pa.org/manifest" '
        'width="1" height="1"><metadata><c2pa:manifest>'
        f"{encoded}"
        "</c2pa:manifest></metadata></svg>"
    ).encode()


def build_svg_clean_with_comment() -> bytes:
    # WHY: proves the parse does not flag "c2pa" appearing only in a
    # comment (issue #137's cited false-positive case) — an XML parser
    # never surfaces comment text as an element or attribute.
    return (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
        b"<!-- rendered by a tool whose name happens to contain c2pa -->"
        b"</svg>"
    )


# --- Test driver -----------------------------------------------------------


def run_stage(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(STAGE), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="typikon-asset-provenance-fixture-") as tmp:
        root = Path(tmp)
        img = root / "public" / "img"
        img.mkdir(parents=True)

        fixtures = {
            "clean.png": build_png(None),
            "manifest.png": build_png(LABEL_PNG),
            "manifest-lying-chunk.png": build_png_with_lying_chunk(LABEL_PNG_LYING_LENGTH),
            "clean.jpg": build_jpeg(b""),
            "manifest-single.jpg": jpeg_single_segment(LABEL_JPEG_SINGLE),
            "manifest-split.jpg": jpeg_split_segments(LABEL_JPEG_SPLIT),
            "clean.svg": build_svg_clean_with_comment(),
            "manifest.svg": build_svg_manifest(LABEL_SVG),
            "declared.jpg": jpeg_single_segment(LABEL_DECLARED),
        }
        for name, data in fixtures.items():
            (img / name).write_bytes(data)

        # INVARIANT check on the fixtures themselves, not the scanner: proves
        # the false-negative case is real (a literal grep would find nothing).
        # SVG is exempt — its C2PA embedding channel IS an xmlns declaration
        # containing "c2pa" (that's what the parse keys on), so a grep would
        # already find a real SVG manifest; SVG's false-positive case (a
        # mention inside a comment, not a real manifest) is checked below.
        for undetectable in ("manifest.png", "manifest-lying-chunk.png", "manifest-single.jpg", "manifest-split.jpg"):
            if b"c2pa" in fixtures[undetectable]:
                failures.append(f"fixture bug: {undetectable} contains literal 'c2pa' — invalidates the false-negative proof")
        if b"c2pa" not in fixtures["clean.svg"]:
            failures.append("fixture bug: clean.svg does not contain literal 'c2pa' — invalidates the false-positive proof")

        (root / "config.toml").write_text(
            '[extra]\nc2pa_declared_assets = ["/img/declared.jpg"]\n',
            encoding="utf-8",
        )

        result = run_stage(root)

        if result.returncode != 1:
            failures.append(f"mixed fixture set: expected exit 1 (undeclared manifests present), got {result.returncode}\nstderr:\n{result.stderr}")

        violation_lines = [line for line in result.stderr.splitlines() if "undeclared C2PA manifest present" in line]

        expected_violations = {
            "manifest.png": f"PNG: undeclared C2PA manifest present (label={LABEL_PNG})",
            "manifest-lying-chunk.png": f"PNG: undeclared C2PA manifest present (label={LABEL_PNG_LYING_LENGTH})",
            "manifest-single.jpg": f"JPEG: undeclared C2PA manifest present (label={LABEL_JPEG_SINGLE})",
            "manifest-split.jpg": f"JPEG: undeclared C2PA manifest present (label={LABEL_JPEG_SPLIT})",
            "manifest.svg": f"SVG: undeclared C2PA manifest present (label={LABEL_SVG})",
        }
        for name, expected in expected_violations.items():
            if not any(name in line and expected in line for line in violation_lines):
                failures.append(f"{name}: expected a violation line naming path + {expected!r}; violation lines were:\n" + "\n".join(violation_lines))

        # Exactly the four manifest fixtures above should have triggered a
        # violation — this catches both an under-report (a manifest fixture
        # missing from violation_lines, already caught above) and an
        # over-report (a clean or declared fixture wrongly flagged).
        if len(violation_lines) != len(expected_violations):
            failures.append(f"expected exactly {len(expected_violations)} violation line(s), got {len(violation_lines)}:\n" + "\n".join(violation_lines))

        if not any("note:" in line and "declared C2PA manifest" in line for line in result.stderr.splitlines()):
            failures.append(f"expected a declared-manifest note for declared.jpg; not found in stderr:\n{result.stderr}")

    # Second run: only clean + declared assets present — proves a fully
    # clean site (nothing to complain about) exits 0, not merely "exit 1
    # with fewer lines".
    with tempfile.TemporaryDirectory(prefix="typikon-asset-provenance-clean-") as tmp:
        root = Path(tmp)
        img = root / "public" / "img"
        img.mkdir(parents=True)
        (img / "clean.png").write_bytes(build_png(None))
        (img / "clean.jpg").write_bytes(build_jpeg(b""))
        (img / "clean.svg").write_bytes(build_svg_clean_with_comment())
        (img / "declared.jpg").write_bytes(jpeg_single_segment(LABEL_DECLARED))
        (root / "config.toml").write_text(
            '[extra]\nc2pa_declared_assets = ["/img/declared.jpg"]\n',
            encoding="utf-8",
        )

        result = run_stage(root)
        if result.returncode != 0:
            failures.append(f"all-clean fixture set: expected exit 0, got {result.returncode}\nstderr:\n{result.stderr}")

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print("OK: asset-provenance stage verified across PNG/JPEG/SVG, single- and multi-segment JPEG, and declared-asset exemption")
    return 0


if __name__ == "__main__":
    if shutil.which("bash") is None:
        print("FAIL: bash not on PATH (required to run ci/asset-provenance.sh)", file=sys.stderr)
        sys.exit(1)
    sys.exit(main())
