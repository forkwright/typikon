+++
# NOTE: comment-only touch, verifying forkwright/typikon#122's fix empirically --
# a diff confined to this file must run full-gate-build. Parsed value unchanged.
title = "Sizing"
description = "Sample sizing guide. Exercises required audience, measurement source, product type, and size table metadata."
template = "sizing-guide.html"

[extra]
audience = "sample shop buyers"
product_type = "widget"
measurement_unit = "inches"
measurement_source = "sample fixture measurement table"
decision_tree = [
  "Measure the space where the widget will sit.",
  "Choose the smallest widget size that is equal to or larger than that measurement.",
]

[[extra.size_table]]
size = "Small"
width = "4"
note = "Fits compact fixture spaces."

[[extra.size_table]]
size = "Large"
width = "8"
note = "Fits standard fixture spaces."
+++

This sample sizing guide proves the sizing-guide schema and template have a concrete fixture with all required metadata populated, and — carrying no `duration` — that an unsourced guide emits no HowTo `totalTime` at all. See `sizing-timed.md` for the sourced case.
