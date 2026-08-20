#!/usr/bin/env python3
"""check-content-heading-collision — regression test for the <h1> guard
carried by every content-bearing template other than index.html
(forkwright/typikon#149, forkwright/typikon#157).

index.html's own version of this guard already has a dedicated fixture
(check-home-heading.py, forkwright/typikon#142/#152). This script proves
the same two failure modes for the rest of the family — journal-entry.html,
faq.html, sizing-guide.html, journal-section.html, page.html, and
section.html — one authoritative `<h1>` sourced from front matter
(page.title / section.title), guarded by the shared `typikon.assert.no_h1` component
against a markdown body supplying a competing one:

- page.html and section.html previously rendered NO heading of their own
  and depended entirely on a leading `# ` line in the body (#149): a
  frontmatter-only content file (the normal shape for a section index
  whose only job is to list children) built with zero headings at any
  level.
- journal-entry.html and faq.html already rendered their own `<h1>` but
  did not guard the unconditional `page.content` render beneath it (#157):
  a body starting with `# ` produced two `<h1>` elements.
- Fixing #149 by adding a template `<h1>` to page.html/section.html
  without ALSO adding the #157 guard would have reproduced #157's own
  defect in two new templates — exactly the "fix carries the class it
  was written to remove" failure shape. sizing-guide.html and
  journal-section.html already carried the unguarded #157 shape without
  being named in that issue; this fixture holds all six templates to the
  same standard so the class cannot resurface in any of them silently.

Runs the real `zola build` against ISOLATED COPIES of this theme (never
the live checkout in place), one throwaway site per (template, body)
case, mirroring check-home-heading.py's exact pattern. A check nobody has
watched fail is an unverified claim:

1. DUPLICATE heading. A body starting with a markdown `# ` line must fail
   the zola build via the `no_h1` guard, naming the template.
2. SUBHEADING escape hatch. A body starting with `##` must build clean
   with exactly one <h1>.
3. NO body at all (forkwright/typikon#149's exact shape — a
   frontmatter-only content file). Must ALSO build clean with exactly one
   <h1>, sourced from the template rather than absent.

NOTE: runs standalone (no consumer site or playwright/browser needed) as
part of ci/run-fixtures.sh, alongside check-home-heading.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
ZOLA = shutil.which("zola")

# WHY these exact [extra] fields (not a minimal guess): mirrors
# check-home-heading.py's own CONFIG_TOML, which is this theme's proof
# that the shape builds clean.
CONFIG_TOML = """title = "Fixture"
description = "typikon content-heading regression fixture"
base_url = "https://fixture.example.com"
default_language = "en"
output_dir = "public"
theme = "typikon"

[extra]
brand_name = "Fixture"
brand_greek = "Δοκιμή"
logo_path = "img/logo.svg"
theme_color = "#FBF7EC"
og_locale = "en_US"
founding_date = "2026"

