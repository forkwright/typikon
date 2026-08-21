#!/usr/bin/env python3
"""check-og-image-format — regression test for the og:image format constraint.

WHY: `og_image` is the one field whose value is consumed entirely by software
this repository never runs — Facebook's, LinkedIn's, Slack's, X's link
scrapers. Those do not render an SVG og:image, so a consumer that configures
one ships a link card with **no image at all**, and every gate here stays green
because the file exists, the path resolves, and the pattern admitted it.

That is the failure shape this substrate keeps producing and then fixing: a
contract permitting a construct that cannot do the job, so the consumer
inherits a silent failure from the thing meant to prevent it. The same week,
`_redirects.tmpl` recommended a host-source rule Cloudflare accepts and ignores
(forkwright/typikon#191).

The check runs over EVERY schema declaring og_image rather than one, because
the pattern was copy-pasted into five files. A sixth schema written by copying
a fifth is exactly how this comes back, and a single-file assertion would not
see it.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = THEME_ROOT / "schemas"

# (value, must_validate)
CASES: list[tuple[str, bool]] = [
    ("img/og-cover.png", True),
    ("img/og-card.jpg", True),
    ("img/og-card.jpeg", True),
    ("img/social/og.webp", True),
    # The defect: accepted before, renders nowhere.
    ("img/og-cover.svg", False),
    ("img/og.SVG", False),
    # Adjacent shapes that must stay refused.
    ("https://example.test/og.png", False),
    ("img/og-cover", False),
    ("img/og cover.png", False),
]


def og_image_patterns() -> dict[str, str]:
    """Every og_image pattern in the registry, keyed by the file declaring it."""
    found: dict[str, str] = {}
    for path in sorted(SCHEMAS.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path.name} is not parseable JSON: {exc}") from exc

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "og_image" and isinstance(value, dict) and "pattern" in value:
                        found[path.name] = value["pattern"]
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(document)
    return found


def main() -> int:
    patterns = og_image_patterns()
    if not patterns:
        print("check-og-image-format: no og_image pattern found in schemas/", file=sys.stderr)
        return 1

    failures: list[str] = []
    for name, pattern in sorted(patterns.items()):
        compiled = re.compile(pattern)
        for value, must_validate in CASES:
            # JSON Schema `pattern` is an unanchored search, and both shipped
            # patterns anchor themselves with ^...$; re.search honours that
            # rather than assuming fullmatch semantics the schema does not have.
            accepted = compiled.search(value) is not None
            if accepted != must_validate:
                want = "accept" if must_validate else "refuse"
                failures.append(f"{name}: expected to {want} {value!r}, it did not")

    # One definition would be better than five identical ones; until then, prove
    # they have not diverged. A schema tightened in one file and not the others
    # is a constraint a consumer can route around by picking a different template.
    distinct = set(patterns.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{name}={pattern!r}" for name, pattern in sorted(patterns.items()))
        failures.append(f"og_image patterns have diverged across schemas: {detail}")

    if failures:
        print("check-og-image-format: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(
        f"check-og-image-format: ok ({len(patterns)} schema(s) agree, "
        f"{len(CASES)} cases each, SVG refused)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
