#!/usr/bin/env python3
"""check-journal-entry-routing — regression test for forkwright/typikon#163.

WHY: TEMPLATE_SCHEMA_MAP (bin/typikon-validate) had entries for faq.html and
sizing-guide.html only. journal-entry.html is a KNOWN_TEMPLATES member -- a
consumer may set `template = "journal-entry.html"` explicitly, or reach it
via the #159 page_template cascade, without tripping the fail-closed
UnregisteredTemplateError -- but because it was absent from
TEMPLATE_SCHEMA_MAP, classify() never routed it to journal-entry.schema.json
by template name; only content/journal/<slug>.md's PATH rule reached that
schema. A page whose effective template is journal-entry.html but whose path
is NOT content/journal/ (forkwright/ardent-tools-site's content/writing/, the
exact #159 cascade case) silently fell through to page.schema.json instead --
the same fail-open shape the #60 consumer-schema-registry work closed for
truly-custom templates, just left open for this one built-in.

Independently, journal-entry.schema.json's `extra` (additionalProperties:
false) had no entries for figure, figure_alt, or tier -- real fields
forkwright/ardent-tools-site's journal-entry content sets (verified directly
against the live site: content/writing/coordination-that-isnt-voting.md sets
all three; templates/journal-section.html there groups the listing by
extra.tier and fails closed if any entry lacks it). Even a page correctly
routed to journal-entry.schema.json still failed on these three fields.

This proves both fixes, and both together, against the REAL bin/typikon-
validate CLI (subprocess -- the actual classify()/validate_file()/main()
path, not a reimplementation):

  1. [REQUIRED NEGATIVE FIXTURE] a leaf page with no template of its own,
     under a section whose _index.md sets page_template = "journal-entry.html"
     (a non-canonical section, mirroring ardent-tools-site's content/writing/
     exactly), with figure/figure_alt/tier extras matching that site's real
     content -- must validate against journal-entry.schema.json, not
     page.schema.json.
  2. the same, with `template = "journal-entry.html"` set directly on the
     leaf page instead of cascaded -- the Done-when's second named case.
  3. [isolates the schema-shape half] a page ALREADY routed correctly via the
     path rule (content/journal/<slug>.md, unaffected by the TEMPLATE_SCHEMA_
     MAP fix either way) still needs the schema to accept figure/figure_alt/
     tier.
  4. extra.figure without extra.figure_alt fails closed (dependentRequired)
     -- proves the guard's OWN logic links the two fields, not just that
     each is independently accepted.
  5. an invalid extra.tier value fails closed (enum) -- proves the tier
     vocabulary is enforced, not merely documented.
  6. CONTROL: an existing content/journal/<slug>.md fixture with no figure/
     tier and no explicit template still validates clean -- the
     TEMPLATE_SCHEMA_MAP addition must not perturb on-path behavior at all
     (the issue's own "Verified safe" claim, checked empirically here rather
     than trusted).
  7. CONTROL: a genuinely unregistered custom template still raises
     UnregisteredTemplateError -- the fail-closed net for templates typikon
     truly does not know is unaffected by adding one more KNOWN entry to
     TEMPLATE_SCHEMA_MAP.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
VALIDATE = THEME_ROOT / "bin" / "typikon-validate"

# NOTE: mirrors forkwright/ardent-tools-site's real
# content/writing/coordination-that-isnt-voting.md frontmatter exactly
# (audience/components/words/words_source are typikon's own required
# journal-entry extras; figure/figure_alt/tier are the #163 additions).
REAL_EXTRAS = (
    'audience = "readers evaluating multi-agent coordination claims"\n'
    'components = "Why voting and hub-orchestration both fail on hard tasks, '
    'and a third coordination shape that isn\'t a blend of them."\n'
    'words = "~1470 words"\n'
    'words_source = "manual count"\n'
    'tier = "research"\n'
    'figure = "img/coordination-shapes.svg"\n'
    'figure_alt = "Three coordination shapes side by side: vote, where isolated '
    'agents fan in to an aggregator with no connections between them; hub, where '
    'a hub farms pieces out to workers and assembles them back with no lateral '
    'edges; and lateral, where agents influence each other during solve before '
    'an integrator composes."\n'
)


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


# NOTE: each case is (label, files, expected_exit, required_stderr_substrings)
CASES: list[tuple[str, dict[str, str], int, list[str]]] = [
    (
        "leaf page with no template, under a non-canonical section whose "
        "_index.md cascades page_template=journal-entry.html, with real "
        "figure/figure_alt/tier extras -- validates as journal-entry, not page",
        {
            "content/writing/_index.md": (
                '+++\ntitle = "Writing"\ntemplate = "journal-section.html"\n'
                'page_template = "journal-entry.html"\n+++\nbody\n'
            ),
            "content/writing/coordination.md": (
                '+++\ntitle = "Coordination that isn\'t voting"\n'
                'description = "Voting and hub-orchestration are the two default '
                'shapes of multi-agent coordination, and why a third needs its own '
                f'emergence conditions."\ndate = 2026-07-20\n\n[extra]\n{REAL_EXTRAS}+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "leaf page setting template=journal-entry.html directly (not cascaded), "
        "under a non-canonical section -- the Done-when's second named case",
        {
            "content/writing/direct.md": (
                '+++\ntitle = "Directly Templated"\ntemplate = "journal-entry.html"\n'
                'description = "A leaf page that sets journal-entry.html on itself, '
                'with no ancestor cascade involved at all."\ndate = 2026-07-21\n\n'
                f'[extra]\n{REAL_EXTRAS}+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "content/journal/<slug>.md (path-based routing, unaffected either way "
        "by TEMPLATE_SCHEMA_MAP) still needs the schema to accept figure/tier",
        {
            "content/journal/entry.md": (
                '+++\ntitle = "A Journal Entry"\n'
                'description = "Ordinary path-routed journal entry carrying the '
                'same real figure/figure_alt/tier extras."\ndate = 2026-07-22\n\n'
                f'[extra]\n{REAL_EXTRAS}+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "extra.figure without extra.figure_alt fails closed (dependentRequired)",
        {
            "content/journal/no-alt.md": (
                '+++\ntitle = "Missing Alt"\ndescription = "A figure with no alt '
                'text must fail, not silently render an empty alt attribute."\n'
                'date = 2026-07-23\n\n[extra]\naudience = "readers"\n'
                'components = "a tag line long enough to pass"\nwords = "~10 words"\n'
                'words_source = "manual count"\nfigure = "img/x.svg"\n+++\nbody\n'
            ),
        },
        1,
        ["'figure_alt' is a dependency of 'figure'"],
    ),
    (
        "an invalid extra.tier value fails closed (enum)",
        {
            "content/journal/bad-tier.md": (
                '+++\ntitle = "Bad Tier"\ndescription = "A tier value outside the '
                'notes/research vocabulary must fail, not pass silently."\n'
                'date = 2026-07-24\n\n[extra]\naudience = "readers"\n'
                'components = "a tag line long enough to pass"\nwords = "~10 words"\n'
                'words_source = "manual count"\ntier = "bogus"\n+++\nbody\n'
            ),
        },
        1,
        ["'bogus' is not one of"],
    ),
    (
        "CONTROL: an ordinary content/journal/<slug>.md entry with no template, "
        "no figure, no tier still validates clean -- on-path behavior unperturbed",
        {
            "content/journal/plain.md": (
                '+++\ntitle = "Plain Entry"\ndescription = "An ordinary entry with '
                'none of the #163 fields set at all, proving the fix changes '
                'nothing for existing content."\ndate = 2026-07-25\n\n[extra]\n'
                'audience = "readers"\ncomponents = "a tag line long enough to pass"\n'
                'words = "~10 words"\nwords_source = "manual count"\n+++\nbody\n'
            ),
        },
        0,
        [],
    ),
    (
        "CONTROL: a genuinely unregistered custom template still fails closed",
        {
            "content/writing/custom.md": (
                '+++\ntitle = "Custom"\ntemplate = "totally-unregistered.html"\n+++\nbody\n'
            ),
        },
        1,
        ["totally-unregistered.html", "has no schema registration"],
    ),
]


def run_cases() -> list[str]:
    failed = []
    for label, files, expected_exit, required_substrings in CASES:
        with tempfile.TemporaryDirectory(prefix="typikon-journal-routing-check-") as tmp:
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


def main() -> int:
    failed = run_cases()
    if failed:
        for line in failed:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1
    print(json.dumps({"checked": len(CASES), "passed": len(CASES), "failed": 0}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
