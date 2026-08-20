# Schemas

JSON Schema definitions for every content type a typikon-consuming site can author live in `schemas/`. Validation happens via `bin/typikon-validate`.

## How the validator routes a file to a schema

`typikon-validate` reads `<root>/content/**/*.md` and classifies in this order. First match wins:

| Rule                                                    | Schema                        |
|----------------------------------------------------------|------------------------------|
| frontmatter `template = "faq.html"`                     | faq                            |
| frontmatter `template = "sizing-guide.html"`             | sizing-guide                   |
| frontmatter `template = "journal-entry.html"`            | journal-entry                  |
| frontmatter `template` matches a `schemas/registry.toml` `template` entry | that entry's consumer schema |
| `_index.md` or `_index.<lang>.md` (root or section)     | section                        |
| `journal/<slug>.md`                                     | journal-entry                  |
| `products/<slug>.md`                                    | product                         |
| path matches a `schemas/registry.toml` `path_prefix` entry | that entry's consumer schema |
| anything else                                            | page                           |

Template-driven dispatch comes first so per-page overrides (FAQ on a non-FAQ section, sizing-guide for a non-product section) escape the path-based default. To add a new template-routed type, extend `TEMPLATE_SCHEMA_MAP` in `bin/typikon-validate`.

Renaming path-routed sections (`journal/` → `notes/`) requires updating the classifier. Out of scope for v1. File an issue when needed.

**Fail-closed:** a `template` value that is neither one of typikon's own shipped templates (`KNOWN_TEMPLATES` in `bin/typikon-validate`) nor a registered `schemas/registry.toml` entry is a validation FAILURE naming the exact missing registration — it does not fall through to `page`. See [Consumer schema registry](#consumer-schema-registry) below.

## Consumer schema registry

A typikon-consuming site's own custom templates (a page type typikon does not ship — an "our approach" page, a case-study template, a domain-specific index) have no built-in schema. Before this mechanism existed, such a file fell through the table above to `page` or `section`, whose `extra` object accepted any additional field without checking its shape. A typo like `kanon_ci = "false"` was schema-valid and became truthy wherever a template did `bool(...)` on it (forkwright/typikon#60). The registry closes that: every custom template or custom-path content type gets its own strict, checked-in schema, and an *unregistered* one is a hard failure, not a silent fallback.

### Registering a custom type

1. Write `<consumer-root>/schemas/<name>.schema.json`. It must declare its own `"$id"` and compose one of typikon's open core building blocks — `page.core.schema.json` or `section.core.schema.json` — via `allOf` + `$ref`, closed with `unevaluatedProperties: false`:

   ```json
   {
     "$schema": "https://json-schema.org/draft/2020-12/schema",
     "$id": "https://<your-site>/schemas/consulting.schema.json",
     "allOf": [{ "$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json" }],
     "properties": {
       "extra": {
         "allOf": [{ "$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json#/properties/extra" }],
         "unevaluatedProperties": false,
         "properties": {
           "ardent": {
             "type": "object",
             "additionalProperties": false,
             "required": ["kanon_ci"],
             "properties": { "kanon_ci": { "type": "boolean" } }
           }
         }
       }
     },
     "unevaluatedProperties": false
   }
   ```

   **Namespace your extension.** Put every custom field under one object keyed by your own name (`extra.ardent` above, not bare `extra.kanon_ci`) so a future typikon-owned field can never collide with a consumer one.

   **WARNING:** the `$ref` targets must be the open `*.core.schema.json` files, never `page.schema.json`/`section.schema.json` themselves. Composing a schema that is *already* closed (via `unevaluatedProperties`) from inside another closed schema corrupts jsonschema 4.23's annotation collection for the whole document. This is a verified failure mode, not a style preference: every top-level field, not just the extension, gets spuriously rejected. `page.schema.json` and `section.schema.json` demonstrate the correct pattern (they compose the core exactly this way, once, standalone) — mirror them, don't reference them.

