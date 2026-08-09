+++
title = "Timed Sizing"
description = "Sample sizing guide with a sourced duration, proving totalTime reproduces the exact supplied value."
template = "sizing-guide.html"

[extra]
audience = "sample shop buyers timing the decision tree"
product_type = "widget"
measurement_unit = "inches"
measurement_source = "sample fixture measurement table"
duration = "PT2M"
duration_source = "operator timed the two-step decision tree during fixture authoring"
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

This sample sizing guide proves a sourced `duration` is reproduced exactly as HowTo `totalTime`, complementing `sizing.md`'s proof that an unsourced guide emits no `totalTime` at all.
