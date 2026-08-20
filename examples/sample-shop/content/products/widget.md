+++
title = "Widget"
description = "A purchasable sample product with sourced availability, shipping, images, and structured data."
weight = 1

[extra]
audience = "sample shop buyers"
price = "$50"
price_source = "sample fixture price list"
stripe_url = "https://buy.stripe.com/test_widget_fixture"
availability = "InStock"
availability_source = "sample fixture inventory record"
shipping_note = "Sample shipping note. Real consumers populate per-product."
shipping_source = "sample fixture fulfillment record"

[[extra.images]]
src = "img/widget-1.jpg"
alt = "First sample widget photograph"

[[extra.images]]
src = "img/widget-2.jpg"
alt = "Second sample widget photograph"
caption = "Optional figcaption beneath the second photo."
+++

A widget that costs fifty dollars in this fixture. `static/img/widget-1.jpg` and `widget-2.jpg` are real fixture JPEGs, so the product gallery partial renders two `<picture>` elements, each with the full hero/medium/small `resize_image` variant set.

The sourced catalog price triggers the Product JSON-LD include in `page.html`. The separately sourced purchasable availability permits this fixture's checkout URL, so the rendered HTML carries Organization and Product entries plus a gated Offer URL.
