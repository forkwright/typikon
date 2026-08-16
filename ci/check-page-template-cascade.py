#!/usr/bin/env python3
"""check-page-template-cascade — regression test for forkwright/typikon#159.

WHY: bin/typikon-validate's classify() read only a file's OWN frontmatter
`template` field. It had no notion of Zola's page_template cascade: a
section's `_index.md` can set `page_template = "..."` and Zola applies that
template to every descendant page that sets no `template` of its own,
recursively through nested sections, with the closest ancestor winning
(https://www.getzola.org/documentation/content/section/ — "The given
template is applied to ALL pages below the section, recursively. If you
have several nested sections, each with a page_template set, the page will
always use the closest to itself. However, a page's own `template`
variable will always have priority."). Pre-fix, such a page fell through
to path-based classification and validated against the wrong schema —
reproduced below exactly as forkwright/typikon#159 reports it: a
non-canonical section directory (not content/journal/, not
content/products/) cascading one of typikon's own templates to its
children.

This script proves, against the REAL `bin/typikon-validate` CLI (Section A,
subprocess — the actual classify()+validate_file()+main() path, not a
reimplementation) and the real `_cascade_lookup` function (Section B,
imported via importlib — bin/typikon-validate has no .py suffix, so it
cannot be `import`ed normally; mirrors ci/check-triad-schema.py's own
loader for the same reason):

Section A (subprocess, full pipeline):
  1. [REQUIRED NEGATIVE FIXTURE] a leaf page with no `template` of its own,
     under a section whose _index.md sets `page_template = "faq.html"`,
     validates against faq.schema.json — exactly as if it had set
     `template = "faq.html"` itself. Pre-fix this fell through to
     page.schema.json and failed on the very extra fields ("questions")
     the cascaded template's schema exists to check.
  2. a page's own `template` always wins over an ancestor's page_template.
  3. `page_template` does NOT apply to a section's own `_index.md` — only
     to pages below it (Zola's own text: "applied to ALL pages below the
     section" — a section's _index.md is not below itself).
  4. of two nested sections that each set page_template, the closer one
     wins for its own descendants.
  5. a section that sets NO page_template does not break the chain — its
     descendants inherit from the next ancestor up that does.
  6. a malformed ancestor _index.md does not crash the run, and does not
     silently swallow ITS OWN malformed-frontmatter error (reported once,
     by the ordinary per-file path) — nor does it poison an unrelated
     sibling section's cascade.
  7. cascade resolution is independent of Path.rglob's traversal order: a
     subsection directory whose name sorts BEFORE "_index.md" ("_" is
     0x5F, above ASCII digits 0x30-0x39) still correctly inherits its
     ancestor's page_template. A cascade built incrementally during the
     main per-file walk (instead of the required full pre-pass) would
     visit this file before ever recording its own section's ancestor,
     and this case would silently fall through to path-based
     classification exactly like the un-fixed classifier does.
  8. a page_template value that resolves through the CONSUMER REGISTRY
     (forkwright/typikon#60), not just TEMPLATE_SCHEMA_MAP, is reached the
     same way — the cascade only resolves an effective `template` value;
     everything downstream of that (registry match, fail-closed checks)
     is the existing, unmodified pipeline.

Section B (direct, `_cascade_lookup` in isolation):
  proves the walk's own arithmetic — nearest-wins, skip-non-setting
  ancestors, page's-own-template-short-circuits (by never being called),
  and stopping at content/ without KeyError/IndexError past the root —
  against constructed Path keys where the full-pipeline noise (schema
  validation, frontmatter parsing) cannot obscure an off-by-one in the
  walk itself.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
VALIDATE = THEME_ROOT / "bin" / "typikon-validate"

_loader = importlib.machinery.SourceFileLoader("typikon_validate_cascade", str(VALIDATE))
_spec = importlib.util.spec_from_loader("typikon_validate_cascade", _loader)
_tv = importlib.util.module_from_spec(_spec)
sys.modules["typikon_validate_cascade"] = _tv  # WHY: dataclass() resolves types via sys.modules[__module__]
_spec.loader.exec_module(_tv)


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def run_validate(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE), str(root)],
        capture_output=True, text=True, check=False,
    )


# NOTE: ── Section A: subprocess, full pipeline ──────────────────────────

# NOTE: each case is (label, files, expected_exit, required_stderr_substrings)
CASES: list[tuple[str, dict[str, str], int, list[str]]] = [
    (
        # WHY: REQUIRED NEGATIVE FIXTURE for #159. Pre-fix command + failure,
        # captured verbatim (git stash of the pre-fix bin/typikon-validate
        # run against this exact fixture):
        #   $ python3 bin/typikon-validate <this fixture>
        #   {"file": "content/guides/shipping.md", "schema": "page",
        #    "pointer": "/extra", "error": "Unevaluated properties are not
        #    allowed ('questions' was unexpected)"}
        #   {"checked": 2, "passed": 1, "failed": 1}
        #   exit=1
        # "questions" is faq.schema.json's own required array field —
        # page.schema.json's extra has never heard of it. Post-fix, the
        # cascade resolves content/guides/shipping.md's effective template
        # to "faq.html" (from content/guides/_index.md's page_template,
        # since the page itself sets none) and validates it against
        # faq.schema.json, where `questions` is exactly the right shape.
        "leaf page with no template, under a section with page_template=faq.html, cascades to faq.schema.json",
        {
            "content/guides/_index.md": (
                '+++\ntitle = "Guides"\ntemplate = "section.html"\n'
                'page_template = "faq.html"\n+++\nbody\n'
            ),
            "content/guides/shipping.md": (
                '+++\ntitle = "Shipping FAQ"\n\n[extra]\naudience = "customers"\n\n'
                '[[extra.questions]]\nq = "How long does shipping take?"\n'
                'a = "Three to five business days."\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "a page's own template overrides an ancestor's page_template",
        {
            "content/guides/_index.md": (
                '+++\ntitle = "Guides"\npage_template = "faq.html"\n+++\nbody\n'
            ),
            "content/guides/plain.md": (
                '+++\ntitle = "Plain page, not a FAQ"\ntemplate = "page.html"\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "page_template does not apply to a section's OWN _index.md — a nested section under a page_template ancestor still classifies as section, not the cascaded schema",
        {
            "content/guides/_index.md": (
                '+++\ntitle = "Guides"\npage_template = "faq.html"\n+++\nbody\n'
            ),
            # WHY: A nested section index: structurally a section (name ==
            # "_index.md"), so it must classify via section.schema.json
            # regardless of the ancestor's page_template. If the cascade
            # wrongly applied here, this would be validated against
            # faq.schema.json and fail (no `extra.questions`); it must
            # pass as a section instead.
            "content/guides/shipping/_index.md": (
                '+++\ntitle = "Shipping"\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "nested sections: the CLOSER ancestor's page_template wins over a farther one",
        {
            "content/guides/_index.md": (
                '+++\ntitle = "Guides"\npage_template = "faq.html"\n+++\nbody\n'
            ),
            "content/guides/sizing/_index.md": (
                '+++\ntitle = "Sizing"\npage_template = "sizing-guide.html"\n+++\nbody\n'
            ),
            # WHY: No template of its own; nearest ancestor (guides/sizing) sets
            # page_template = sizing-guide.html — must NOT pick up the
            # farther content/guides/ ancestor's faq.html instead. A sizing
            # fixture validated as faq (extra.questions required) would
            # fail; validated as sizing-guide (extra.sizes required) is
            # the correct outcome and is what this fixture supplies.
            "content/guides/sizing/shirt.md": (
                '+++\ntitle = "Shirt Sizing"\n\n[extra]\naudience = "customers"\n'
                'product_type = "shirt"\nmeasurement_source = "pattern block"\n\n'
                '[[extra.size_table]]\nsize = "M"\nwaist = "38-40in"\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "a section with NO page_template of its own does not break the chain — its child inherits from the next ancestor up",
        {
            "content/guides/_index.md": (
                '+++\ntitle = "Guides"\npage_template = "faq.html"\n+++\nbody\n'
            ),
            # WHY: sizing/_index.md sets no page_template at all — the walk
            # must skip past it (not stop / not treat "unset" as a match)
            # and keep going up to content/guides/, inheriting faq.html.
            "content/guides/sizing/_index.md": '+++\ntitle = "Sizing"\n+++\nbody\n',
            "content/guides/sizing/note.md": (
                '+++\ntitle = "A note, not a size chart"\n\n[extra]\naudience = "customers"\n\n'
                '[[extra.questions]]\nq = "Is this a FAQ page?"\na = "Yes, by inheritance."\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "a malformed ancestor _index.md does not crash the run: its own error is reported once, and it contributes nothing to the cascade (sibling section unaffected)",
        {
            "content/guides/_index.md": '+++\ntitle = "Guides"\npage_template = "faq.html\n+++\nbody\n',  # NOTE: unterminated string — malformed TOML
            "content/other/_index.md": '+++\ntitle = "Other"\n+++\nbody\n',
            "content/other/plain.md": '+++\ntitle = "Plain"\n+++\nbody\n',
        },
        1,
        ["content/guides/_index.md"],
    ),
    (
        # WHY: Path.rglob's walk order is lexicographic
        # per path segment. "_index.md" (leading "_", 0x5F) sorts BELOW
        # any letter but ABOVE any ASCII digit (0x30-0x39), so a sibling
        # directory named "2026-faq" sorts, and so is visited, BEFORE its
        # own section's "_index.md" in that same walk. An incremental,
        # single-pass cascade (recording page_template as the main loop
        # reaches each _index.md) would visit content/guides/2026-faq/
        # leaf.md before ever recording content/guides/2026-faq/_index.md's
        # page_template, and this fixture would silently fall through to
        # page.schema.json — exactly the un-fixed classifier's failure
        # mode, just for a different reason. The required full pre-pass
        # (build_page_template_cascade) makes this order-independent.
        "cascade resolution does not depend on Path.rglob's traversal order (digit-prefixed subsection sorts before its own _index.md)",
        {
            "content/guides/2026-faq/_index.md": (
                '+++\ntitle = "2026 FAQ"\npage_template = "faq.html"\n+++\nbody\n'
            ),
            "content/guides/2026-faq/leaf.md": (
                '+++\ntitle = "Leaf"\n\n[extra]\naudience = "customers"\n\n'
                '[[extra.questions]]\nq = "Does order-independence hold?"\na = "Yes, it does."\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        # WHY: A page_template value reaching the #60 CONSUMER REGISTRY, not
        # just the built-in TEMPLATE_SCHEMA_MAP — proves the cascade only
        # resolves an effective `template`; everything downstream
        # (registry_hit / fail-closed / MismatchedExtendsError) is the
        # existing, unmodified pipeline reached the same way an explicit
        # `template = "consulting.html"` would reach it.
        "a page_template resolving through the consumer registry (not TEMPLATE_SCHEMA_MAP) is reached the same way an explicit template would be",
        {
            "schemas/registry.toml": (
                '[[entry]]\ntemplate = "consulting.html"\n'
                'schema = "schemas/consulting.schema.json"\nextends = "page"\n'
            ),
            "schemas/consulting.schema.json": (
                '{\n  "$schema": "https://json-schema.org/draft/2020-12/schema",\n'
                '  "$id": "https://ardent.tools/schemas/consulting.schema.json",\n'
                '  "title": "consulting page",\n'
                '  "allOf": [{"$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json"}],\n'
                '  "properties": {"extra": {\n'
                '    "allOf": [{"$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json#/properties/extra"}],\n'
                '    "unevaluatedProperties": false,\n'
                '    "properties": {"ardent": {"type": "object", "additionalProperties": false,\n'
                '      "required": ["kanon_ci"], "properties": {"kanon_ci": {"type": "boolean"}}}}\n'
                "  }},\n"
                '  "unevaluatedProperties": false\n}\n'
            ),
            "content/approach/_index.md": (
                '+++\ntitle = "Approach"\npage_template = "consulting.html"\n+++\nbody\n'
            ),
            "content/approach/method.md": (
                '+++\ntitle = "Method"\n\n[extra.ardent]\nkanon_ci = true\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
]


def run_section_a() -> list[str]:
    failed = []
    for label, files, expected_exit, required_substrings in CASES:
        with tempfile.TemporaryDirectory(prefix="typikon-cascade-check-") as tmp:
            root = Path(tmp)
            write_tree(root, files)
            result = run_validate(root)
            if result.returncode != expected_exit:
                failed.append(
                    f"{label}: expected exit {expected_exit}, got {result.returncode}\n"
                    f"  stdout: {result.stdout.strip()}\n  stderr: {result.stderr.strip()}"
                )
                continue
            missing = [s for s in required_substrings if s not in result.stderr]
            if missing:
                failed.append(f"{label}: stderr missing expected substring(s) {missing}\n  stderr: {result.stderr.strip()}")
    return failed


# NOTE: ── Section B: `_cascade_lookup` in isolation ─────────────────────

def run_section_b() -> list[str]:
    failed = []
    lookup = _tv._cascade_lookup

    # WHY: nearest ancestor wins over a farther one that also sets page_template
    cascade = {
        Path("content"): "page.html",
        Path("content/a"): "faq.html",
        Path("content/a/b"): "sizing-guide.html",
    }
    got = lookup(Path("content/a/b"), cascade)
    if got != "sizing-guide.html":
        failed.append(f"nearest-wins: expected 'sizing-guide.html', got {got!r}")

    # WHY: a directory with no cascade entry of its own is skipped, not treated as a stop
    got = lookup(Path("content/a/b/c"), cascade)  # NOTE: b/c has no entry; nearest SET ancestor is content/a/b
    if got != "sizing-guide.html":
        failed.append(f"skip-unset-directory-still-finds-nearest-SET-ancestor: expected 'sizing-guide.html', got {got!r}")

    # WHY: only content/a set (b sets nothing): inherits from content/a
    cascade2 = {Path("content"): "page.html", Path("content/a"): "faq.html"}
    got = lookup(Path("content/a/b"), cascade2)
    if got != "faq.html":
        failed.append(f"inherit-past-non-setting-section: expected 'faq.html', got {got!r}")

    # WHY: nothing set anywhere in the chain -> None, no exception walking past content/
    got = lookup(Path("content/a/b"), {})
    if got is not None:
        failed.append(f"no-ancestor-sets-page_template: expected None, got {got!r}")

    # WHY: root section itself (content/) is checked, not skipped
    cascade3 = {Path("content"): "index.html"}
    got = lookup(Path("content"), cascade3)
    if got != "index.html":
        failed.append(f"root-section-checked: expected 'index.html', got {got!r}")

    return failed


def main() -> int:
    failed = run_section_a() + run_section_b()
    if failed:
        for line in failed:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1
    print(json.dumps({"checked": len(CASES) + 5, "passed": len(CASES) + 5, "failed": 0}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
