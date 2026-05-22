+++
title = "Gadget"
description = "A second sample product. Pairs with widget so the products section list renders multi-entry behavior."
weight = 2

[extra]
audience = "sample shop buyers"
price = "85"
price_source = "sample fixture price list"
stripe_url = "https://buy.stripe.com/test_gadget_fixture"
+++

# Gadget

A gadget that costs eighty-five dollars (no leading dollar sign — the price-pattern accepts both forms). The schema lets a consumer write either `"$85"` or `"85"`; both validate. The Product JSON-LD strips the leading `$` for the numeric `price` field.
