# Agentic operation

Every agent working on typikon itself or on any consumer site follows the contract below. AI agents operate typikon. Human edits are exceptions.

If you are a human reading this: every constraint here is also good for humans, but the bias is toward machine ergonomics. When in doubt, optimize for the agent.

## The contract

### 1. Read the schema before you write content

Every content type has a JSON Schema in `schemas/`:

| Type | Schema | Used by |
|------|--------|---------|
| Page | `schemas/page.schema.json` | Top-level pages (about, contact, philosophy) |
| Section | `schemas/section.schema.json` | Section index files (`_index.md`) |
| Journal entry | `schemas/journal-entry.schema.json` | Pages under a journal section |
| Product | `schemas/product.schema.json` | Pages under a products section |
| FAQ | `schemas/faq.schema.json` | Any page with `template = "faq.html"` |
| Sizing guide | `schemas/sizing-guide.schema.json` | Any page with `template = "sizing-guide.html"` |

The schema defines: required fields, optional fields, value types, value patterns, length limits. Do not invent fields. If a frontmatter field is not in the schema, do not write it — the schema closes every one of the six, so an unrecognized field fails validation instead of silently passing.

A consumer site's own custom template (not one of the six above) needs its own schema, registered in `schemas/registry.toml` — see `docs/SCHEMAS.md#consumer-schema-registry`. An unregistered custom template fails validation naming the missing registration. It does not fall back to `page`'s shape.

### 2. Use the scaffolder

```bash
bin/typikon-init <type> <destination-path>
```

The scaffolder writes valid frontmatter from the start. Hand-writing frontmatter is a defect: it produces files that look correct but fail validation in subtle ways.

If you find yourself wanting to hand-write frontmatter, file an issue requesting a new scaffold type instead.

### 3. Validate before you push

```bash
bin/typikon-validate <consumer-site-root>
```

Runs every content file in the consumer site against its appropriate schema. Output is JSONL on stderr. Exit 0 = all valid, exit 1 = any failure.

JSONL line shape:

```json
{"file": "content/products/belt.md", "pointer": "/extra/price", "error": "expected string, got null"}
```

Run this in your authoring loop. Do not push without it passing.

### 4. Run the gate locally

```bash
bin/typikon-check <consumer-site-root>
```

Runs every stage below, in order. A stage failing does not stop the ones after it (each records its own verdict — see `bin/typikon-check`'s Exit codes for how it decides the run's overall result):

