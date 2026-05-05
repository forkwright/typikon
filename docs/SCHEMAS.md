# Schemas

JSON Schema definitions for every content type a typikon-consuming site can author. The schemas in `schemas/` are authoritative; this document is a human-readable index. Validation happens via `bin/typikon-validate`.

## How the validator routes a file to a schema

`typikon-validate` reads `<root>/content/**/*.md` and classifies by path:

| Path under `content/`           | Schema             |
|---------------------------------|--------------------|
| `_index.md`                     | section            |
| `<section>/_index.md`           | section            |
| `journal/<slug>.md`             | journal-entry      |
| `products/<slug>.md`            | product            |
| anything else                   | page               |

Renaming sections (`journal/` → `notes/`) requires updating the validator's classifier. Out of scope for v1; file an issue when needed.

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

**Example:**

```toml
+++
title = "Belt"
description = "Single-layer Hermann Oak harness leather. Solid brass. Hand saddle-stitched. $150, shipping included."
seoTitle = "Hermann Oak Leather Belt | Ardent Leatherworks"

[extra]
seo_title = "Hermann Oak Leather Belt | Ardent Leatherworks"
price = "$150"
stripe_url = "https://buy.stripe.com/cNi9AT1ZHfFDeNRdsh6Ri02"
+++
```

## Adding a new content type

1. Identify the type. If two existing types could absorb it via an optional field, use that instead.
2. Write `schemas/<type>.schema.json`, extending the page shape where possible.
3. Add a scaffold under `scaffolds/new-<type>.md.tmpl` (Phase 5+).
4. Update `bin/typikon-validate` to classify by path.
5. Update this document with a new section.
6. Add a fixture in `examples/` exercising the type.
7. Run `bin/typikon-check examples/<fixture>` end-to-end.

## Schema migrations

When a schema changes incompatibly:

1. Ship a migration script in `bin/typikon-migrate-<from>-<to>` (Rust-or-bash, idempotent).
2. The migration walks a consumer site root and rewrites old frontmatter to the new shape.
3. The PR description lists every consumer affected.
4. On merge, run the migration against each consumer; open consumer-side PRs to capture the diff.

This keeps consumers from drifting out of typikon's contract silently.
