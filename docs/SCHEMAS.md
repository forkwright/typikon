# Schemas

JSON Schema definitions for every content type a typikon-consuming site can author. The schemas in `schemas/` are authoritative; this document is a human-readable index. Validation happens via `bin/typikon-validate`.

## How the validator routes a file to a schema

`typikon-validate` reads `<root>/content/**/*.md` and classifies in this order — first match wins:

| Rule                                         | Schema             |
|----------------------------------------------|--------------------|
| frontmatter `template = "faq.html"`          | faq                |
| frontmatter `template = "sizing-guide.html"` | sizing-guide       |
| `_index.md` (root or section)                | section            |
| `journal/<slug>.md`                          | journal-entry      |
| `products/<slug>.md`                         | product            |
| anything else                                | page               |

Template-driven dispatch comes first so per-page overrides (FAQ on a non-FAQ section, sizing-guide for a non-product section) escape the path-based default. To add a new template-routed type, extend `TEMPLATE_SCHEMA_MAP` in `bin/typikon-validate`.

Renaming path-routed sections (`journal/` → `notes/`) requires updating the classifier. Out of scope for v1; file an issue when needed.

## page (`schemas/page.schema.json`)

Top-level pages and section children that aren't journal entries or products.

**Required:** `title`.

**Optional core:** `description`, `date`, `updated`, `path`, `template`, `weight`, `draft`.

**Optional `[extra]`:** `seo_title`, `body_class`, `og_image`, `og_type`.

**Constraints:** title ≤80 chars; description ≤200; path matches `^/[a-z0-9/_-]*/?$`; template matches `^[a-z0-9_-]+\.html$`; og_image ends in `.svg|.png|.jpg|.webp`.

**Example:**

```toml
+++
title = "Philosophy"
description = "The hand remembers. Materials carry memory. Attention is a moral act."

[extra]
og_image = "img/og-philosophy.png"
+++
```

## section (`schemas/section.schema.json`)

Section index files (`_index.md`). Includes the home page when home uses `template = "index.html"`.

**Required:** `title`.

**Optional core:** `description`, `template`, `sort_by` (date|weight|title|none), `weight`, `transparent`.

**Optional `[extra]`:** `greek` (data-greek heading attribute), `body_class`, `list_caption`, plus the home-page-specific fields:
- `home_logo`, `home_tagline`, `home_tagline_alt`
- `triad` (object with `greek: [...]`, `english: [...]`, optional `target`)
- `home_nav` (list of `{url, label, greek?}`)

**Example (journal section):**

```toml
+++
title = "Journal"
description = "Notes from the bench. Process, materials, the work of making."
sort_by = "date"
template = "journal-section.html"

[extra]
greek = "Ἡμερολόγιον"
list_caption = "Newest at top."
+++
```

## journal-entry (`schemas/journal-entry.schema.json`)

Pages under `content/journal/` (excluding `_index.md`). Stricter than page: requires `description`, `date`, and the entry-level extras so the auto-generated journal listing renders cleanly.

**Required:** `title`, `description`, `date`, `extra.components`, `extra.words`.

**Constraints:**
- description: 20–200 chars
- date: ISO 8601
- extra.components: 5–120 chars (the conceptual-tags line)
- extra.words: matches `^~?\d+( words)?$`

**Example:**

```toml
+++
title = "ἀπορία"
description = "On the green dye and the tensions it holds. Why the color that can't decide is the one I keep thinking about."
date = 2026-01-20

[extra]
components = "ἀπορία · productive uncertainty · the green"
words = "~430 words"
+++
```

## product (`schemas/product.schema.json`)

Pages under `content/products/`. Required for the purchase block to render.

**Required:** `title`, `description`, `extra.price`, `extra.stripe_url`.

**Constraints:**
- description: 30–200 chars
- price: matches `^\$?\d{1,5}(\.\d{2})?$` (e.g. `$150`, `85`, `12.50`)
- stripe_url: matches `^https://buy\.stripe\.com/[A-Za-z0-9_]+$`
- shipping_note (optional): ≤200 chars
- images (optional): array of `{src, alt, caption?}` — Zola's `resize_image` produces 400/800/1200px WebP variants automatically; the product-gallery partial renders responsive `<picture>` per item

**Example:**