[extra.author]
name = "Fixture Author"
uri = "https://fixture.example.com/about/"
"""

# WHY a root index unconditionally: index.html carries its own dedicated
# fixture (check-home-heading.py); it is never itself under test here,
# only present because every site needs a valid anchor.
HOME_FRONTMATTER = '+++\ntitle = "Fixture Home"\ntemplate = "index.html"\n+++\n'

H1_RE = re.compile(r"<h1[ >]", re.IGNORECASE)


@dataclass(frozen=True)
class ContentTemplate:
    template: str  # exact string this theme's `template` frontmatter field + typikon.assert.*(template=...) use
    is_section: bool  # section (_index.md under a subdirectory) vs. leaf page (.md)
    frontmatter_extra: str  # TOML fragment satisfying this template's own typikon.assert.required calls


# WHY these minimal shapes and no more: each satisfies exactly the
# typikon.assert.required calls its own template makes (verified by reading
# templates/*.html directly), so a build failure here can only mean the
# heading behavior under test, never an unrelated missing field.
CASES = [
    ContentTemplate(
        template="journal-entry.html",
        is_section=False,
        frontmatter_extra=(
            'description = "fixture"\n'
            "date = 2026-01-01\n"
            "\n[extra]\n"
            'audience = "fixture"\n'
            'components = "fixture"\n'
            'words = "fixture"\n'
            'words_source = "fixture"\n'
        ),
    ),
    ContentTemplate(
        template="faq.html",
        is_section=False,
        frontmatter_extra=(
            "\n[extra]\n"
            'audience = "fixture"\n'
            "[[extra.questions]]\n"
            'q = "Q"\n'
            'a = "A"\n'
        ),
    ),
    ContentTemplate(
        template="sizing-guide.html",
        is_section=False,
        frontmatter_extra=(
            "\n[extra]\n"
            'audience = "fixture"\n'
            'product_type = "widget"\n'
            'measurement_source = "fixture"\n'
            "[[extra.size_table]]\n"
            'size = "S"\n'
        ),
    ),
    ContentTemplate(template="page.html", is_section=False, frontmatter_extra=""),
    ContentTemplate(template="section.html", is_section=True, frontmatter_extra=""),
    ContentTemplate(template="journal-section.html", is_section=True, frontmatter_extra=""),
]


def copy_theme(dest: Path) -> None:
    for item in ("templates", "static", "sass", "theme.toml"):
        src = THEME_ROOT / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dest / item)
        else:
            shutil.copy2(src, dest / item)


def make_site(root: Path, theme_dir: Path, case: ContentTemplate, body: str) -> tuple[Path, str]:
    site = root / "site"
    content = site / "content"
    content.mkdir(parents=True)
    (site / "themes").mkdir()
    (site / "themes" / "typikon").symlink_to(theme_dir, target_is_directory=True)
    (site / "config.toml").write_text(CONFIG_TOML)
    (content / "_index.md").write_text(HOME_FRONTMATTER)

    frontmatter = (
        '+++\ntitle = "Fixture"\n'
        f'template = "{case.template}"\n'
        f"{case.frontmatter_extra}+++\n"
    )
    if case.is_section:
        target_dir = content / "testsec"
        target_dir.mkdir()
        (target_dir / "_index.md").write_text(frontmatter + body)
        route = "testsec"
    else:
        (content / "fixture.md").write_text(frontmatter + body)
        route = "fixture"
    return site, route


def zola_build(site: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ZOLA, "build"],
        cwd=site,
        capture_output=True,
        text=True,
        check=False,
    )


def h1_count(site: Path, route: str) -> int:
    html = (site / "public" / route / "index.html").read_text()
    return len(H1_RE.findall(html))


def run_case(root: Path, theme_dir: Path, case: ContentTemplate, failures: list[str]) -> None:
    label = case.template

    # ── Case A: duplicate heading (forkwright/typikon#157) ──────────
    dup_site, dup_route = make_site(root / f"{label}-dup", theme_dir, case, body="# Leading heading\n\nBody copy.\n")
    result = zola_build(dup_site)
    if result.returncode == 0:
        n = h1_count(dup_site, dup_route)
        failures.append(
            f"{label} duplicate-heading: a body starting with `# ` was expected to fail "
            f"the build via the no_h1 guard, but zola exited 0 with {n} <h1> element(s) — "
            "the guard did not fire"
        )
    elif "no_h1" not in result.stderr and "collides with this page's required heading" not in result.stderr:
        failures.append(
            f"{label} duplicate-heading: build failed as expected but not via the no_h1 "
            f"guard (got a different error) — the guard may not be wired:\n{result.stderr}"
        )
    elif label not in result.stderr:
        failures.append(
            f"{label} duplicate-heading: the no_h1 guard fired but its message did not "
            f"name '{label}' — a consumer could not tell which template to fix:\n{result.stderr}"
        )
    else:
        print(f"check-content-heading-collision: {label} duplicate-heading confirmed the no_h1 guard fired, naming the template")

    # ── Case B: subheading escape hatch ──────────────────────────────
    sub_site, sub_route = make_site(root / f"{label}-sub", theme_dir, case, body="## A subheading is fine\n\nBody copy.\n")
    result = zola_build(sub_site)
    if result.returncode != 0:
        failures.append(f"{label} subheading escape hatch: expected a clean build:\n{result.stderr}")
    else:
        n = h1_count(sub_site, sub_route)
        if n != 1:
            failures.append(f"{label} subheading escape hatch: expected exactly 1 <h1>, got {n}")
        else:
            print(f"check-content-heading-collision: {label} subheading-only fixture confirmed exactly 1 <h1>")

    # ── Case C: frontmatter-only body (forkwright/typikon#149) ──────
    empty_site, empty_route = make_site(root / f"{label}-empty", theme_dir, case, body="")
    result = zola_build(empty_site)
    if result.returncode != 0:
        failures.append(f"{label} frontmatter-only body: expected a clean build:\n{result.stderr}")
    else:
        n = h1_count(empty_site, empty_route)
        if n != 1:
            failures.append(
                f"{label} frontmatter-only body: expected exactly 1 <h1> sourced from the "
                f"template (forkwright/typikon#149), got {n} — a heading that depends on "
                "markdown-body convention regressed"
            )
        else:
            print(f"check-content-heading-collision: {label} frontmatter-only body confirmed exactly 1 <h1>")


def main() -> int:
    # WHY a hard failure, not a skip: same posture as check-home-heading.py
    # — zola is installed unconditionally before ci/run-fixtures.sh runs
    # (.github/workflows/gate-attestation.yml), so its absence here means
    # the install step broke, not that this check is optional.
    if ZOLA is None:
        print("check-content-heading-collision: FAIL — zola not on PATH (see gate-attestation.yml's install step)", file=sys.stderr)
        return 1

    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="typikon-content-heading-") as tmp:
        root = Path(tmp)
        theme_dir = root / "theme"
        copy_theme(theme_dir)

        for case in CASES:
            run_case(root, theme_dir, case, failures)

    if failures:
        print("check-content-heading-collision: FAIL", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    total = len(CASES) * 3
    print(f"check-content-heading-collision: ok ({total}/{total} fixtures behaved as required)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
