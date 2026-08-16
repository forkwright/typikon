#!/usr/bin/env python3
"""check-control-contrast — regression test for WCAG 1.4.11 non-text contrast.

WHY: a form control's border is its only perceivable boundary when it has
no fill difference from its background. forkwright/typikon#136 found two
such controls (.purchase-box select, .buttondown-form input[type="email"])
styled with var(--rule) — a token meant for decorative dividers, which
only reaches 1.35:1 / 1.26:1 against --bg / --bg-accent, far under the
3:1 WCAG 1.4.11 floor for UI component boundaries. --control-border is
the dedicated, contrast-checked token for this role; --rule stays
reserved for decoration and is never contrast-checked against 3:1.

This script parses static/css/style.css directly (no browser, no built
site) so it stays exact: it resolves every `--token: #hex` declaration in
:root, then scans every rule block for a form-control selector (input,
select, textarea, button) with a `border` declaration that resolves
through a var() to one of those hex values, and fails if that resolved
color does not clear 3:1 against both --bg and --bg-accent. This is
generic over the token name and the selector, not a hardcoded pass for
the two sites the issue named — a future control styled with the wrong
token fails the same way.

The luminance/contrast math and the :root parser live in ci/contrast.py,
shared with ci/check-interactive-contrast.py (forkwright/typikon#64) so
both checks measure against the identical formula.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contrast import NON_TEXT_CONTRAST_FLOOR, contrast_ratio, parse_root_tokens  # noqa: E402

THEME_ROOT = Path(__file__).resolve().parent.parent
STYLE_CSS = THEME_ROOT / "static" / "css" / "style.css"

RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
BORDER_VAR_RE = re.compile(r"border(?:-\w+)?\s*:\s*[^;]*var\(--([\w-]+)\)[^;]*;")
FORM_CONTROL_SELECTOR_RE = re.compile(r"\b(input|select|textarea|button)\b")
BG_TOKENS = ("bg", "bg-accent")


def find_form_control_border_vars(css_text: str) -> list[tuple[str, str]]:
    """Return (selector, var-name) for every form-control rule with a border var()."""
    found = []
    for selector, body in RULE_RE.findall(css_text):
        selector = selector.strip()
        if not FORM_CONTROL_SELECTOR_RE.search(selector):
            continue
        for var_name in BORDER_VAR_RE.findall(body):
            found.append((selector, var_name))
    return found


def main() -> int:
    css_text = STYLE_CSS.read_text(encoding="utf-8")
    tokens = parse_root_tokens(css_text)

    for required in ("bg", "bg-accent"):
        if required not in tokens:
            print(f"FAIL: :root declares no --{required} token in {STYLE_CSS}", file=sys.stderr)
            return 1

    control_vars = find_form_control_border_vars(css_text)
    if not control_vars:
        print(f"FAIL: found no form-control border declarations to check in {STYLE_CSS}", file=sys.stderr)
        return 1

    failures = []
    checked = []
    for selector, var_name in control_vars:
        if var_name not in tokens:
            failures.append(f"{selector}: border var(--{var_name}) has no :root declaration to resolve")
            continue
        border_hex = tokens[var_name]
        for bg_name in BG_TOKENS:
            ratio = contrast_ratio(border_hex, tokens[bg_name])
            checked.append(f"{selector} border --{var_name} vs --{bg_name} = {ratio:.2f}:1")
            if ratio < NON_TEXT_CONTRAST_FLOOR:
                failures.append(
                    f"{selector}: border var(--{var_name}) ({border_hex}) is {ratio:.2f}:1 against "
                    f"--{bg_name} ({tokens[bg_name]}), below the {NON_TEXT_CONTRAST_FLOOR}:1 WCAG "
                    "1.4.11 non-text contrast floor"
                )

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    for line in checked:
        print(f"OK: {line}")
    print(f"OK: {len(control_vars)} form-control border declaration(s) clear {NON_TEXT_CONTRAST_FLOOR}:1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
