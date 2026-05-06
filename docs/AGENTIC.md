# Agentic operation

Typikon is operated by AI agents. This document is the contract every agent follows when working on typikon itself or on any consumer site.

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

The schema defines: required fields, optional fields, value types, value patterns, length limits. Do not invent fields. If a frontmatter field is not in the schema, do not write it.

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

Runs every content file in the consumer site against its appropriate schema. Output is JSONL on stderr; exit 0 = all valid, exit 1 = any failure.

JSONL line shape:

```json
{"file": "content/products/belt.md", "pointer": "/extra/price", "error": "expected string, got null"}
```

Run this in your authoring loop. Do not push without it passing.

### 4. Run the gate locally

```bash
bin/typikon-check <consumer-site-root>
```

Runs (in order, fail-fast):

1. `zola check` (internal links + assets)
2. `zola build` (no warnings tolerated)
3. `csp-enforce.sh` (greps `public/` for inline `<script>`, `<style>`, `on*=` handlers)
4. `lychee public/ --config ci/lychee.toml` (external links)
5. `pa11y-ci --config ci/pa11y.config.js` (WCAG 2.1 AA)
6. `playwright test` (per-route smoke assertions)

Output is JSONL summarizing each gate. If anything fails, fix; do not push to bypass.

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

### 7. Schema changes are migrations

When a schema field is renamed, removed, or changed incompatibly, the typikon PR also ships a migration script in `bin/typikon-migrate-<from>-<to>`. The script:

- Runs against a consumer site root
- Reads every content file, applies the transformation, writes back
- Is idempotent (re-running is a no-op if already migrated)
- Exits 0 on success with summary of files changed

The PR description must list every consumer affected and link the migration runs.

### 8. Repos are forge-primary

`origin` is the forkwright forge (`http://127.0.0.1:7878/forkwright/typikon.git`). `github` is the GitHub mirror (push only). Check with `git remote -v` before push.

`kanon forge set-mirror` configures the mirror push. Do not push directly to GitHub — the mirror handles it.

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

The product-gallery partial (auto-included by page.html) renders a responsive `<picture>` per image — Zola's `resize_image()` generates 400 / 800 / 1200 px WebP variants automatically. First image is the hero (eager-loaded); the rest lazy-load.

When real photos arrive, drop the placeholder `<div class="product-images">…image-placeholder-list…</div>` block from the markdown body — the gallery takes its visual slot.

## The agent loop

For a routine content edit:

```
1. typikon-init <type> <path>           # produces valid scaffold
2. edit the markdown body              # frontmatter is already correct
3. typikon-validate <site-root>        # exits 0 = good
4. typikon-check <site-root>           # exits 0 = ready to push
5. git commit + git push origin main   # forge primary, mirror to GH
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

## What this contract does not say

- It does not say *what* content to write. That comes from the consumer site's brief.
- It does not say what the design language is. That is in `templates/` + `static/` and is read, not derived.
- It does not say how to make decisions about scope. Use kanon's standard escalation surfaces (issues, plans).

When in doubt, run the gate. If the gate is green, you are not breaking anything. If the gate is red, the gate is the source of truth.
