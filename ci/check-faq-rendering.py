#!/usr/bin/env python3
"""check-faq-rendering — regression test for faq.html anchor uniqueness and
JSON-LD script-breakout escaping (forkwright/typikon#92).

Reads the already-built examples/sample-shop/public/faq/index.html (built
by the bin/typikon-check invocation earlier in ci/run-fixtures.sh) and
proves two properties the fixture's own content is shaped to exercise:

- Two questions that auto-slugify to the same base anchor
  ("Do you ship worldwide?" / "Do you ship worldwide?!") must still
  produce two distinct element ids, not a silently duplicated one. The
  disambiguated id's exact suffix is an implementation detail (the
  colliding item's absolute position in the questions array, not a
  per-collision counter), so this asserts structurally — base id present,
  at least one sibling id sharing its "<base>-" prefix — rather than a
  literal string, so it keeps checking something real if the fixture
  gains or loses an earlier question.
- A question/answer pair containing a literal `</script>` must render as
  inert text everywhere, including inside the FAQPage JSON-LD
  <script type="application/ld+json"> block — an unescaped `</script>`
  there would terminate the element early and let the following bytes
  execute as markup/script in a visitor's browser.

Usage:
    ci/check-faq-rendering.py <built-sample-shop-public-dir>

NOTE: unlike the standalone checks in this directory, this one needs a
real Tera render (get_url(), typikon.assert.required, and Tera's component
scoping rules are all in play) — there is no meaningful way to simulate
that without invoking zola, so it runs against already-built output
rather than constructing its own fixture in-process.

NOTE on detecting the script-breakout directly: the block-extraction
regex below (`<script type="application/ld+json">(.*?)</script>`, DOTALL,
non-greedy) is itself blind to a genuine breakout — an unescaped
`</script>` inside a field value is, by construction, indistinguishable
from the block's real closing tag, so it always gets consumed as the
terminator and never appears *inside* an extracted body string. A
substring check for "</script>" inside an extracted body can therefore
never fire on the exact input it exists to catch. Detection instead goes
through json.loads() on each extracted body: a genuine breakout truncates
the body mid-string (at the injected "</script>", not the real one),
which is syntactically invalid JSON, while the escaped "\\/script" form
round-trips through JSON cleanly. This also serves as a general JSON-LD
well-formedness check, and the block-count assertion guards against a
breakout silently merging/splitting the expected three blocks.
"""

import json
import re
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ci/check-faq-rendering.py <built-sample-shop-public-dir>", file=sys.stderr)
        return 2

    faq_path = Path(argv[1]) / "faq" / "index.html"
    if not faq_path.is_file():
        print(f"error: {faq_path} not found (did bin/typikon-check build sample-shop first?)", file=sys.stderr)
        return 2

    html = faq_path.read_text(encoding="utf-8")
    failures = []

    # Anchor uniqueness: the colliding base anchor and a disambiguated
    # sibling must both be present, and no id may repeat.
    ids = re.findall(r'class="faq-item" id="([^"]+)"', html)
    base = "do-you-ship-worldwide"
    if base not in ids:
        failures.append(f"expected anchor '{base}' not found")
    disambiguated = [i for i in ids if i != base and i.startswith(base + "-")]
    if not disambiguated:
        failures.append(
            f"no disambiguated sibling of '{base}' found (expected an id like "
            f"'{base}-<N>') — anchor collision not resolved"
        )
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        failures.append(f"duplicate element id(s) in rendered FAQ: {dupes}")

    # Script-breakout escaping in visible text. The visible-text rendering
    # goes through Tera's default HTML autoescaping (item.q is not
    # `| safe`), so a literal "</script>" reaches the page HTML-entity
    # encoded (verified against a real zola build: Tera's escaper encodes
    # "/" as "&#x2F;", not just "<"/">"), not as the literal characters.
    if "&lt;&#x2F;script&gt;" not in html:
        failures.append("expected HTML-escaped question text '&lt;&#x2F;script&gt;' not found — fixture content missing")

    # The page renders THREE ld+json blocks (Organization, FAQPage,
    # BreadcrumbList) — the fixture content lives in FAQPage's, so every
    # block must be checked, not just the first match. A breakout that
    # merges/splits blocks changes this count.
    ldjson_bodies = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    if len(ldjson_bodies) != 3:
        failures.append(
            "expected 3 application/ld+json script blocks (Organization, FAQPage, "
            f"BreadcrumbList), found {len(ldjson_bodies)} — a script-breakout may have "
            "merged or split blocks"
        )
    if not ldjson_bodies:
        failures.append("no application/ld+json script block found on the FAQ page")

    saw_escaped_breakout = False
    for i, body in enumerate(ldjson_bodies):
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            failures.append(
                f"application/ld+json block {i} is not valid JSON ({exc}) — an "
                "unescaped '</script>' in a field value likely truncated it early "
                "(script-breakout escaping regressed)"
            )
            continue
        if "\\/script" in body:
            saw_escaped_breakout = True

    # WHY this positive check, not just the parse-success check above: a
    # block that never contained the fixture's "</script>" question at
    # all (e.g. the fixture content silently stopped rendering) would
    # also parse as valid JSON, passing the check above vacuously.
    # Require the escaped form to actually be present in at least one
    # block.
    if not saw_escaped_breakout:
        failures.append("escaped '\\/script' not found in any valid JSON-LD block — fixture content missing")

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(f"check-faq-rendering: ok (anchors unique, {len(ids)} checked; script-breakout escaped)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
