+++
title = "Widget"
description = "A sample product. Exercises product.schema.json's required fields (price, stripe_url) plus optional images, shipping_note, og_image."
weight = 1

[extra]
audience = "sample shop buyers"
price = "$50"
price_source = "sample fixture price list"
stripe_url = "https://buy.stripe.com/test_widget_fixture"
shipping_note = "Sample shipping note. Real consumers populate per-product."

[[extra.images]]
src = "img/widget-1.jpg"
alt = "First sample widget photograph"

[[extra.images]]
src = "img/widget-2.jpg"
alt = "Second sample widget photograph"
caption = "Optional figcaption beneath the second photo."
+++

A widget that costs fifty dollars in this fixture. `static/img/widget-1.jpg` and `widget-2.jpg` are real fixture JPEGs, so the product gallery partial renders two `<picture>` elements, each with the full hero/medium/small `resize_image` variant set.

The price + stripe_url combination triggers the Product JSON-LD include in `page.html`, so the rendered HTML carries `application/ld+json` schema entries for Organization (always-on) and Product (conditional).