2. Add an entry to `<consumer-root>/schemas/registry.toml`:

   ```toml
   [[entry]]
   template = "consulting.html"                    # OR path_prefix = "systems/"
   schema = "schemas/consulting.schema.json"        # path relative to the consumer root
   extends = "page"                                 # "page" or "section" — which core it composes
   ```

   The registry entry requires exactly one of `template` (matched against frontmatter `template`) or `path_prefix` (matched against the content-relative path, e.g. `"systems/"` catches `content/systems/<anything>.md`). `template` wins when both a template and a path could match the same file — same precedent as `TEMPLATE_SCHEMA_MAP`.

   **`extends` must match what the matched file structurally is, not just what you intended the entry to cover.** A `_index.md` is always a Zola section. Every other file is always a Zola page — that split is Zola's, not the registry's to override. `path_prefix = "systems/"` also textually matches `content/systems/_index.md`, not just its leaf pages. If that entry's `extends = "page"`, the index file fails with a `MismatchedExtendsError` instead of silently validating against the wrong shape (missing section-only fields like `sort_by`/`page_template`/`extra.triad`). Scope the prefix past the index file, or give the section index its own `template`-keyed entry with `extends = "section"`, if you need both covered.

3. Run `typikon-validate <consumer-root>` (or `typikon-check`, which calls it). A malformed registry entry fails immediately with the specific problem, before typikon-validate checks that file's content. Malformed means: both discriminators set, neither set, `extends` naming a type with no composable core, a missing schema file, a schema missing `$id`, a duplicate discriminator, or a discriminator matching a file whose structural kind disagrees with `extends`.

A consumer with no custom templates needs no `schemas/registry.toml` at all. Its absence is not an error, and every existing consumer validates unchanged.

Only `page` and `section` have a `*.core.schema.json` building block today — those are the two shapes a real consumer has needed to extend. Extending `journal-entry`, `product`, `faq`, or `sizing-guide` the same way means splitting that schema into a `.core.schema.json` + closed wrapper first, following `schemas/page.schema.json`'s pattern exactly, then adding its slug to `COMPOSABLE_CORE_SLUGS` in `bin/typikon-validate`.

### Schema changes are migrations here too

