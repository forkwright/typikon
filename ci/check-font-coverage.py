#!/usr/bin/env python3
"""check-font-coverage — CSS unicode-range must be derived from the bytes.

WHY: a declared unicode-range is a claim about the shipped font, not a fact
about it — an upstream font master can omit codepoints inside a range a
CSS unicode-range asserts as covered (e.g. Greek letters present only as
math/science symbols), and when that happens matching text silently falls
back to the visitor's system font while the CSS still asserts self-hosted
coverage (forkwright/typikon#35). This script treats the shipped WOFF2
cmap as the single source of truth and fails if a declared unicode-range
codepoint is not actually present in the font it is declared on. Control
characters (Unicode category Cc) are excluded: no font maps a glyph to
them and no browser ever requests one, so their absence from cmap is not
a coverage gap.

Also reports (non-fatal) which code points used across templates/ and
examples/ fall outside every declared @font-face's actual coverage, so a
future subset/typeface change has a concrete, reproducible target list
instead of a vague "add Greek" note.
"""

import re
import sys
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTFont

THEME_ROOT = Path(__file__).resolve().parent.parent
FONTS_CSS = THEME_ROOT / "static" / "css" / "fonts.css"

FONT_FACE_RE = re.compile(r"@font-face\s*{([^}]*)}", re.DOTALL)
SRC_URL_RE = re.compile(r"url\('([^']+\.woff2)'\)")
UNICODE_RANGE_RE = re.compile(r"unicode-range:\s*([^;]+);")
TOKEN_RE = re.compile(r"U\+([0-9A-Fa-f]{1,6})(?:-([0-9A-Fa-f]{1,6}))?")


def parse_unicode_range(value: str) -> set[int]:
    codepoints: set[int] = set()
    for lo_hex, hi_hex in TOKEN_RE.findall(value):
        lo = int(lo_hex, 16)
        hi = int(hi_hex, 16) if hi_hex else lo
        codepoints.update(range(lo, hi + 1))
    return codepoints


def font_cmap_codepoints(path: Path) -> set[int]:
    font = TTFont(str(path))
    return set(font.getBestCmap().keys())


def scan_font_faces(css_text: str) -> list[dict]:
    faces = []
    for block in FONT_FACE_RE.findall(css_text):
        urls = SRC_URL_RE.findall(block)
        range_match = UNICODE_RANGE_RE.search(block)
        if not urls or not range_match:
            continue
        # NOTE: a variable-font @font-face lists the same file twice (once
        # per format() token) -- dedupe so each shipped file is opened once.
        files = list(dict.fromkeys(THEME_ROOT / "static" / u.removeprefix("/") for u in urls))
        faces.append(
            {
                "files": files,
                "declared": parse_unicode_range(range_match.group(1)),
            }
        )
    return faces


def scan_fixture_codepoints() -> set[int]:
    codepoints: set[int] = set()
    for path in THEME_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if "themes" in path.parts:  # NOTE: self-referential example symlinks (examples/*/themes/typikon -> repo root)
            continue
        if ".git" in path.parts:
            continue
        if path.suffix not in (".md", ".toml", ".html"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for ch in text:
            cp = ord(ch)
            if 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
                codepoints.add(cp)
    return codepoints


def main() -> int:
    css_text = FONTS_CSS.read_text(encoding="utf-8")
    faces = scan_font_faces(css_text)
    if not faces:
        print(f"FAIL: no @font-face blocks with src + unicode-range found in {FONTS_CSS}", file=sys.stderr)
        return 1

    failures = []
    all_covered: set[int] = set()
    for face in faces:
        actual: set[int] = set()
        for f in face["files"]:
            if not f.exists():
                failures.append(f"{f.relative_to(THEME_ROOT)}: declared in fonts.css but file does not exist")
                continue
            actual |= font_cmap_codepoints(f)
        all_covered |= actual

        for cp in sorted(face["declared"]):
            if unicodedata.category(chr(cp)) == "Cc":
                continue  # WHY: control chars have no glyph in any font and are never rendered
            if cp not in actual:
                names = ", ".join(f.name for f in face["files"])
                failures.append(f"{names}: unicode-range declares U+{cp:04X} but shipped cmap does not contain it")

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    fixture_cps = scan_fixture_codepoints()
    uncovered = sorted(fixture_cps - all_covered)
    if uncovered:
        points = ", ".join(f"U+{cp:04X} ({chr(cp)})" for cp in uncovered)
        print(
            "NOTE: fixture/doc content uses Greek/Greek-Extended code points with no "
            f"declared @font-face coverage (falls back to system fonts): {points}",
            file=sys.stderr,
        )

    print(f"OK: {len(faces)} font-face declarations match shipped cmap coverage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
