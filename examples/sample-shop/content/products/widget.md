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

# Widget

A widget that costs fifty dollars in this fixture. The product gallery partial would render two `<picture>` elements for the images above — but the source files are placeholders, so the fixture skips the build of the responsive variants by leaving `static/img/widget-*.jpg` absent.

The price + stripe_url combination triggers the Product JSON-LD include in `page.html`, so the rendered HTML carries `application/ld+json` schema entries for Organization (always-on) and Product (conditional).
