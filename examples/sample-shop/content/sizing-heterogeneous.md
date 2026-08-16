+++
title = "Heterogeneous Sizing"
description = "Sample sizing guide whose rows carry non-overlapping optional columns, proving header/cell association survives row order (forkwright/typikon#57)."
template = "sizing-guide.html"

[extra]
audience = "sample shop buyers exercising heterogeneous size_table rows"
product_type = "widget"
measurement_unit = "inches"
measurement_source = "sample fixture measurement table"

[[extra.size_table]]
size = "S"
waist = "30"

[[extra.size_table]]
size = "M"
note = "custom"
+++

This sample sizing guide's two rows set disjoint optional columns — row "S"
sets only `waist`, row "M" sets only `note` — the exact shape
forkwright/typikon#57 was filed against. Deriving headers from row 0 alone
would produce a single "Waist" column and let row "M"'s `note` value render
under it; the fix unions column presence across every row instead, so both
"Waist" and "Note" columns exist and each row shows a blank cell in the
column it does not set. `ci/smoke/shared.spec.ts`'s sizing-table block
asserts exactly this against the rendered page.
