#!/usr/bin/env python3
"""Exercise the Tera 2 migration paths that static syntax checks cannot prove.

Zola 0.23 moved Typikon from Tera 1 macros to globally registered, isolated-
context Tera 2 components. ``check-tera2-contract.py`` rejects the old dialect,
but only a real render can establish the migrated runtime semantics:

- missing ``[extra.author]`` falls back to the site title/base URL in Atom and
  to the site title in Article JSON-LD;
- Atom timestamps use Jiff-compatible RFC 3339 output and an absent page
  ``updated`` value falls back to its publication date;
- a component receives no ambient ``lang``, so the breadcrumb component must
  carry the translated page's language into every ``get_section`` lookup;
- the array-spread replacement for Tera 1's ``concat`` retains ``rel="me"``
  links in Organization ``sameAs``.

The public GitHub gate installs the pinned Zola binary before auto-discovering
this no-argument fixture. The fixture builds only an isolated temporary site;
it never writes generated output into the checkout.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


THEME_ROOT = Path(__file__).resolve().parent.parent
ZOLA = shutil.which("zola")

CONFIG_TOML = '''title = "Renderer Fixture"
description = "Default-language renderer fixture."
base_url = "https://renderer-fixture.example.com"
default_language = "en"
output_dir = "public"
theme = "typikon"
generate_feeds = true
feed_filenames = ["atom.xml"]

[languages.fr]
title = "Matrice française"
description = "Fixture de rendu en français."
generate_feeds = true
feed_filenames = ["atom.xml"]

[extra]
brand_name = "Renderer Fixture"
brand_greek = "Δοκιμή"
logo_path = "img/logo.svg"
theme_color = "#FBF7EC"
og_locale = "en_US"
founding_date = "2026"
footer_links = [
  { url = "https://profile.example.com/first", label = "First profile", rel = "me" },
  { url = "/contact/", label = "Contact" },
  { url = "https://profile.example.com/second", label = "Second profile", rel = "me" },
]
'''

ROOT_EN = '''+++
title = "English Home"
description = "Default-language home."
template = "section.html"
+++
'''

ROOT_FR = '''+++
title = "Accueil français"
description = "Accueil traduit."
template = "section.html"
+++
'''

SECTION_EN = '''+++
title = "English Journal"
description = "Default-language journal."
sort_by = "date"
template = "journal-section.html"
page_template = "journal-entry.html"
+++
'''

SECTION_FR = '''+++
title = "Journal français"
description = "Journal traduit."
sort_by = "date"
template = "journal-section.html"
page_template = "journal-entry.html"
+++
'''

ENTRY_EN = '''+++
title = "English Entry"
description = "Default-language entry."
date = 2026-08-19

[extra]
audience = "renderer fixture readers"
components = "Tera 2 · defaults · breadcrumbs"
+++

Default-language body.
'''

ENTRY_FR = '''+++
title = "Entrée française"
description = "Entrée traduite."
date = 2026-08-19

[extra]
audience = "lecteurs de la fixture"
components = "Tera 2 · langue · fil d’Ariane"
+++

Corps traduit.
'''


class JsonLdParser(HTMLParser):
    """Collect JSON values from ``application/ld+json`` script elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._chunks: list[str] | None = None
        self.payloads: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._chunks is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._chunks is not None:
            self.payloads.append("".join(self._chunks))
            self._chunks = None


def copy_theme(dest: Path) -> None:
    for item in ("templates", "static", "sass", "theme.toml"):
        source = THEME_ROOT / item
        if not source.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, dest / item)
        else:
            shutil.copy2(source, dest / item)