1. `typikon-validate` (frontmatter against JSON Schema)
2. `zola check` (internal links + assets)
3. `zola build` (no warnings tolerated, output `public/`)
4. `zola build --base-url http://127.0.0.1:8080 --output-dir public-local` (the copy browser gates serve — `public/` retains the real `base_url` for deploy)
5. `csp-enforce.sh` (parses `public/` HTML for inline `<script>`, `<style>`, `on*=` handlers)
6. `asset-provenance.sh` (parses `public/` PNG/JPEG/SVG containers for an embedded C2PA manifest undeclared in `config.toml`'s `extra.c2pa_declared_assets`)
7. `lychee public/ --config ci/lychee.toml` (external links)
8. `pa11y-ci --config ci/pa11y.config.js` (WCAG 2.1 AA, against `public-local/`)
9. `playwright test` (per-route smoke assertions, against `public-local/`)

Output is JSONL summarizing each gate. If anything fails, fix it. Do not push to bypass.

### 5. No inline scripts, styles, or event handlers

Anywhere. Not in templates, not in markdown content, not in scaffolded snippets.

- `<script>foo()</script>` → extract to `static/js/<name>.js`, reference from `<script src="/js/<name>.js" defer>`.
- `<style>...</style>` → extract to `static/css/<name>.css`, reference from `<link rel="stylesheet" href="/css/<name>.css">`.
- `<button onclick="...">` → attach in JS via `addEventListener` after `DOMContentLoaded`.

The CSP-enforce gate fails the build if any of these appear in the rendered output.

### 6. Schemas and primitives evolve in typikon, not in consumers

When two consumer sites disagree on a primitive (a field, a layout, a color token), the primitive is not yet a primitive. Either:

- Parameterize the schema (add an optional field, document its semantics, add a default in the theme), or
- Split the primitive into two (give them different names, document when each applies).

Do not fork the theme into a consumer to satisfy a one-off need. Forks become permanent and the design family fragments.

### 7. Schema changes are migrations, where a migration is possible

When a typikon PR renames, removes, or changes a schema field incompatibly, it also ships a migration script in `bin/typikon-migrate-<from>-<to>`. The script:

- Runs against a consumer site root
- Reads every content file, applies the transformation, writes back
- Is idempotent (re-running is a no-op if already migrated) <!-- kanon:ignore WRITING/passive-voice -- idempotent is a predicate adjective, not a participle, with no actor to name — filed kanon (forge) issue #10074 -->
- Exits 0 on success with summary of files changed

The PR description must list every consumer affected and link the migration runs.

**Adding a required field is the exception, and it is deliberate.** A rename or a
removal is a transformation of content that already exists, so a script can perform it.
A new required field asks for a value the consumer has never recorded, and no
script can supply it.

That matters most for the provenance fields — `words_source`, `price_source`,
`measurement_source`. Each states where a rendered number came from. A migration that
filled them with a placeholder would be writing a false provenance claim into content,
which is the exact failure the fields exist to prevent. A schema that guarantees
"this price is traceable" is worth less than nothing if a generated string can satisfy
the guarantee.

So typikon ships no migration for added required fields. The consequence is real and
falls on the consumer: it cannot bump the theme submodule until it has authored the
new fields for every affected content file. Budget that as content work, not as a
version bump — `themes/typikon/bin/typikon-validate .` names each file and pointer, so
you can enumerate the work before starting it.

The PR adding a required field must say so in its description, and list the consumers
it blocks.

### 8. Check the push authority before pushing

`origin` is GitHub (`forkwright/typikon`). This repo configures no forge remote and has no mirror step, so a push to `origin` is a push to GitHub. Check with `git remote -v` instead of assuming either shape.

Whether the fleet returns to a forge-primary split is an open question that forkwright/kanon#3045 owns.

### 9. Photography goes in `page.extra.images`

Drop source files in the consumer's `static/img/<section>/<slug>/<n>.{jpg,jpeg,png,webp,tiff,heic}` and reference them in frontmatter:

```toml
[[extra.images]]
src = "img/products/belt/01.jpg"
alt = "Brown harness leather belt laid flat with brass buckle"

[[extra.images]]
src = "img/products/belt/02.jpg"
alt = "Close-up of saddle stitch on belt edge"
caption = "Two needles work the same thread from opposite sides."
```

The product-gallery partial (auto-included by page.html) renders a responsive `<picture>` per image — Zola's `resize_image()` generates 400 / 800 / 1200 px WebP variants automatically. First image is the hero (eager-loaded). The rest lazy-load.

When real photos arrive, drop the placeholder `<div class="product-images">…image-placeholder-list…</div>` block from the markdown body — the gallery takes its visual slot.

## The agent loop

For a routine content edit:

```
1. typikon-init <type> <path>           # produces valid scaffold
2. edit the markdown body              # frontmatter is already correct
3. typikon-validate <site-root>        # exits 0 = good
4. typikon-check <site-root>           # exits 0 = ready to push
5. git commit + git push origin main
6. CI re-runs the gate; deploys on green
```

For a structural change (template, schema, primitive):

```
1. work in typikon repo, branch from main
2. update template / schema / primitive
3. update consumer fixture in examples/
4. run bin/typikon-check examples/<fixture>     # full gate against fixture
5. if schema changed incompatibly, write bin/typikon-migrate-<from>-<to>
6. open PR, list affected consumers in description
7. on merge: run migration against each consumer, open consumer-side PRs
```

## Starting a new typikon-consuming site

When a new fleet site enters the family, do not fork or copy. Consume the substrate.

### 1. Scaffold

```bash
typikon-init <site-slug> ~/dev/<site-slug>
```

The scaffolder writes `config.toml`, the `themes/typikon` submodule, `_headers`, `_redirects`, the GitHub Actions workflow, a starter `content/_index.md`, and the operator brief at `CLAUDE.md`. The first commit lands automatically. Once the forge repo exists, the operator pushes (`kanon forge init forkwright/<site-slug>`).

### 2. Brand identity (consumer-side, not theme-side)

The substrate is design-family neutral. Brand-specific values go in `config.toml [extra]`:

| Field                       | What it shapes                              |
|-----------------------------|---------------------------------------------|
| `brand_name`                | header, footer, JSON-LD Organization name   |
| `brand_greek`               | nav-logo hover and footer attribution       |
| `logo_path`                 | header logo + JSON-LD Organization.logo     |
| `favicon_path`              | `<link rel="icon">`; defaults to `img/favicon.svg`; `type=` is derived from the path's own extension (`.ico`/`.png`/`.gif`/`.jpg`/`.jpeg`/`.webp`/`.svg`), not hardcoded |
| `theme_color`               | `<meta name="theme-color">` browser chrome  |
| `og_image`                  | default Open Graph image when a page omits its own |
| `font_preload`              | which `.woff2` files preload at first paint |
| `nav_items`, `footer_links` | navigation structure                        |
| `[extra.author]`            | atom feed `<author>` + JSON-LD Article author |
| `consumer_css`              | list of stylesheet paths, each `<link>`ed after core's own `style.css`, in order (`templates/base.html`'s Consumer stylesheet hook) |