```toml
+++
title = "Belt"
description = "Single-layer Hermann Oak harness leather. Solid brass. Hand saddle-stitched. $150, shipping included."

[extra]
seo_title = "Hermann Oak Leather Belt | Ardent Leatherworks"
price = "$150"
stripe_url = "https://buy.stripe.com/cNi9AT1ZHfFDeNRdsh6Ri02"

[[extra.images]]
src = "img/products/belt/01.jpg"
alt = "Brown harness leather belt laid flat with brass buckle"

[[extra.images]]
src = "img/products/belt/02.jpg"
alt = "Close-up of saddle-stitch on belt edge"
caption = "Two needles work the same thread from opposite sides."
+++
```

## faq (`schemas/faq.schema.json`)

Any page with `template = "faq.html"`. Renders a definition-list FAQ with anchored `<dt>`s and emits FAQPage JSON-LD.

**Required:** `title`, `extra.questions` (array of one or more entries).

**Constraints (per question):**
- q: 5–200 chars
- a: 5–2000 chars; supports `\n\n` for paragraph breaks (template splits on it)
- anchor (optional): `^[a-z0-9-]+$` — slugified from `q` if omitted
- additionalProperties on each question: false (strict)

**Example:**

```toml
+++
title = "Questions"
description = "Frequently asked questions."
template = "faq.html"

[[extra.questions]]
q = "What size belt do I need?"
a = "Belt size is the actual measurement around your body, not pants size. Most wear two inches over pants."
anchor = "sizing"

[[extra.questions]]
q = "Do you ship internationally?"
a = "US only currently. Reach out for case-by-case international quotes."
+++
```

## sizing-guide (`schemas/sizing-guide.schema.json`)

Any page with `template = "sizing-guide.html"`. Renders a measurement table, an optional inline-SVG diagram, and an optional decision tree.

**Required:** `title`, `extra.product_type`, `extra.size_table` (one or more rows).

**Constraints:**
- product_type: 2–40 chars
- measurement_unit (optional): `inches | centimeters | both` (default `inches`)
- size_table rows: required `size`; optional `waist`, `length`, `width`, `note` — column rendering is conditional on the first row's keys
- diagram (optional): path under static/ to an `.svg` file; loaded inline via `load_data`
- decision_tree (optional): array of strings, rendered as ordered list

**Example:**

```toml
+++
title = "Belt Sizing"
description = "How to size an Ardent harness belt."
template = "sizing-guide.html"

[extra]
product_type = "belt"
measurement_unit = "inches"
decision_tree = [
  "Find a belt you wear and like the fit of. Measure from the buckle fold to the hole you use most.",
  "If you carry concealed at the waist, add 1 inch.",
]

[[extra.size_table]]
size = "32"
waist = "32"
note = "Sized to the middle hole; first hole is 30, last is 34."

[[extra.size_table]]
size = "34"
waist = "34"
note = "Sized to the middle hole; first hole is 32, last is 36."
+++
```

> **TOML order matters.** `decision_tree = [...]` must come *before* the first `[[extra.size_table]]` block. Once an array-of-tables starts, scalar assignments belong to the *last* table — so a trailing `decision_tree` would silently land inside the final size_table row.

## Adding a new content type

1. Identify the type. If two existing types could absorb it via an optional field, use that instead.
2. Write `schemas/<type>.schema.json`, extending the page shape where possible.
3. Add a template `templates/<type>.html` (extend `page.html` when the override is content-only; replace it when the head/body shape needs to change).
4. Update `bin/typikon-validate`:
   - if path-routed: extend the path classifier
   - if template-routed: add an entry to `TEMPLATE_SCHEMA_MAP`
   - in either case: add the slug to the `load_schemas()` tuple
5. Update this document with a new section.
6. Add coverage in `examples/sample-blog/` or `examples/sample-shop/` (or a new fixture if the type doesn't fit either).
7. Run `bin/typikon-check examples/<fixture>` end-to-end.

## Schema migrations

When a schema changes incompatibly:

1. Copy `bin/typikon-migrate-template` → `bin/typikon-migrate-<from>-<to>`.
2. Replace the `migrate(frontmatter, file_path)` body with the field transformation. Idempotence rule: running it twice on the same input must produce the same output as once.
3. The script walks a consumer site root, parses frontmatter, runs `migrate()`, and writes back when the result differs.
4. The typikon PR description lists every consumer affected.
5. On merge, run the migration against each consumer in a separate consumer-side PR — that captures the rewrite as a reviewable diff.

The skeleton handles parsing, idempotence checking, basic TOML serialization, and JSONL change reporting. It uses `tomli_w` when installed and falls back to a minimal emitter otherwise — install `tomli_w` via `uv tool install tomli_w` if your migration needs round-trip fidelity for inline tables / multi-line strings.

This keeps consumers from drifting out of typikon's contract silently.