def make_site(root: Path, theme_dir: Path) -> Path:
    site = root / "site"
    journal = site / "content" / "journal"
    journal.mkdir(parents=True)
    (site / "themes").mkdir()
    (site / "themes" / "typikon").symlink_to(theme_dir, target_is_directory=True)

    files = {
        site / "config.toml": CONFIG_TOML,
        site / "content" / "_index.md": ROOT_EN,
        site / "content" / "_index.fr.md": ROOT_FR,
        journal / "_index.md": SECTION_EN,
        journal / "_index.fr.md": SECTION_FR,
        journal / "entry.md": ENTRY_EN,
        journal / "entry.fr.md": ENTRY_FR,
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    return site


def json_ld_objects(path: Path) -> list[dict[str, Any]]:
    parser = JsonLdParser()
    parser.feed(path.read_text(encoding="utf-8"))
    values = [json.loads(payload) for payload in parser.payloads]
    return [value for value in values if isinstance(value, dict)]


def object_of_type(objects: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [value for value in objects if value.get("@type") == kind]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {kind} JSON-LD object, found {len(matches)}")
    return matches[0]


def check_atom_author(public: Path, failures: list[str]) -> None:
    atom = ET.parse(public / "atom.xml").getroot()
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    name = atom.findtext("atom:author/atom:name", namespaces=namespace)
    uri = atom.findtext("atom:author/atom:uri", namespaces=namespace)
    if name != "Renderer Fixture":
        failures.append(f"author-less Atom name: expected site title, got {name!r}")
    if uri != "https://renderer-fixture.example.com":
        failures.append(f"author-less Atom URI: expected base URL, got {uri!r}")
    expected_timestamp = "2026-08-19T00:00:00+00:00"
    feed_updated = atom.findtext("atom:updated", namespaces=namespace)
    if feed_updated != expected_timestamp:
        failures.append(
            "Atom feed updated: expected Jiff-compatible RFC 3339 publication fallback "
            f"{expected_timestamp!r}, got {feed_updated!r}"
        )
    entries = atom.findall("atom:entry", namespace)
    if len(entries) != 1:
        failures.append(f"author-less Atom entries: expected exactly 1, got {len(entries)}")
    else:
        entry_author = entries[0].findtext("atom:author/atom:name", namespaces=namespace)
        if entry_author != "Renderer Fixture":
            failures.append(
                f"author-less Atom entry name: expected site title, got {entry_author!r}"
            )
        published = entries[0].findtext("atom:published", namespaces=namespace)
        updated = entries[0].findtext("atom:updated", namespaces=namespace)
        if published != expected_timestamp or updated != expected_timestamp:
            failures.append(
                "Atom entry timestamps: expected publication and null-updated fallback to "
                f"{expected_timestamp!r}, got published={published!r}, updated={updated!r}"
            )


def check_structured_data(public: Path, failures: list[str]) -> None:
    english = json_ld_objects(public / "journal" / "entry" / "index.html")
    article = object_of_type(english, "Article")
    article_author = article.get("author", {}).get("name")
    if article_author != "Renderer Fixture":
        failures.append(
            f"author-less Article name: expected site title, got {article_author!r}"
        )

    organization = object_of_type(english, "Organization")
    expected_same_as = [
        "https://profile.example.com/first",
        "https://profile.example.com/second",
    ]
    if organization.get("sameAs") != expected_same_as:
        failures.append(
            "Organization sameAs: expected only the two ordered rel=me URLs after Tera 2 array "
            f"spread, got {organization.get('sameAs')!r}"
        )

    french = json_ld_objects(public / "fr" / "journal" / "entry" / "index.html")
    breadcrumb = object_of_type(french, "BreadcrumbList")
    breadcrumb_items = [
        (item.get("position"), item.get("name"), item.get("item"))
        for item in breadcrumb.get("itemListElement", [])
    ]
    expected_items = [
        (1, "Matrice française", "https://renderer-fixture.example.com"),
        (2, "Accueil français", "https://renderer-fixture.example.com/fr/"),
        (3, "Journal français", "https://renderer-fixture.example.com/fr/journal/"),
        (4, "Entrée française", "https://renderer-fixture.example.com/fr/journal/entry/"),
    ]
    if breadcrumb_items != expected_items:
        failures.append(
            "translated breadcrumb: expected ordered French ancestors and canonical URLs "
            f"{expected_items!r}, got {breadcrumb_items!r}"
        )


def main() -> int:
    if ZOLA is None:
        print(
            "check-tera2-rendering: FAIL — zola not on PATH "
            "(see gate-attestation.yml's install step)",
            file=sys.stderr,
        )
        return 1

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="typikon-tera2-rendering-") as tmp:
        root = Path(tmp)
        theme = root / "theme"
        copy_theme(theme)
        site = make_site(root, theme)
        try:
            version = subprocess.run(
                [ZOLA, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            version_text = f"{version.stdout}\n{version.stderr}".strip()
            if version.returncode != 0 or version_text != "zola 0.23.3":
                failures.append(
                    "renderer authority: expected zola 0.23.3, got "
                    f"exit {version.returncode} and output {version_text!r}"
                )

            result = subprocess.run(
                [ZOLA, "build"],
                cwd=site,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if result.returncode != 0:
                failures.append(
                    f"pinned Zola/Tera renderer exited {result.returncode}:\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            else:
                public = site / "public"
                try:
                    check_atom_author(public, failures)
                    check_structured_data(public, failures)
                except (
                    ET.ParseError,
                    json.JSONDecodeError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as exc:
                    failures.append(f"rendered-output inspection failed: {exc}")
        except subprocess.TimeoutExpired as exc:
            failures.append(f"renderer command exceeded its local timeout: {exc.cmd!r}")

    if failures:
        print("check-tera2-rendering: FAIL", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        "check-tera2-rendering: ok "
        "(author fallbacks, translated breadcrumbs, and sameAs spread)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
