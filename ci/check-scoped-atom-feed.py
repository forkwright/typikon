#!/usr/bin/env python3
"""Render the root-feed source-section contract with pinned Zola.

Static template checks cannot prove Zola's supplied feed set, transparent-
section bubbling, feed-limit ordering, or Tera's rendered XML. This fixture
builds isolated temporary consumers and verifies both the opt-in contract and
the unchanged native behavior. It never writes generated output into the
checkout.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


THEME_ROOT = Path(__file__).resolve().parent.parent
ZOLA = shutil.which("zola")
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
BASE_URL = "https://scoped-feed.example.com"


def config_toml(scope: str | None) -> str:
    scope_line = "" if scope is None else f'feed_source_section = "{scope}"\n'
    template = '''title = "Scoped Feed Fixture"
description = "Whole-site description that must not replace the source section."
base_url = "__BASE_URL__"
default_language = "en"
output_dir = "public"
theme = "typikon"
generate_feeds = true
feed_filenames = ["atom.xml"]
feed_limit = 2
taxonomies = [{name = "tags", feed = true}]

[extra]
brand_name = "Scoped Feed Fixture"
brand_greek = "Δοκιμή"
logo_path = "img/logo.svg"
theme_color = "#FBF7EC"
og_locale = "en_US"
founding_date = "2026"
__SCOPE_LINE__'''
    return template.replace("__BASE_URL__", BASE_URL).replace("__SCOPE_LINE__", scope_line)


ROOT = '''+++
title = "Home"
description = "Fixture home section."
template = "section.html"
+++
'''

JOURNAL = '''+++
title = "Journal"
description = "Only direct Journal entries belong to the canonical root feed."
sort_by = "date"
generate_feeds = true
template = "journal-section.html"
page_template = "journal-entry.html"
+++
'''

EMPTY = '''+++
title = "Empty"
description = "Configured empty section used to prove fail-closed behavior."
+++
'''

PRODUCTS = '''+++
title = "Products"
description = "Unrelated products must not enter the scoped root feed."
+++
'''


def journal_entry(
    title: str,
    date: str,
    body: str,
    *,
    updated: str | None = None,
    include: bool = True,
    tags: tuple[str, ...] = (),
) -> str:
    updated_line = "" if updated is None else f"updated = {updated}\n"
    include_line = "" if include else "include_in_feeds = false\n"
    taxonomy_block = ""
    if tags:
        rendered_tags = ", ".join('"{}"'.format(tag) for tag in tags)
        taxonomy_block = "\n[taxonomies]\ntags = [{}]\n".format(rendered_tags)
    return '''+++
title = "{title}"
description = "Rendered fixture entry for the scoped Atom feed contract."
date = {date}
{updated_line}{include_line}{taxonomy_block}
[extra]
audience = "readers verifying the scoped feed"
components = "Atom · scope · ordering"
+++

{body}
'''.format(
        title=title,
        date=date,
        updated_line=updated_line,
        include_line=include_line,
        taxonomy_block=taxonomy_block,
        body=body,
    )


def make_site(root: Path, scope: str | None) -> Path:
    site = root / "site"
    journal = site / "content" / "journal"
    notes = journal / "notes"
    products = site / "content" / "products"
    empty = site / "content" / "empty"
    for directory in (notes, products, empty, site / "themes", site / "templates"):
        directory.mkdir(parents=True, exist_ok=True)
    (site / "themes" / "typikon").symlink_to(THEME_ROOT, target_is_directory=True)

    files = {
        site / "config.toml": config_toml(scope),
        site / "templates" / "taxonomy_list.html": (
            "<!doctype html><title>Fixture taxonomy list</title>\n"
        ),
        site / "templates" / "taxonomy_single.html": (
            "<!doctype html><title>Fixture taxonomy term</title>\n"
        ),
        site / "content" / "_index.md": ROOT,
        journal / "_index.md": JOURNAL,
        journal / "beta.md": journal_entry("Beta", "2026-08-18", "Beta body.", tags=("proof",)),
        journal / "gamma.md": journal_entry("Gamma", "2026-08-19", "Gamma body.", tags=("proof",)),
        journal / "excluded.md": journal_entry(
            "Excluded", "2026-08-24", "Excluded body.", include=False
        ),
        notes / "_index.md": '''+++
title = "Transparent notes"
description = "Nested entries bubble into the parent section but not its direct-page feed scope."
transparent = true
page_template = "journal-entry.html"
+++
''',
        notes / "nested.md": journal_entry(
            "Nested", "2026-08-23", "Nested transparent-section body."
        ),
        products / "_index.md": PRODUCTS,
        products / "newer.md": '''+++
title = "Newer Product"
description = "A newer dated page outside the configured Journal scope."
date = 2026-08-22
+++

Original product body.
''',
        site / "content" / "terms.md": '''+++
title = "Terms"
description = "An unrelated dated terms page outside the configured scope."
date = 2026-08-21
+++

Original terms body.
''',
        empty / "_index.md": EMPTY,
    }
    for path, value in files.items():
        path.write_text(value, encoding="utf-8")
    return site


def run_build(site: Path, *, expect_success: bool) -> subprocess.CompletedProcess[str]:
    public = site / "public"
    if public.exists():
        shutil.rmtree(public)
    result = subprocess.run(
        [ZOLA, "build"],
        cwd=site,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"Zola build exited {result.returncode}:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not expect_success and result.returncode == 0:
        raise AssertionError("Zola build unexpectedly accepted an invalid feed source")
    return result


def run_validate(site: Path, *, expect_success: bool) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(THEME_ROOT / "bin" / "typikon-validate"), str(site)],
        cwd=site,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"typikon-validate exited {result.returncode}:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not expect_success and result.returncode == 0:
        raise AssertionError("typikon-validate unexpectedly accepted an invalid feed owner")
    return result


def parse_atom(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def entry_ids(feed: ET.Element) -> list[str]:
    return [
        value
        for value in (
            entry.findtext("atom:id", namespaces=ATOM)
            for entry in feed.findall("atom:entry", ATOM)
        )
        if value is not None
    ]


def entry_updated(feed: ET.Element, entry_id: str) -> str | None:
    for entry in feed.findall("atom:entry", ATOM):
        if entry.findtext("atom:id", namespaces=ATOM) == entry_id:
            return entry.findtext("atom:updated", namespaces=ATOM)
    return None


def alternate_href(feed: ET.Element) -> str | None:
    for link in feed.findall("atom:link", ATOM):
        if link.get("rel") != "self":
            return link.get("href")
    return None


def require(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def check_scoped_site(root: Path) -> None:
    site = make_site(root, "journal/_index.md")
    run_build(site, expect_success=True)
    root_atom_path = site / "public" / "atom.xml"
    root_feed = parse_atom(root_atom_path)
    expected_root_ids = [
        f"{BASE_URL}/journal/gamma/",
        f"{BASE_URL}/journal/beta/",
    ]
    require(entry_ids(root_feed), expected_root_ids, "scoped root membership/order/feed_limit")
    require(
        root_feed.findtext("atom:updated", namespaces=ATOM),
        "2026-08-19T00:00:00+00:00",
        "initial scoped root freshness",
    )
    require(
        root_feed.findtext("atom:title", namespaces=ATOM),
        "Scoped Feed Fixture - Journal",
        "scoped root title",
    )
    require(
        root_feed.findtext("atom:subtitle", namespaces=ATOM),
        "Only direct Journal entries belong to the canonical root feed.",
        "scoped root subtitle",
    )
    require(alternate_href(root_feed), f"{BASE_URL}/journal/", "scoped root alternate")

    section_feed = parse_atom(site / "public" / "journal" / "atom.xml")
    require(
        entry_ids(section_feed),
        [f"{BASE_URL}/journal/notes/nested/", f"{BASE_URL}/journal/gamma/"],
        "native section feed remains engine-owned",
    )
    taxonomy_feed = parse_atom(site / "public" / "tags" / "proof" / "atom.xml")
    require(
        entry_ids(taxonomy_feed),
        [f"{BASE_URL}/journal/gamma/", f"{BASE_URL}/journal/beta/"],
        "native taxonomy feed remains engine-owned",
    )

    beta = site / "content" / "journal" / "beta.md"
    beta.write_text(
        beta.read_text(encoding="utf-8").replace(
            "date = 2026-08-18\n", "date = 2026-08-18\nupdated = 2026-08-25\n"
        ),
        encoding="utf-8",
    )
    run_build(site, expect_success=True)
    edited_feed = parse_atom(root_atom_path)
    require(
        edited_feed.findtext("atom:updated", namespaces=ATOM),
        "2026-08-25T00:00:00+00:00",
        "older entry edit advances root freshness",
    )
    require(
        entry_updated(edited_feed, f"{BASE_URL}/journal/beta/"),
        "2026-08-25T00:00:00+00:00",
        "older entry edit advances its entry timestamp",
    )

    original_atom = root_atom_path.read_bytes()
    (site / "content" / "terms.md").write_text(
        (site / "content" / "terms.md").read_text(encoding="utf-8")
        .replace("Original terms body.", "Edited unrelated terms body."),
        encoding="utf-8",
    )
    (site / "content" / "products" / "newer.md").write_text(
        (site / "content" / "products" / "newer.md").read_text(encoding="utf-8")
        .replace("Original product body.", "Edited unrelated product body."),
        encoding="utf-8",
    )
    run_build(site, expect_success=True)
    require(
        (site / "public" / "atom.xml").read_bytes(),
        original_atom,
        "unrelated content leaves scoped root feed byte-identical",
    )


def check_limit_and_ties(root: Path) -> None:
    site = make_site(root, "journal/_index.md")
    journal = site / "content" / "journal"
    (journal / "alpha.md").write_text(
        journal_entry("Alpha", "2026-08-19", "Alpha tie-order body."),
        encoding="utf-8",
    )
    (journal / "delta.md").write_text(
        journal_entry(
            "Delta",
            "2026-08-17",
            "Delta full-scope freshness body.",
            updated="2026-08-26",
        ),
        encoding="utf-8",
    )
    run_build(site, expect_success=True)
    feed = parse_atom(site / "public" / "atom.xml")
    require(
        entry_ids(feed),
        [f"{BASE_URL}/journal/alpha/", f"{BASE_URL}/journal/gamma/"],
        "same-date permalink tie and native feed limit",
    )
    require(
        feed.findtext("atom:updated", namespaces=ATOM),
        "2026-08-26T00:00:00+00:00",
        "full scoped freshness includes an entry outside the feed limit",
    )


def check_colocated_directness(root: Path) -> None:
    site = make_site(root, "journal/_index.md")
    journal = site / "content" / "journal"
    direct = journal / "bundle"
    nested = journal / "notes" / "nested-bundle"
    direct.mkdir()
    nested.mkdir()
    (direct / "index.md").write_text(
        journal_entry("Direct bundle", "2026-08-20", "Direct colocated body."),
        encoding="utf-8",
    )
    (nested / "index.md").write_text(
        journal_entry("Nested bundle", "2026-08-25", "Nested transparent bundle body."),
        encoding="utf-8",
    )
    config = site / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("feed_limit = 2", "feed_limit = 3"),
        encoding="utf-8",
    )
    run_build(site, expect_success=True)
    require(
        entry_ids(parse_atom(site / "public" / "atom.xml")),
        [
            f"{BASE_URL}/journal/bundle/",
            f"{BASE_URL}/journal/gamma/",
            f"{BASE_URL}/journal/beta/",
        ],
        "direct colocated leaf is included while nested transparent bundle is excluded",
    )


def check_native_datetime_order(root: Path) -> None:
    site = make_site(root, "journal/_index.md")
    journal = site / "content" / "journal"
    (journal / "beta.md").write_text(
        journal_entry(
            "Beta",
            "2026-08-19T00:30:00+02:00",
            "Lexically later but chronologically earlier body.",
        ),
        encoding="utf-8",
    )
    (journal / "gamma.md").write_text(
        journal_entry(
            "Gamma",
            "2026-08-18T23:45:00+00:00",
            "Chronologically later body.",
        ),
        encoding="utf-8",
    )
    run_build(site, expect_success=True)
    require(
        entry_ids(parse_atom(site / "public" / "atom.xml")),
        [f"{BASE_URL}/journal/gamma/", f"{BASE_URL}/journal/beta/"],
        "native parsed-datetime ordering beats lexical RFC3339 ordering",
    )


def check_wrong_sort_fails_validation(root: Path) -> None:
    site = make_site(root, "journal/_index.md")
    owner = site / "content" / "journal" / "_index.md"
    owner.write_text(
        owner.read_text(encoding="utf-8").replace('sort_by = "date"', 'sort_by = "weight"'),
        encoding="utf-8",
    )
    result = run_validate(site, expect_success=False)
    output = f"{result.stdout}\n{result.stderr}"
    for expected in ("content/journal/_index.md", "sort_by", "date"):
        if expected not in output:
            raise AssertionError(
                f"wrong-sort failure did not name {expected!r}:\n{output}"
            )


def check_translated_wrong_sort_fails_validation(root: Path) -> None:
    site = make_site(root, "journal/_index.md")
    translated = site / "content" / "journal" / "_index.fr.md"
    translated.write_text(
        JOURNAL.replace('title = "Journal"', 'title = "Journal français"').replace(
            'sort_by = "date"', 'sort_by = "weight"'
        ),
        encoding="utf-8",
    )
    result = run_validate(site, expect_success=False)
    output = f"{result.stdout}\n{result.stderr}"
    for expected in ("content/journal/_index.fr.md", "sort_by", "date"):
        if expected not in output:
            raise AssertionError(
                f"translated wrong-sort failure did not name {expected!r}:\n{output}"
            )


def check_multilingual_scope(root: Path) -> None:
    site = make_site(root, "journal/_index.md")
    # This case also proves the validator's success path. Narrow the shared
    # renderer fixture to fields owned by Typikon's current closed schemas;
    # taxonomy rendering and product fixtures are tested separately.
    shutil.rmtree(site / "content" / "products")
    canonical_owner = site / "content" / "journal" / "_index.md"
    canonical_owner.write_text(
        canonical_owner.read_text(encoding="utf-8").replace("generate_feeds = true\n", ""),
        encoding="utf-8",
    )
    for name in ("beta.md", "gamma.md"):
        path = site / "content" / "journal" / name
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '\n[taxonomies]\ntags = ["proof"]\n', ""
            ),
            encoding="utf-8",
        )
    config = site / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + '''

[languages.fr]
title = "Flux délimité"
description = "Fixture française."
generate_feeds = true
feed_filenames = ["atom.xml"]
''',
        encoding="utf-8",
    )
    (site / "content" / "_index.fr.md").write_text(
        '''+++
title = "Accueil français"
description = "Accueil traduit."
template = "section.html"
+++
''',
        encoding="utf-8",
    )
    journal = site / "content" / "journal"
    translated_owner = journal / "_index.fr.md"
    translated_owner.write_text(
        JOURNAL.replace('title = "Journal"', 'title = "Journal français"').replace(
            'sort_by = "date"', 'sort_by = "weight"'
        ).replace("generate_feeds = true\n", ""),
        encoding="utf-8",
    )
    (journal / "beta.fr.md").write_text(
        journal_entry("Bêta", "2026-08-18", "Corps bêta."), encoding="utf-8"
    )
    (journal / "gamma.fr.md").write_text(
        journal_entry("Gamma", "2026-08-19", "Corps gamma."), encoding="utf-8"
    )

    invalid = run_validate(site, expect_success=False)
    invalid_output = f"{invalid.stdout}\n{invalid.stderr}"
    if "content/journal/_index.fr.md" not in invalid_output or "sort_by" not in invalid_output:
        raise AssertionError(
            "translated owner with wrong sort did not fail closed:\n" + invalid_output
        )

    translated_owner.write_text(
        translated_owner.read_text(encoding="utf-8").replace(
            'sort_by = "weight"', 'sort_by = "date"'
        ),
        encoding="utf-8",
    )
    run_validate(site, expect_success=True)
    run_build(site, expect_success=True)
    require(
        entry_ids(parse_atom(site / "public" / "fr" / "atom.xml")),
        [f"{BASE_URL}/fr/journal/gamma/", f"{BASE_URL}/fr/journal/beta/"],
        "translated root feed resolves and preserves the translated date-sorted owner",
    )


def check_unset_site(root: Path) -> None:
    site = make_site(root, None)
    run_build(site, expect_success=True)
    require(
        entry_ids(parse_atom(site / "public" / "atom.xml")),
        [f"{BASE_URL}/journal/notes/nested/", f"{BASE_URL}/products/newer/"],
        "unset scope preserves Zola's site-wide feed set",
    )


def check_invalid_scope(root: Path, scope: str, expected_text: str) -> None:
    site = make_site(root, scope)
    result = run_build(site, expect_success=False)
    output = f"{result.stdout}\n{result.stderr}"
    if expected_text not in output:
        raise AssertionError(
            f"invalid scope failure did not name {expected_text!r}:\n{output}"
        )


def check_invalid_path_spelling(root: Path, scope: str) -> None:
    site = make_site(root, scope)
    result = run_validate(site, expect_success=False)
    output = f"{result.stdout}\n{result.stderr}"
    for expected in ("feed_source_section", "normalized POSIX", "_index.md"):
        if expected not in output:
            raise AssertionError(
                f"invalid path spelling {scope!r} did not name {expected!r}:\n{output}"
            )
    try:
        summary = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise AssertionError(
            f"invalid path spelling did not emit a JSON summary: {result.stdout!r}"
        ) from exc
    if summary.get("config_failed") is not True:
        raise AssertionError(f"config failure was not reported explicitly: {summary!r}")
    if summary.get("passed") + summary.get("failed") != summary.get("checked"):
        raise AssertionError(f"content accounting is inconsistent: {summary!r}")


def main() -> int:
    if ZOLA is None:
        print(
            "check-scoped-atom-feed: FAIL — zola not on PATH "
            "(see gate-attestation.yml's install step)",
            file=sys.stderr,
        )
        return 1

    version = subprocess.run(
        [ZOLA, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    version_text = f"{version.stdout}\n{version.stderr}".strip()
    if version.returncode != 0 or version_text != "zola 0.23.3":
        print(
            "check-scoped-atom-feed: FAIL — expected zola 0.23.3, got "
            f"exit {version.returncode} and output {version_text!r}",
            file=sys.stderr,
        )
        return 1

    try:
        with tempfile.TemporaryDirectory(prefix="typikon-scoped-feed-") as tmp:
            base = Path(tmp)
            check_scoped_site(base / "scoped")
            check_limit_and_ties(base / "limit-and-ties")
            check_colocated_directness(base / "colocated")
            check_native_datetime_order(base / "datetime-order")
            check_wrong_sort_fails_validation(base / "wrong-sort")
            check_translated_wrong_sort_fails_validation(base / "translated-wrong-sort")
            check_multilingual_scope(base / "multilingual")
            check_unset_site(base / "unset")
            check_invalid_scope(base / "missing", "missing/_index.md", "missing/_index.md")
            check_invalid_scope(base / "empty", "empty/_index.md", "empty/_index.md")
            check_invalid_path_spelling(base / "traversal", "../content/journal/_index.md")
            check_invalid_path_spelling(base / "wrong-name", "journal/foo_index.md")
    except (AssertionError, ET.ParseError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"check-scoped-atom-feed: FAIL — {exc}", file=sys.stderr)
        return 1

    print(
        "check-scoped-atom-feed: ok "
        "(scope, direct/bundled pages, exclusion, native ordering, limit, freshness, failures, legacy feeds)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