`bin/typikon-migrate-template` operates on frontmatter regardless of which schema validates it, so a registered consumer schema changing incompatibly ships a migration the same way a typikon-owned one does — see [Schema migrations](#schema-migrations) below. No separate mechanism exists for consumer schemas.

## page (`schemas/page.schema.json`)

Top-level pages and section children that aren't journal entries or products. Built from the open `page.core.schema.json` building block, closed once here — see [Consumer schema registry](#consumer-schema-registry) if you need to extend this contract for a custom template.

**Required:** `title`.

**Optional core:** `description`, `date`, `updated`, `path`, `template`, `weight`, `draft`, `include_in_feeds`.

**Optional `[extra]`:** `seo_title`, `body_class`, `og_image`, `og_type`, `greek` (qualified alternate-language text carried by the owned H1), `audience`, `price`, `price_source`, `stripe_url`, paired `availability`/`availability_source`, and paired `shipping_note`/`shipping_source`.

`body_class` is the semantic hook for page-wide presentation. A branded
not-found page uses `body_class = "error-page"`. Its Markdown body does not
wrap or replace the H1 because `page.html` owns that heading.

**Constraints:**
- title: ≤80 chars
- description: ≤200 chars
- path: matches `^/[a-z0-9/_-]*/?$`
- template: matches `^[a-z0-9_-]+\.html$`
- og_image: ends in `.svg|.png|.jpg|.webp`

Setting any commercial fact triggers the product-shaped contract in `page.html`,
which requires `audience`, `price`, and `price_source`. Those three fields
render a catalog price and Product/Offer data without implying readiness.
`stripe_url` is optional and renders only when paired with sourced
purchasable availability. Shipping text likewise requires its own paired
source. A dedicated product page under `content/products/` should use the
`product` schema instead — these fields exist here for the rare
non-product-section page that still needs catalog or purchase output.

`include_in_feeds = false` is a top-level Zola page field, not an `[extra]`
extension. Every closed page schema accepts it (`page`,
`journal-entry`, `product`, `faq`, and `sizing-guide`) and excludes that page
from native or configured Atom feeds without hiding the rendered page.

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

Section index files (`_index.md`). Includes the home page when home uses `template = "index.html"`. Built from the open `section.core.schema.json` building block, closed once here — see [Consumer schema registry](#consumer-schema-registry) if you need to extend this contract for a custom section template.

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

Pages under `content/journal/` (excluding `_index.md`), OR any page whose effective `template` — explicit or resolved through the `page_template` cascade (see the routing table above) — is `journal-entry.html`, regardless of its path. Stricter than page: requires `description`, `date`, and the entry-level extras so the auto-generated journal listing renders cleanly.

**Required:** `title`, `description`, `date`, `extra.audience`, `extra.components`.

**Optional `[extra]`:** `words`, `words_source`, `seo_title`, `body_class`, `og_image`, `og_type`, `author`, `skip_sitemap`, `figure`, `figure_alt`, `tier`.

**Constraints:**
- description: 20–200 chars
- date: ISO 8601
- extra.audience: 3–120 chars. Rendered in the entry header, alongside `extra.components` — reader-orienting context for who the piece is for
- extra.components: 5–120 chars (the conceptual-tags line)
- extra.words: matches `^~?\d+( words)?$`. **Optional override** — `journal-entry.html`/`journal-section.html` render Zola's own `page.word_count`/`entry.word_count` by default (the rendered body's word count, excluding fenced code blocks — see `templates/journal-entry.html`), so the figure cannot drift from the body it describes. Set this only to force a custom string
- extra.words_source: 3–200 chars. **Required alongside `extra.words`, forbidden without it** (`dependentRequired`, both directions — same pattern as `product.schema.json`'s `availability`/`availability_source`). Not needed for the default derived count, which carries no separate provenance claim
- extra.og_image: ends in `.svg|.png|.jpg|.webp`
- extra.figure: ends in `.svg|.png|.jpg|.webp`. Not consumed by typikon's own stock `journal-entry.html` — a consumer shadow template renders it as furniture above the entry body (forkwright/typikon#163)
- extra.figure_alt: 5–500 chars. **Required whenever `extra.figure` is set** (enforced via `dependentRequired`, not just documented)
- extra.tier: one of `notes | research`. Not consumed by typikon's own stock `journal-section.html` — a consumer shadow template that groups its listing by tier reads it (forkwright/typikon#163)

**Example — explicit `words` override:**

```toml
+++
title = "ἀπορία"
description = "On the green dye and the tensions it holds. Why the color that can't decide is the one I keep thinking about."
date = 2026-01-20

[extra]
audience = "readers following the workbench journal"
components = "ἀπορία · productive uncertainty · the green"
words = "~430 words"
words_source = "manual count"
+++
```

**Example — derived `words`:** omitting `words`/`words_source` renders `page.word_count` instead:

```toml
+++
title = "ἀπορία"
description = "On the green dye and the tensions it holds. Why the color that can't decide is the one I keep thinking about."
date = 2026-01-20

[extra]
audience = "readers following the workbench journal"
components = "ἀπορία · productive uncertainty · the green"
+++
```

## product (`schemas/product.schema.json`)

Pages under `content/products/`. Required for the purchase block to render.

**Required:** `title`, `description`, `extra.audience`, `extra.price`, `extra.price_source`.

Those fields establish a catalog record, not sale readiness. Typikon shows the
recorded price but emits a checkout link and `Offer.url` only when
`extra.availability` is one of `InStock`, `PreOrder`, `BackOrder`, or
`LimitedAvailability` and a source records that state.

**Constraints:**
- description: 30–200 chars
- audience: 3–120 chars
- price: matches `^\$?\d{1,5}(\.\d{2})?$` (e.g. `$150`, `85`, `12.50`)
- price_source: 3–200 chars. Source for the rendered price claim
- stripe_url (optional): matches `^https://buy\.stripe\.com/[A-Za-z0-9_]+$`.
  When present, availability and its source become required, and availability
  must be one of the four purchasable states
- availability + availability_source (optional paired fields): a sourced
  Schema.org state. `OutOfStock`, `Discontinued`, or absence keeps the page
  catalog-only
- shipping_note + shipping_source (optional paired fields): ≤200-char public
  claim plus its provenance. Typikon renders no default shipping promise
- images (optional): array of `{src, alt, caption?}`. Zola's `resize_image` produces 400/800/1200px WebP variants automatically, and the product-gallery partial renders responsive `<picture>` per item

**Example:**

```toml
+++
title = "Belt"
description = "Single-layer Hermann Oak harness leather. Solid brass. Hand saddle-stitched. $150, shipping included."

[extra]
seo_title = "Hermann Oak Leather Belt | Ardent Leatherworks"
audience = "customers choosing a made-to-order belt"
price = "$150"
price_source = "Stripe price price_123"
stripe_url = "https://buy.stripe.com/cNi9AT1ZHfFDeNRdsh6Ri02"
availability = "InStock"
availability_source = "inventory record checked at publication"
shipping_note = "Ask for the current lead time."
shipping_source = "workshop fulfillment record"

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

**Required:** `title`, `extra.audience`, `extra.questions` (array of one or more entries).

**Constraints (per question):**
- audience: 3–120 chars
- q: 5–200 chars
- a: 5–2000 chars. Supports `\n\n` for paragraph breaks (template splits on it)
- anchor (optional): `^[a-z0-9-]+$`. Slugified from `q` if omitted
- additionalProperties on each question: false (strict)

**Example:**

```toml
+++
title = "Questions"
description = "Frequently asked questions."
template = "faq.html"

[extra]
audience = "customers with pre-purchase questions"

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

**Required:** `title`, `extra.audience`, `extra.measurement_source`, `extra.product_type`, `extra.size_table` (one or more rows).

**Constraints:**
- audience: 3–120 chars
- measurement_source: 3–200 chars. Source for numeric sizing claims
- product_type: 2–40 chars
- measurement_unit (optional): `inches | centimeters | both` (default `inches`)
- size_table rows: required `size`. Optional `waist`, `length`, `width`, `note` (each column's shape declared once, under `$defs`, in the schema). A column renders if ANY row in the table sets it, and every row gets a cell in that column — blank where the row itself omits the field — so header/cell association never depends on row order
- diagram (optional): path under static/ to an `.svg` file. Loaded inline via `load_data`
- decision_tree (optional): array of strings, rendered as ordered list
- duration (optional): ISO 8601 duration, hours/minutes/seconds only (e.g. `PT2M`). Requires duration_source. Emitted as HowTo `totalTime` only when both are set — never guessed

**Example:**

```toml
+++
title = "Belt Sizing"
description = "How to size an Ardent harness belt."
template = "sizing-guide.html"

[extra]
audience = "customers measuring for belt sizing"
product_type = "belt"
measurement_unit = "inches"
measurement_source = "bench pattern block 2026-01"
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

> **TOML order matters.** `decision_tree = [...]` must come *before* the first `[[extra.size_table]]` block. Once an array-of-tables starts, scalar assignments belong to the *last* table, so a trailing `decision_tree` would silently land inside the final size_table row.

## Adding a new content type

This section is for a type shared by ≥2 consumers, landing in typikon itself (AGENTIC.md's "two consumers wanting the same thing → typikon" rule). A single consumer's own custom template belongs in [Consumer schema registry](#consumer-schema-registry) instead — it needs no typikon PR.

1. Identify the type. If two existing types could absorb it via an optional field, use that instead.
2. Write `schemas/<type>.schema.json`, extending the page shape where possible.
3. Add a template `templates/<type>.html` — extend `page.html` when the override changes content only, replace it when the head/body shape needs to change.
4. Update `bin/typikon-validate`:
   - if path-routed: extend the path classifier
   - if template-routed: add an entry to `TEMPLATE_SCHEMA_MAP`
   - in either case: add the slug to the `load_schemas()` tuple
5. Update this document with a new section.
6. Add coverage in `examples/sample-blog/` or `examples/sample-shop/` (or a new fixture if the type doesn't fit either).
7. Run `bin/typikon-check examples/<fixture>` end-to-end.

## Schema migrations

For incompatible schema changes where a deterministic transformation preserves truth:

1. Copy `bin/typikon-migrate-template` → `bin/typikon-migrate-<from>-<to>`.
2. Replace the `migrate(frontmatter, file_path)` body with the field transformation. Idempotence rule: running it twice on the same input must produce the same output as once.
3. The script walks a consumer site root, parses frontmatter, runs `migrate()`, and writes back when the result differs.
4. The typikon PR description lists every consumer affected.
5. On merge, run the migration against each consumer in a separate consumer-side PR. That captures the rewrite as a reviewable diff.

A newly required provenance value is the exception. A migration may automate
safe removal of a now-gated claim, but it cannot synthesize the source that
makes the claim true. The Typikon PR names every blocked consumer. Each one
authors the source or intentionally removes the gated fact in a separate PR.

The skeleton handles parsing, idempotence checking, basic TOML serialization, and JSONL change reporting. It uses `tomli_w` when installed and falls back to a minimal emitter otherwise. Install `tomli_w` via `uv tool install tomli_w` if your migration needs round-trip fidelity for inline tables or multi-line strings.

This keeps consumers from drifting out of typikon's contract silently.
