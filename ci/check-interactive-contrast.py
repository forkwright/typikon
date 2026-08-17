#!/usr/bin/env python3
"""check-interactive-contrast — regression gate for WCAG 1.4.3 text contrast
across every rendered interactive state.

WHY: forkwright/typikon#64 found `.nav-links a:nth-child(3):hover` using a
dye color under the 4.5:1 AA floor for small text and fixed it with a
darker token (--aporia-interactive), but pa11y's static scan does not
exercise hover/focus/active states, so nothing verified the theme's other
~30 state-changing rules, and nothing would catch a future one regressing.
An op-pause completion audit reopened the issue on exactly that gap:
"the fix is real and the class is untouched."

This script is the class-level fix, and it resolves every color from the
CSS SOURCE rather than trusting a hand-typed token name — an earlier draft
of this file stored the expected token as a literal string per entry, and
mutation-testing it (reverting --aporia-interactive to the original,
failing --aporia at style.css:205) proved that draft kept reporting the
OLD passing ratio: the literal was never re-checked against the file, so
the exact regression #64 was reopened over would have sailed through it
uncaught. What follows instead:

1. RESOLVES each MATRIX entry's foreground/background by walking a short,
   explicit CHAIN of selectors — the state selector itself, then (only
   when it doesn't declare the property, including when it declares the
   literal keyword `inherit`) the selector CSS inheritance would actually
   defer to — using find_declared_var() to parse the real rule body each
   time. A chain terminates at a selector that verifiably declares the
   property as `var(--token)` in the CURRENT file; if the file stops
   declaring it anywhere in the chain, resolution raises and the check
   fails rather than silently reusing a stale value.

2. Applies the WCAG floor (4.5:1 normal text, 3:1 large-scale text per
   technique G18/G145: >=24px any weight, or >=18.66px at >=700 weight) to
   the resolved ratio.

3. SCANS static/css/style.css for every rule whose selector carries an
   interactive-state pseudo-class (:hover, :focus, :focus-visible,
   :active, :visited, :disabled) and whose body sets `color`,
   `background`/`background-color`, or `opacity`, and fails closed if any
   such selector is not accounted for in MATRIX, NOT_TEXT_CONTRAST, or the
   opacity special-case. This is what makes "a brand-new, unreviewed state
   rule" fail on coverage even before its ratio is computed.

Background tokens are the one piece NOT re-derived from a nearby CSS
declaration where no such declaration exists to derive from (the ordinary
case: `.nav-links a:hover` sets no `background` at all — the page's own
--bg is a DOM/layout fact, not a CSS property on that selector). Those
entries assert a literal token instead, exactly as
ci/check-control-contrast.py already does for --bg/--bg-accent, and this
file's own header comment records the closure check: every
`background: var(--bg-accent)` declaration in the theme was grepped
(style.css + templates/) and traced to its consumers — .purchase-box
(the #136 form control, not text), .product-images/.workshop-images (no
text), and .faq-item:target (the FAQ deep-link background; MATRIX
includes it explicitly below because .faq-anchor's own text sits inside
it). No other selector in MATRIX ever renders inside a --bg-accent
container.

Out of scope, with reasons, so nobody re-litigates them as omissions:

  - `:focus-visible`'s outline color (style.css:287) is a WCAG 1.4.11
    NON-TEXT UI-boundary color, not 1.4.3 text — ci/check-control-contrast.py's
    domain, not this one. It resolves to var(--text) against var(--bg) =
    15.77:1, so there is no live defect either way.
  - `.home-page:has(.mark-*:hover)` / `:has(.triad-mark.settled .triad-N:hover)`
    (static/css/skins/leather.css as of forkwright/typikon#55; originally
    in style.css itself) shift the home page's background through a
    decorative gradient. This is pre-adjudicated, not skipped out of
    convenience: ci/pa11y.config.js's own `ignore`-list comment states the
    underlying text stays "on archival-paper bg, contrast-AA-clean" by
    design and marks the class ratio-aware. This script does not
    re-litigate that documented call.
  - `:active`, `:visited`, `:disabled` currently have ZERO rules anywhere
    in style.css (confirmed by the scan in part 3 finding none) — so
    every element's active/visited/disabled state renders with the same
    color as its hover-or-default state, both of which MATRIX already
    verifies. `:visited` specifically could not be verified any other
    way: every major browser engine makes `getComputedStyle` on a
    `:visited` element report color/background/border/outline as if
    unvisited, to prevent history-sniffing, so a browser-driven assertion
    structurally cannot observe a real :visited color even if one
    existed. The scan re-runs this absence check on every invocation —
    the moment any of these three pseudo-classes gets a color rule, part
    3 requires it to be added here with a passing ratio.

ci/smoke/interactive-state-contrast.spec.ts is this script's browser-side
counterpart: it drives an actual Chromium instance through default,
hover, focus and active (visited is the browser-restricted exception
above) and reads real getComputedStyle output, which catches a cascade
bug (an unrelated, more-specific rule silently overriding what this
static script assumes) that parsing style.css in isolation cannot.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contrast import (  # noqa: E402
    blend_over,
    contrast_ratio,
    parse_root_tokens,
    text_contrast_floor,
)

THEME_ROOT = Path(__file__).resolve().parent.parent
STYLE_CSS = THEME_ROOT / "static" / "css" / "style.css"

# First-party skins this theme ships (forkwright/typikon#55): their :root
# token overrides are cascade-loaded AFTER style.css by a consumer that
# opts in (config.extra.consumer_css), so the SAME theme-owned selectors
# this script protects (.nav-links a:nth-child(3):hover, .triad-3, ...)
# render through whatever hue a skin maps its --accent-N tokens to.
# Scanning core alone would leave that mapping — including the exact
# color pair (--aporia / --aporia-interactive) #64 was filed over —
# unchecked the moment it moved out of style.css. This does NOT extend to
# arbitrary consumer-authored CSS: MATRIX is hand-curated over this
# theme's OWN selectors, so an unknown consumer skin with its own novel
# selectors is out of scope here exactly as it always was.
FIRST_PARTY_SKINS = [THEME_ROOT / "static" / "css" / "skins" / "leather.css"]


def load_theme_css() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in [STYLE_CSS, *FIRST_PARTY_SKINS])

RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
STATE_PSEUDO_RE = re.compile(r":(hover|focus-visible|focus|active|visited|disabled)\b")
COLOR_AFFECTING_RE = re.compile(
    r"(?:^|;)\s*(color|background(?:-color)?|opacity)\s*:", re.MULTILINE
)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

INHERIT_SENTINEL = "INHERIT"


def _prop_var_re(prop_alt: str) -> re.Pattern:
    # WHY the (?:^|;) anchor: mirrors COLOR_AFFECTING_RE's boundary above —
    # without it, prop_alt="color" matches the "color:" substring inside
    # "background-color:"/"border-color:"/"outline-color:"/etc. and
    # silently resolves the WRONG property's value with no error.
    return re.compile(
        rf"(?:^|;)\s*(?:{prop_alt})\s*:\s*[^;]*var\(--([\w-]+)\)[^;]*;",
        re.MULTILINE,
    )


def _prop_inherit_re(prop_alt: str) -> re.Pattern:
    # WHY the same anchor as _prop_var_re: unanchored, prop_alt="color"
    # would equally match the "color: inherit;" substring inside
    # "background-color: inherit;".
    return re.compile(
        rf"(?:^|;)\s*(?:{prop_alt})\s*:\s*(?:inherit|unset|currentColor)\s*;",
        re.MULTILINE,
    )


def find_declared_var(css_text: str, selector: str, prop_alt: str) -> str | None:
    """Return the var() token `prop_alt` (e.g. "color" or
    "background|background-color") resolves to on the EXACT selector, the
    sentinel INHERIT_SENTINEL if it's declared as the literal keyword
    inherit/unset/currentColor (meaning "look at the DOM parent instead"),
    or None if that selector's rule doesn't mention the property at all.
    Last declaration wins if the selector appears in more than one rule
    (source-order cascade, equal specificity)."""
    var_re = _prop_var_re(prop_alt)
    inherit_re = _prop_inherit_re(prop_alt)
    result: str | None = None
    for raw_selector, body in RULE_RE.findall(css_text):
        for part in raw_selector.split(","):
            if part.strip() != selector:
                continue
            m = var_re.search(body)
            if m:
                result = m.group(1)
                continue
            if inherit_re.search(body):
                result = INHERIT_SENTINEL
    return result


def resolve_chain(css_text: str, chain: list[str], prop_alt: str) -> tuple[str, str]:
    """Walk `chain` in order; return (token, selector-that-declared-it).
    Raises LookupError if nothing in the chain declares a var()-based
    value — that is a failure, not a silent fallback, because it means
    either the chain is wrong or the CSS stopped declaring the property
    the chain assumes it does."""
    for selector in chain:
        found = find_declared_var(css_text, selector, prop_alt)
        if found is not None and found != INHERIT_SENTINEL:
            return found, selector
    raise LookupError(
        f"no var()-based {prop_alt} declaration found walking chain {chain} "
        "(a selector said `inherit` with nothing further up the chain to "
        "resolve it against, or none of the chain matches any rule at all)"
    )


# --- Part 1: the hand-curated selector/state/font matrix -------------------
#
# Each entry: (selector, state, color_chain, bg, font_px, font_weight, note)
#
#   selector    — the CSS selector text as it appears in style.css (used to
#                 report the finding and, for synthetic non-selector labels
#                 like "(hover, unchanged)" rows, purely descriptive).
#   state       — one of "default", "hover", "focus". No entry carries
#                 "active"/"visited"/"disabled" — see the module docstring
#                 for why those three are verified by absence instead.
#   color_chain — ordered list of selectors to resolve `color` against;
#                 resolve_chain() walks it and fails if none resolves.
#   bg          — either ("literal", token_name) for a page/container
#                 context asserted rather than derived (documented in the
#                 module docstring's closure check), or ("chain", [...])
#                 to resolve `background`/`background-color` the same way
#                 color is resolved.
#   font_px/font_weight — the element's computed size/weight, used to pick
#                 the 4.5:1 vs 3:1 floor exactly as WCAG defines "large".
#   note        — why this entry exists / anything non-obvious about it.
MATRIX = [
    # --- primary nav ---
    (".nav-links a", "default", [".nav-links a"], ("literal", "bg"), 11.1, 400,
     "base rule sets color directly"),
    (".nav-links a:nth-child(1):hover", "hover", [".nav-links a:nth-child(1):hover"], ("literal", "bg"), 11.1, 400,
     "dye-color hover override"),
    (".nav-links a:nth-child(2):hover", "hover", [".nav-links a:nth-child(2):hover"], ("literal", "bg"), 11.1, 400,
     "dye-color hover override"),
    (".nav-links a:nth-child(3):hover", "hover", [".nav-links a:nth-child(3):hover"], ("literal", "bg"), 11.1, 400,
     "core resolves to --accent-3 (neutral by default); the leather skin's --accent-3 must stay "
     "mapped to --aporia-interactive, not raw --aporia — the original #64 fix, now one hop deeper"),
    (".nav-links a:nth-child(4):hover", "hover", [".nav-links a:nth-child(4):hover"], ("literal", "bg"), 11.1, 400,
     "dye-color hover override"),
    (".nav-links a:nth-child(5):hover", "hover", [".nav-links a:nth-child(5):hover"], ("literal", "bg"), 11.1, 400,
     "dye-color hover override"),
    (".nav-links a:nth-child(6):hover", "hover", [".nav-links a:nth-child(6):hover"], ("literal", "bg"), 11.1, 400,
     "dye-color hover override"),
    # WHY .nav-links a:hover::after (Greek-label reveal) has no entry of
    # its own: a pseudo-element with no `color` declaration inherits the
    # originating element's COMPUTED color, so during hover it renders in
    # whichever of the six rows above applied. Not a distinct pair.

    # --- home-page secondary nav ---
    # WHY .home-nav a:hover has no own color entry: no :hover rule touches
    # color at all, so the chain for "hover" correctly falls through to
    # the default rule below.
    (".home-nav a", "default", [".home-nav a"], ("literal", "bg"), 13.3, 400,
     "base rule sets color directly"),
    (".home-nav a:hover", "hover", [".home-nav a:hover", ".home-nav a"], ("literal", "bg"), 13.3, 400,
     "no .home-nav a:hover rule declares color; chain falls back to the base rule, "
     "which resolve_chain() proves rather than assumes"),

    # --- home logo reveal ---
    (".logo", "default", [".logo"], ("literal", "bg"), 11.1, 400,
     "base rule sets color directly"),
    (".logo:hover::after", "hover", [".logo:hover::after", ".logo::after", ".logo"], ("literal", "bg"), 11.1, 400,
     "neither ::after rule sets color; chain falls back to .logo"),

    # --- section-heading Greek reveal ---
    ("h2[data-greek]", "default", ["h2[data-greek]", "h2"], ("literal", "bg"), 13.3, 400,
     "h2[data-greek] itself sets no color; chain falls back to bare h2"),
    ("h2[data-greek]:hover::after", "hover",
     ["h2[data-greek]:hover::after", "h2[data-greek]::after", "h2[data-greek]", "h2"],
     ("literal", "bg"), 13.3, 400,
     "neither ::after rule nor h2[data-greek] sets color; chain falls back to bare h2"),

    # --- skip link (visible only while focused) ---
    (".sr-only:focus", "focus", [".sr-only:focus", "a"], ("literal", "bg"), 16.0, 400,
     "<a class=sr-only>; the focus rule sets background/border, not color; "
     "chain falls back to the global a{color:text} rule"),
    (".sr-only:focus-visible", "focus", [".sr-only:focus-visible", "a"], ("literal", "bg"), 16.0, 400,
     "grouped with .sr-only:focus in the same rule; identical resolution"),

    # --- products / journal index ---
    (".products-list a", "default", [".products-list a", "a"], ("literal", "bg"), 19.2, 400,
     "neither list rule sets color; chain falls back to the global a{color:text} rule "
     "(.product-materials/.product-price pin their own text-light via a more specific "
     "selector and are unaffected by either state)"),
    (".products-list a:hover", "hover", [".products-list a:hover"], ("literal", "bg"), 19.2, 400,
     "declares color directly; .product-name/.entry-name have no own color so they "
     "take this (the text-light metadata siblings keep their own more-specific color)"),
    (".journal-list a", "default", [".journal-list a", "a"], ("literal", "bg"), 19.2, 400,
     "grouped with .products-list a in the base rule; same resolution"),
    (".journal-list a:hover", "hover", [".journal-list a:hover"], ("literal", "bg"), 19.2, 400,
     "grouped with .products-list a:hover in the same hover rule; same resolution"),

    # --- buy button (bg/fg swap, not a plain color change) ---
    (".buy-btn", "default", [".buy-btn"], ("chain", [".buy-btn"]), 11.1, 400,
     "color:var(--bg) text on background:var(--text) — both declared directly"),
    (".buy-btn:hover", "hover", [".buy-btn:hover", ".buy-btn"], ("chain", [".buy-btn:hover"]), 11.1, 400,
     "hover declares no `color`; chain falls back to .buy-btn (still --bg). "
     "background is declared directly on the hover rule (--accent-1)"),

    # --- 404 back link ---
    (".back-link", "default", [".back-link"], ("literal", "bg"), 11.1, 400,
     "base rule sets color directly"),
    (".back-link:hover", "hover", [".back-link:hover"], ("literal", "bg"), 11.1, 400,
     "hover rule sets color directly"),

    # --- launch-notification pill (bg/fg swap on hover) ---
    (".notify-link", "default", [".notify-link"], ("literal", "bg"), 13.3, 400,
     "border-only default; background is the page bg behind it (no background "
     "declared on this rule to derive from)"),
    (".notify-link:hover", "hover", [".notify-link:hover"], ("chain", [".notify-link:hover"]), 13.3, 400,
     "both color and background declared directly on the hover rule (a full swap)"),

    # --- footer links ---
    (".footer-links a", "default", [".footer-links a"], ("literal", "bg"), 11.1, 400,
     "base rule sets color directly"),
    (".footer-links a:hover", "hover", [".footer-links a:hover"], ("literal", "bg"), 11.1, 400,
     "hover rule sets color directly"),

    # --- journal entry prev/next nav ---
    (".entry-nav a", "default", [".entry-nav a"], ("literal", "bg"), 13.3, 400,
     "base rule sets color directly"),
    (".entry-nav a:hover", "hover", [".entry-nav a:hover"], ("literal", "bg"), 13.3, 400,
     "hover rule sets color directly"),

    # --- FAQ deep-link anchor ---
    # WHY nested inside .faq-question (templates/faq.html:38-39): its
    # `color: inherit` genuinely means "look at .faq-question" — and if
    # .faq-item is the URL's :target, that ancestor's background becomes
    # --bg-accent (style.css:1340-1346), so both backgrounds are checked.
    (".faq-anchor", "default", [".faq-anchor", ".faq-question"], ("literal", "bg"), 23.04, 500,
     "color:inherit defers to the parent .faq-question, which sets color:var(--text) directly"),
    (".faq-anchor", "default (:target ancestor)", [".faq-anchor", ".faq-question"], ("literal", "bg-accent"), 23.04, 500,
     "same resolution as above; .faq-item:target swaps the ANCESTOR background to --bg-accent "
     "when this FAQ entry is the page's URL fragment"),
    (".faq-anchor:hover", "hover", [".faq-anchor:hover"], ("literal", "bg"), 23.04, 500,
     "hover rule sets color directly; border-bottom repeats the same token, not text, not re-checked"),
    (".faq-anchor:hover", "hover (:target ancestor)", [".faq-anchor:hover"], ("literal", "bg-accent"), 23.04, 500,
     "same hover color; checked against the :target ancestor's --bg-accent too"),

    # --- home triad mark ---
    # WHY hover resolves through the SAME chain as default: color is set
    # outside :hover and never overridden by it (only the nested
    # .english/.greek opacity toggles) — verified explicitly by re-walking
    # the chain below, not assumed unaffected.
    (".triad-1", "default", [".triad-1"], ("literal", "bg"), 23.04, 400,
     "resting color of the first triad word"),
    (".triad-1", "hover (unchanged)", [".triad-1"], ("literal", "bg"), 23.04, 400,
     ".triad-mark.settled .triad-word:hover only transforms scale + toggles child opacity; "
     "no more-specific selector exists, so the chain correctly resolves to the same rule"),
    (".triad-2", "default", [".triad-2"], ("literal", "bg"), 23.04, 400,
     "resting color of the second triad word"),
    (".triad-2", "hover (unchanged)", [".triad-2"], ("literal", "bg"), 23.04, 400,
     ".triad-mark.settled .triad-word:hover only transforms scale + toggles child opacity"),
    (".triad-3", "default", [".triad-3"], ("literal", "bg"), 23.04, 400,
     "resting color of the third triad word — already the corrected token"),
    (".triad-3", "hover (unchanged)", [".triad-3"], ("literal", "bg"), 23.04, 400,
     ".triad-mark.settled .triad-word:hover only transforms scale + toggles child opacity"),

    # --- alt-tagline reveal on the home page ---
    (".home .home-tagline[data-alt]:hover::after", "hover",
     [".home .home-tagline[data-alt]:hover::after", ".home .home-tagline[data-alt]::after"],
     ("literal", "bg"), 23.04, 300,
     "the opacity-only hover rule sets no color; chain falls back to the base "
     "::after rule, which sets color:var(--text) directly (style.css:854)"),
]

# WHY this dict exists, not just a coverage-scan skip: selectors here
# change something OTHER than a text color, a text-bearing background, or
# opacity (a transform, a decorative underline color, a non-text focus
# outline, or a pre-adjudicated decorative background-gradient tint).
# Listing each one with its reason keeps the coverage sweep VISIBLY
# complete rather than silently partial — an unlisted exclusion would be
# indistinguishable from one nobody checked.
NOT_TEXT_CONTRAST = {
    ".logo:hover span": "opacity toggle only, no color",
    ".nav-links a:hover::after": "opacity toggle of the Greek-label pseudo-element; it has no "
                                  "own color so it inherits whichever nth-child hover row applied "
                                  "(all six are in MATRIX)",
    ".nav-links a:hover span": "opacity toggle only, no color",
    "h2[data-greek]:hover span": "opacity toggle only, no color",
    ".home-nav a:hover::after": "opacity toggle of the Greek label; color already covered by "
                                 ".home-nav a:hover above (identical, unaffected by this rule)",
    ".home-nav a:hover span": "opacity toggle only, no color",
    ".mark:hover": "transform:scale only, no text",
    ".home-page:has(.mark-aima:hover)": "decorative bg gradient — pre-adjudicated, see module docstring",
    ".home-page:has(.mark-thanatochromia:hover)": "decorative bg gradient — pre-adjudicated, see module docstring",
    ".home-page:has(.mark-aporia:hover)": "decorative bg gradient — pre-adjudicated, see module docstring",
    "a:hover": "text-decoration-color only, not the glyph color, which is what 1.4.3 measures",
    ".home .home-tagline:hover span": "opacity toggle only, no color",
    ".triad-mark.settled .triad-word:hover .english": "opacity toggle only, no color",
    ".triad-mark.settled .triad-word:hover .greek": "opacity toggle only, no color",
    ".triad-mark.settled .triad-word:hover": "transform:scale only, no color",
    ".home-page:has(.triad-mark.settled .triad-1:hover)::before":
        "decorative overlay, position:fixed z-index:-1 — pre-adjudicated, see module docstring",
    ".home-page:has(.triad-mark.settled .triad-2:hover)::after":
        "decorative overlay, position:fixed z-index:-1 — pre-adjudicated, see module docstring",
    ".home-page:has(.triad-mark.settled .triad-3:hover) .triad-mark::after":
        "decorative overlay, position:fixed z-index:-1 — pre-adjudicated, see module docstring",
    ".home-page:has(.triad-mark.settled .triad-1:hover)": "decorative bg gradient — pre-adjudicated, see module docstring",
    ".home-page:has(.triad-mark.settled .triad-2:hover)": "decorative bg gradient — pre-adjudicated, see module docstring",
    ".home-page:has(.triad-mark.settled .triad-3:hover)": "decorative bg gradient — pre-adjudicated, see module docstring",
}

# --- the one opacity-driven state: composite, don't just resolve ----------
OPACITY_ENTRY = {
    "selector": ".buttondown-form button:hover",
    "fg_chain": [".buttondown-form button:hover", ".buttondown-form button"],
    "own_bg_chain": [".buttondown-form button:hover", ".buttondown-form button"],
    "backdrop_token": "bg",
    "alpha": 0.8,
    "font_px": 13.3,
    "font_weight": 400,
    "note": "opacity:0.8 dims the button's own background:var(--text) toward the page "
            "backdrop it sits on (--bg); the text color itself (--bg) is unaffected since "
            "it composites onto an identically-colored backdrop",
}


def find_state_affecting_selectors(css_text: str) -> dict[str, list[str]]:
    """Return {normalized selector: [matched state pseudo-classes]} for every
    rule with an interactive-state pseudo-class whose body sets color,
    background(-color), or opacity.

    WARNING: strip comments before matching. RULE_RE's selector group spans
    everything since the previous rule's `}`, so a comment sitting between
    two rules (there are dozens in this file, e.g. "/* Nav links get dye
    colors on hover */" directly above .nav-links a:nth-child(1):hover)
    would otherwise be captured as part of the NEXT selector's text and
    corrupt both the coverage match and the printed selector.
    """
    css_text = CSS_COMMENT_RE.sub(" ", css_text)
    found: dict[str, list[str]] = {}
    for raw_selector, body in RULE_RE.findall(css_text):
        if not COLOR_AFFECTING_RE.search(body):
            continue
        for part in raw_selector.split(","):
            selector = part.strip()
            states = STATE_PSEUDO_RE.findall(selector)
            if states:
                found[selector] = states
    return found


def main() -> int:
    css_text = load_theme_css()
    css_text_nocomments = CSS_COMMENT_RE.sub(" ", css_text)
    tokens = parse_root_tokens(css_text)

    for required in ("bg", "bg-accent"):
        if required not in tokens:
            print(f"FAIL: :root declares no --{required} token in {STYLE_CSS}", file=sys.stderr)
            return 1

    failures: list[str] = []
    checked: list[str] = []

    # --- Part 1: resolve every entry from source and check it ---
    for selector, state, color_chain, bg_spec, font_px, weight, note in MATRIX:
        try:
            fg_name, fg_via = resolve_chain(css_text_nocomments, color_chain, "color")
        except LookupError as exc:
            failures.append(f"{selector} [{state}]: {exc}")
            continue

        bg_kind, bg_arg = bg_spec
        if bg_kind == "literal":
            bg_name, bg_via = bg_arg, "(page/container context, asserted — see module docstring)"
        else:
            try:
                bg_name, bg_via = resolve_chain(css_text_nocomments, bg_arg, "background|background-color")
            except LookupError as exc:
                failures.append(f"{selector} [{state}]: {exc}")
                continue

        if fg_name not in tokens:
            failures.append(f"{selector} [{state}]: resolved fg --{fg_name} (via {fg_via}) has no :root declaration")
            continue
        if bg_name not in tokens:
            failures.append(f"{selector} [{state}]: resolved bg --{bg_name} (via {bg_via}) has no :root declaration")
            continue

        ratio = contrast_ratio(tokens[fg_name], tokens[bg_name])
        floor = text_contrast_floor(font_px, weight)
        checked.append(
            f"{selector} [{state}] --{fg_name} (via {fg_via}) vs --{bg_name} = {ratio:.2f}:1 "
            f"(floor {floor}:1 @ {font_px:g}px/{weight}) — {note}"
        )
        if ratio < floor:
            failures.append(
                f"{selector} [{state}]: --{fg_name} ({tokens[fg_name]}) vs --{bg_name} "
                f"({tokens[bg_name]}) is {ratio:.2f}:1, below the {floor}:1 WCAG 1.4.3 floor "
                f"for {font_px:g}px/{weight} text"
            )

    # --- the opacity-composited case ---
    e = OPACITY_ENTRY
    try:
        fg_name, fg_via = resolve_chain(css_text_nocomments, e["fg_chain"], "color")
        own_bg_name, own_bg_via = resolve_chain(css_text_nocomments, e["own_bg_chain"], "background|background-color")
    except LookupError as exc:
        failures.append(f"{e['selector']}: {exc}")
    else:
        if fg_name not in tokens or own_bg_name not in tokens or e["backdrop_token"] not in tokens:
            failures.append(f"{e['selector']}: a resolved token has no :root declaration")
        else:
            composited_bg = blend_over(tokens[own_bg_name], tokens[e["backdrop_token"]], e["alpha"])
            ratio = contrast_ratio(tokens[fg_name], composited_bg)
            floor = text_contrast_floor(e["font_px"], e["font_weight"])
            checked.append(
                f"{e['selector']} [hover, opacity={e['alpha']}] --{fg_name} (via {fg_via}) vs "
                f"composited {composited_bg} (--{own_bg_name} via {own_bg_via} over --{e['backdrop_token']}) "
                f"= {ratio:.2f}:1 (floor {floor}:1) — {e['note']}"
            )
            if ratio < floor:
                failures.append(
                    f"{e['selector']}: composited background {composited_bg} against "
                    f"--{fg_name} is {ratio:.2f}:1, below the {floor}:1 floor"
                )

    # --- Part 2: coverage scan (both directions) ---
    found = find_state_affecting_selectors(css_text)
    matrix_selectors = {sel for sel, *_ in MATRIX}
    documented_not_text = set(NOT_TEXT_CONTRAST)
    documented_opacity = {OPACITY_ENTRY["selector"]}

    for selector in found:
        if selector in documented_not_text or selector in documented_opacity or selector in matrix_selectors:
            continue
        failures.append(
            f"{selector}: sets color/background/opacity under an interactive-state "
            "pseudo-class but is not in MATRIX, NOT_TEXT_CONTRAST, or the opacity "
            "special-case — add it to ci/check-interactive-contrast.py before merging"
        )

    for pseudo in ("active", "visited", "disabled"):
        live = [sel for sel, states in found.items() if pseudo in states]
        if live:
            failures.append(
                f":{pseudo} now has {len(live)} color/background/opacity rule(s) "
                f"({', '.join(live)}) that MATRIX does not cover — this script's absence "
                f"claim for :{pseudo} (see module docstring) is now false; add explicit "
                "entries and, for :visited, verify manually since browser assertions are "
                "blocked by every engine's history-sniffing protection"
            )

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    for line in checked:
        print(f"OK: {line}")
    print(
        f"OK: {len(checked)} interactive-state text-contrast declaration(s), each resolved "
        "from the live CSS source, clear their WCAG 1.4.3 floor; :active/:visited/:disabled "
        "confirmed to carry zero color rules (verified-by-absence, re-checked every run)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
