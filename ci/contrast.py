"""contrast — shared WCAG 2.x contrast-ratio math for typikon's CI checks.

NOTE: an importable module, not a standalone script (its name is
hyphen-free specifically so `from contrast import ...` works) — no
shebang, no executable bit, unlike its ci/check-*.py callers.

WHY a shared module: static/css/style.css's :root token block is the single
source of every color this theme uses, and every gate stage that measures a
token's contrast (form-control non-text contrast, interactive text contrast)
needs the identical relative-luminance formula and the identical :root
parser. Duplicating that math per script risks the two silently drifting to
different rounding or a transcription slip in one copy; importing from here
keeps it one fact in one place (forkwright/typikon#136, #64).
"""

import re

# WCAG 2.2 AA 1.4.3 (text): normal-size text needs 4.5:1; large-scale text
# needs only 3:1. WCAG 2.2 AA 1.4.11 (non-text): UI component boundaries
# (borders, focus indicators) need 3:1 regardless of size.
TEXT_CONTRAST_FLOOR_NORMAL = 4.5
TEXT_CONTRAST_FLOOR_LARGE = 3.0
NON_TEXT_CONTRAST_FLOOR = 3.0

# WCAG technique G18/G145 "large scale" definition: >=18pt (24px) at any
# weight, or >=14pt (18.66px) at bold (>=700) weight.
LARGE_TEXT_PX_REGULAR = 24.0
LARGE_TEXT_PX_BOLD = 18.66
BOLD_WEIGHT_THRESHOLD = 700

TOKEN_DECL_RE = re.compile(r"--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;")


def srgb_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    rl, gl, bl = srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def blend_over(fg_hex: str, backdrop_hex: str, alpha: float) -> str:
    """Composite fg_hex at `alpha` opacity over an opaque backdrop.

    WHY: CSS `opacity` on an element dims its own painted colors toward
    whatever sits behind it at render time. Both a static parse of the
    declared token and a browser's getComputedStyle report the
    pre-composite color unchanged, so a token that looks AA-clean in the
    stylesheet can still fail once opacity is applied — this computes the
    actual composited color so that case can be checked too. See
    .buttondown-form button:hover (forkwright/typikon#64), the one state
    rule in this theme that varies contrast via opacity rather than a
    color/background token swap.
    """
    fg = fg_hex.lstrip("#")
    bg = backdrop_hex.lstrip("#")
    fr, fg_g, fb = (int(fg[i : i + 2], 16) for i in (0, 2, 4))
    br, bg_g, bb = (int(bg[i : i + 2], 16) for i in (0, 2, 4))
    r = round(fr * alpha + br * (1 - alpha))
    g = round(fg_g * alpha + bg_g * (1 - alpha))
    b = round(fb * alpha + bb * (1 - alpha))
    return f"#{r:02X}{g:02X}{b:02X}"


def parse_root_tokens(css_text: str) -> dict[str, str]:
    root_match = re.search(r":root\s*\{([^{}]*)\}", css_text, re.DOTALL)
    if not root_match:
        return {}
    return dict(TOKEN_DECL_RE.findall(root_match.group(1)))


def text_contrast_floor(font_px: float, font_weight: int) -> float:
    is_large = font_px >= LARGE_TEXT_PX_REGULAR or (
        font_px >= LARGE_TEXT_PX_BOLD and font_weight >= BOLD_WEIGHT_THRESHOLD
    )
    return TEXT_CONTRAST_FLOOR_LARGE if is_large else TEXT_CONTRAST_FLOOR_NORMAL