If a brand needs a *visual* override beyond the table above (different scale ratio, different color palette, different type pairing), declare it via `consumer_css` and redeclare the relevant `:root` custom properties in that file. Core's own interactive-state CSS (nav hover, buttons, the home triad mark, FAQ anchors, ...) never hard-codes a hue — it resolves through four semantic tokens, `--accent-1` through `--accent-4`, which default to a neutral `--text-mid` and exist solely for a skin to redeclare. `static/css/skins/leather.css` is the first-party example: it maps those four tokens to Ardent Leatherworks' dye palette and carries that brand's own content-authoring classes (`.dye-entry-*`, `.swatch-*`, `.dye-marks`) — copy its shape, not its colors, for a new skin. **Do not edit typikon's `static/css/style.css`** for one-off site needs — that's a fork by mutation.

Beyond styles, `templates/base.html`'s own header comment documents the full design/extension surface (forkwright/typikon#55): a `{% block %}` for head metadata, nav, footer, structured data (JSON-LD), scripts, and page composition, each with a sane default a consumer only overrides when it needs to. A consumer template extends `base.html` and overrides just the block(s) it needs — it does not need to copy the whole file to add a stylesheet, a nav item, or a JSON-LD field.

### 3. When to extend typikon vs. override locally

| You need to                                                | Where it goes                                                            |
|------------------------------------------------------------|--------------------------------------------------------------------------|
| Change one site's color palette / type / scale             | `consumer_css` entry redeclaring `:root` tokens (incl. `--accent-1..4`)  |
| Add a one-off CSS class used in one site's content          | `consumer_css` entry                                                     |
| Add a stylesheet, head element, or footer content of your own | Override the relevant `{% block %}` in a template that `{% extends "base.html" %}` — see that file's header comment. Not a reason to shadow `base.html` itself |
| Add a content type (FAQ, sizing-guide, recipe, gallery)    | typikon — schema + template + AGENTIC + fixture coverage                 |
| Add an optional frontmatter field shared by ≥2 sites       | typikon — extend the relevant schema; every content type's `extra` is closed (`unevaluatedProperties: false` or, for journal-entry/product/faq/sizing-guide, plain `additionalProperties: false`), so a new field is a schema edit, never an ambient allowance |
| Override one page's HTML structure with a custom template  | Consumer-side template under `<consumer>/templates/<name>.html` (Zola overrides typikon) **and** a `schemas/registry.toml` entry — see `docs/SCHEMAS.md#consumer-schema-registry`. A custom `template` with no registry entry fails validation; it does not fall back to `page`'s shape |
| Add a global behavior (CSP token, JSON-LD type, atom field)| typikon — and update `examples/` so the fixture exercises the change      |

The rule of thumb: **two consumers wanting the same thing → typikon. One consumer wanting an exception → consumer-side override.**

### 4. Fixtures verify your assumptions

`examples/sample-blog/` and `examples/sample-shop/` are working consumer sites that consume typikon via a `themes/typikon` symlink to the parent repo. They build under `zola build` from their own directory and exercise every schema and template typikon ships.

When you add a content type or change a primitive, update at least one fixture to exercise the change. CI runs `zola build` + `typikon-validate` + `csp-enforce` against both fixtures on every PR. If a substrate change breaks a fixture, it would break a real consumer — fix it before merge.

### 5. Schema migrations

When a typikon schema changes incompatibly, the same PR ships a migration script — see `bin/typikon-migrate-template` and the migration section of [`SCHEMAS.md`](SCHEMAS.md). The PR description lists every consumer affected. On merge, run the migration against each consumer in a separate consumer-side PR.

## What this contract does not say

- It does not say *what* content to write. That comes from the consumer site's brief.
- It does not say what the design language is. That is in `templates/` + `static/` and is read, not derived.
- It does not say how to make decisions about scope. Use kanon's standard escalation surfaces (issues, plans).

When in doubt, run the gate. If the gate is green, you are not breaking anything. If the gate is red, the gate is the source of truth. <!-- kanon:ignore WRITING/passive-voice -- green and red are CI-status adjectives, not participles, with no actor to name — filed kanon (forge) issue #10074 -->
