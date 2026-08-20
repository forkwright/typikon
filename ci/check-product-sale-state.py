#!/usr/bin/env python3
"""Verify rendered checkout gating and the paired product fact schema."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class ProductParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.buy_hrefs: list[str] = []
        self.visible_chunks: list[str] = []
        self._script_chunks: list[str] | None = None
        self.json_payloads: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "a" and "buy-btn" in classes and values.get("href"):
            self.buy_hrefs.append(values["href"] or "")
        if tag == "script" and values.get("type") == "application/ld+json":
            self._script_chunks = []

    def handle_data(self, data: str) -> None:
        if self._script_chunks is not None:
            self._script_chunks.append(data)
        else:
            self.visible_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script_chunks is not None:
            self.json_payloads.append("".join(self._script_chunks))
            self._script_chunks = None


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def product_object(parser: ProductParser, slug: str, failures: list[str]) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    for payload in parser.json_payloads:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            fail("{}: malformed JSON-LD: {}".format(slug, exc), failures)
            continue
        if isinstance(value, dict) and value.get("@type") == "Product":
            objects.append(value)
    if len(objects) != 1:
        fail("{}: expected exactly one Product JSON-LD object, found {}".format(slug, len(objects)), failures)
        return {}
    return objects[0]


def inspect_page(
    public: Path,
    slug: str,
    *,
    title: str,
    price: str,
    checkout: str,
    availability: str | None,
    shipping: str | None,
    purchasable: bool,
    failures: list[str],
) -> None:
    path = public / "products" / slug / "index.html"
    if not path.is_file():
        fail("{}: rendered page is missing".format(path), failures)
        return
    source = path.read_text(encoding="utf-8")
    parser = ProductParser()
    parser.feed(source)
    visible = " ".join(" ".join(parser.visible_chunks).split())
    if title not in visible or price not in visible:
        fail("{}: catalog title/price are not both visible".format(slug), failures)

    product = product_object(parser, slug, failures)
    offer = product.get("offers", {}) if isinstance(product, dict) else {}
    expected_availability = None if availability is None else "https://schema.org/" + availability
    if offer.get("availability") != expected_availability:
        fail(
            "{}: expected Offer.availability {!r}, got {!r}".format(
                slug, expected_availability, offer.get("availability")
            ),
            failures,
        )

    if purchasable:
        if parser.buy_hrefs != [checkout]:
            fail("{}: expected one checkout link, got {!r}".format(slug, parser.buy_hrefs), failures)
        if offer.get("url") != checkout:
            fail("{}: Offer.url does not match the verified checkout".format(slug), failures)
    else:
        if parser.buy_hrefs:
            fail("{}: non-purchasable page emitted checkout links".format(slug), failures)
        if checkout in source:
            fail("{}: stored checkout URL leaked into rendered HTML/JSON-LD".format(slug), failures)
        if "url" in offer:
            fail("{}: non-purchasable Offer emitted a URL".format(slug), failures)

    if shipping is None:
        if "Ships within one week" in visible or "product-shipping" in source:
            fail("{}: page invented or emitted an unsourced shipping claim".format(slug), failures)
    elif shipping not in visible:
        fail("{}: sourced shipping claim is not visible".format(slug), failures)
    if availability is not None:
        labels = {
            "InStock": "In stock",
            "OutOfStock": "Out of stock",
            "PreOrder": "Pre-order",
            "BackOrder": "Back order",
            "LimitedAvailability": "Limited availability",
            "Discontinued": "Discontinued",
        }
        if labels[availability] not in visible:
            fail("{}: sourced availability label is not visible".format(slug), failures)


def check_schema(root: Path, failures: list[str]) -> None:
    schema = json.loads((root / "schemas" / "product.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    valid = {
        "title": "Fixture",
        "description": "A sufficiently long product description for schema validation.",
        "extra": {
            "audience": "fixture buyers",
            "price": "$50",
            "price_source": "fixture price source",
        },
    }
    if not validator.is_valid(valid):
        fail("product schema rejected catalog-only frontmatter", failures)

    invalid_pairs = [
        ("availability", "InStock"),
        ("availability_source", "fixture inventory source"),
        ("shipping_note", "Ships after the recorded check."),
        ("shipping_source", "fixture fulfillment source"),
    ]
    for field, value in invalid_pairs:
        candidate = deepcopy(valid)
        candidate["extra"][field] = value
        if validator.is_valid(candidate):
            fail("product schema accepted unpaired {}".format(field), failures)

    paired = deepcopy(valid)
    paired["extra"].update(
        {
            "availability": "InStock",
            "availability_source": "fixture inventory source",
            "shipping_note": "Ships after the recorded check.",
            "shipping_source": "fixture fulfillment source",
        }
    )
    if not validator.is_valid(paired):
        fail("product schema rejected fully paired sale-state facts", failures)

    checkout = deepcopy(paired)
    checkout["extra"]["stripe_url"] = "https://buy.stripe.com/test_fixture"
    if not validator.is_valid(checkout):
        fail("product schema rejected sourced purchasable checkout", failures)

    unsafe_checkout = deepcopy(valid)
    unsafe_checkout["extra"]["stripe_url"] = "https://buy.stripe.com/test_fixture"
    if validator.is_valid(unsafe_checkout):
        fail("product schema accepted checkout without sourced availability", failures)
    negative_checkout = deepcopy(unsafe_checkout)
    negative_checkout["extra"].update(
        {
            "availability": "OutOfStock",
            "availability_source": "fixture inventory source",
        }
    )
    if validator.is_valid(negative_checkout):
        fail("product schema accepted checkout for non-purchasable availability", failures)

    page_core = json.loads((root / "schemas" / "page.core.schema.json").read_text(encoding="utf-8"))
    page_validator = Draft202012Validator(page_core)
    page_base = {"title": "Catalog", "extra": deepcopy(valid["extra"])}
    if not page_validator.is_valid(page_base):
        fail("page core rejected catalog-only product facts", failures)
    for field, value in invalid_pairs:
        candidate = deepcopy(page_base)
        candidate["extra"][field] = value
        if page_validator.is_valid(candidate):
            fail("page core accepted unpaired {}".format(field), failures)
    page_checkout = deepcopy(page_base)
    page_checkout["extra"]["stripe_url"] = "https://buy.stripe.com/test_fixture"
    if page_validator.is_valid(page_checkout):
        fail("page core accepted checkout without sourced availability", failures)
    page_purchasable = deepcopy(page_base)
    page_purchasable["extra"].update(
        {
            "stripe_url": "https://buy.stripe.com/test_fixture",
            "availability": "InStock",
            "availability_source": "fixture inventory source",
        }
    )
    if not page_validator.is_valid(page_purchasable):
        fail("page core rejected sourced purchasable checkout", failures)
    page_negative = deepcopy(page_purchasable)
    page_negative["extra"]["availability"] = "OutOfStock"
    if page_validator.is_valid(page_negative):
        fail("page core accepted checkout for non-purchasable availability", failures)


def check_invalid_state_render(root: Path, failures: list[str]) -> None:
    zola = shutil.which("zola")
    if zola is None:
        fail("isolated invalid-state render: zola is not on PATH", failures)
        return
    with tempfile.TemporaryDirectory(prefix="typikon-product-state-") as tmp:
        site = Path(tmp) / "site"
        products = site / "content" / "products"
        products.mkdir(parents=True)
        (site / "themes").mkdir()
        (site / "themes" / "typikon").symlink_to(root, target_is_directory=True)
        (site / "config.toml").write_text(
            '''title = "Sale State Fixture"
description = "Rendered fail-closed product fixture."
base_url = "https://sale-state.example.com"
theme = "typikon"

[extra]
brand_name = "Sale State Fixture"
brand_greek = "Δοκιμή"
logo_path = "img/logo.svg"
theme_color = "#FBF7EC"
og_locale = "en_US"
founding_date = "2026"
''',
            encoding="utf-8",
        )
        (site / "content" / "_index.md").write_text(
            '+++\ntitle = "Home"\ntemplate = "section.html"\n+++\n', encoding="utf-8"
        )
        (products / "_index.md").write_text(
            '+++\ntitle = "Products"\n+++\n', encoding="utf-8"
        )
        fixtures = {
            "missing-source": '''+++
title = "Missing Source"
description = "A deliberately invalid render fixture with no availability source."

[extra]
audience = "fixture buyers"
price = "$70"
price_source = "fixture price source"
stripe_url = "https://buy.stripe.com/test_missing_source"
availability = "InStock"
+++

Catalog body.
''',
            "missing-state": '''+++
title = "Missing State"
description = "A deliberately invalid render fixture with a stored URL but no state."

[extra]
audience = "fixture buyers"
price = "$71"
price_source = "fixture price source"
stripe_url = "https://buy.stripe.com/test_missing_state"
+++

Catalog body.
''',
            "out-of-stock": '''+++
title = "Out Of Stock"
description = "A deliberately invalid render fixture retaining a URL for a negative state."

[extra]
audience = "fixture buyers"
price = "$72"
price_source = "fixture price source"
stripe_url = "https://buy.stripe.com/test_out_of_stock"
availability = "OutOfStock"
availability_source = "fixture inventory source"
+++

Catalog body.
''',
            "discontinued": '''+++
title = "Discontinued"
description = "A deliberately invalid render fixture retaining a URL for a retired state."

[extra]
audience = "fixture buyers"
price = "$73"
price_source = "fixture price source"
stripe_url = "https://buy.stripe.com/test_discontinued"
availability = "Discontinued"
availability_source = "fixture inventory source"
+++

Catalog body.
''',
            "unpaired-shipping": '''+++
title = "Unpaired Shipping"
description = "A deliberately invalid render fixture with an unsourced shipping promise."

[extra]
audience = "fixture buyers"
price = "$74"
price_source = "fixture price source"
shipping_note = "Unsourced shipping promise."
+++

Catalog body.
''',
        }
        for slug, frontmatter in fixtures.items():
            (products / f"{slug}.md").write_text(frontmatter, encoding="utf-8")
        result = subprocess.run(
            [zola, "build"],
            cwd=site,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            fail(
                "isolated invalid-state render failed before inspection: {}".format(result.stderr),
                failures,
            )
            return
        cases = [
            ("missing-source", "Missing Source", "$70", "https://buy.stripe.com/test_missing_source", None),
            ("missing-state", "Missing State", "$71", "https://buy.stripe.com/test_missing_state", None),
            ("out-of-stock", "Out Of Stock", "$72", "https://buy.stripe.com/test_out_of_stock", "OutOfStock"),
            ("discontinued", "Discontinued", "$73", "https://buy.stripe.com/test_discontinued", "Discontinued"),
            ("unpaired-shipping", "Unpaired Shipping", "$74", "https://buy.stripe.com/test_absent_fixture", None),
        ]
        for slug, title, price, checkout, availability in cases:
            inspect_page(
                site / "public",
                slug,
                title=title,
                price=price,
                checkout=checkout,
                availability=availability,
                shipping=None,
                purchasable=False,
                failures=failures,
            )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: ci/check-product-sale-state.py <sample-shop-public-dir>", file=sys.stderr)
        return 2
    public = Path(sys.argv[1]).resolve()
    root = Path(__file__).resolve().parent.parent
    failures: list[str] = []
    check_schema(root, failures)
    check_invalid_state_render(root, failures)
    inspect_page(
        public,
        "widget",
        title="Widget",
        price="$50",
        checkout="https://buy.stripe.com/test_widget_fixture",
        availability="InStock",
        shipping="Sample shipping note. Real consumers populate per-product.",
        purchasable=True,
        failures=failures,
    )
    inspect_page(
        public,
        "gadget",
        title="Gadget",
        price="85",
        checkout="https://buy.stripe.com/test_gadget_fixture",
        availability="OutOfStock",
        shipping=None,
        purchasable=False,
        failures=failures,
    )
    inspect_page(
        public,
        "catalog",
        title="Catalog Record",
        price="$65",
        checkout="https://buy.stripe.com/test_catalog_fixture",
        availability=None,
        shipping=None,
        purchasable=False,
        failures=failures,
    )
    inspect_page(
        public,
        "retired",
        title="Retired Product",
        price="$40",
        checkout="https://buy.stripe.com/test_retired_fixture",
        availability="Discontinued",
        shipping=None,
        purchasable=False,
        failures=failures,
    )
    if failures:
        print("check-product-sale-state: FAIL", file=sys.stderr)
        for message in failures:
            print("  - " + message, file=sys.stderr)
        return 1
    print("check-product-sale-state: ok (schema pairs, catalog, checkout, shipping, Offer URL)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
