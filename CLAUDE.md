<!--
scope: Fleet Zola theme, frontmatter schemas, scaffolds, and CI gates for agentic web-property substrate
defers_to: docs/AGENTIC.md for the agent contract; docs/SCHEMAS.md for frontmatter rules; docs/BOOTSTRAP.md for scaffolder behaviour
tightens: strict CSP with no unsafe-inline narrows the kanon defaults for fleet web properties
-->

# CLAUDE.md: Typikon

## Repository

Typikon (τυπικόν): the rule by which a thing of a given kind is enacted. A Zola theme + frontmatter schemas + agentic scaffolding + CI gates. Fleet web-property substrate. Sites of the family consume typikon as a git submodule.

A typikon governs *how* a service is performed without specifying *what* the service contains. Concretely: templates, schemas, scaffolders, and gates that produce coherent fleet sites without specifying their content.

## Operating principle

This repository is optimized for agentic operation. Humans should not need to develop here. Every change should leave the substrate more agent-operable, not less. If an edit makes a primitive harder to script, validate, or scaffold, it's the wrong shape.

```
typikon/
├── templates/              # Tera templates: base, page, section, journal
├── static/                 # css (design tokens inline in style.css), js, fonts (self-hosted WOFF2)
├── sass/                   # reserved, currently empty
├── schemas/                # JSON Schema per content type
├── scaffolds/              # reserved, currently empty — typikon-init scaffolds content inline
├── bin/                    # typikon-init, typikon-validate, typikon-check, typikon-refresh, typikon-migrate-template
├── ci/                     # strict gate config (lychee, pa11y, playwright, csp-enforce, asset-provenance)
├── docs/                   # AGENTIC.md, SCHEMAS.md, BOOTSTRAP.md
├── _headers.tmpl           # Cloudflare Pages strict-CSP
├── _redirects.tmpl         # Cloudflare Pages redirects
├── theme.toml              # Zola theme manifest
├── CLAUDE.md
├── README.md
├── LICENSE
└── NOTICE
```

## Standards

Follow kanon standards (canonical: `~/dev/kanon/crates/basanos/standards/`). Key docs: `STANDARDS.md`, `TESTING.md`, `SECURITY.md`, `WRITING.md`, `GNOMON.md`.

Web-property-specific standards live alongside as kanon STANDARDS/WEB.md (filed against kanon as a follow-up to typikon v1).

## Locked decisions

- **Static SSG**: Zola 0.23.x with Tera 2 templates. No JavaScript build step, no Node toolchain, no npm in the site build path.
- **Dual-CI migration window**: consumer sites scaffold both `.kanon-ci.toml` and `.github/workflows/deploy.yml`. Forge is primary; GitHub is the executable fallback until menos validates the forge deploy path end-to-end. Both templates target the same Cloudflare Pages project and main/master branch semantics.
- **Temporary Node deploy-tool exception**: the consumer deploy gates install npm-based `pa11y`, Playwright, and Wrangler so forge and GitHub stay stage-for-stage equivalent during migration. Revisit when forge has native replacements.
- **Theme distribution**: git submodule under consumer's `themes/typikon/`. (Zola has no theme registry; submodule is current best practice.)
- **Strict CSP**: no `unsafe-inline` anywhere. CSP-enforce CI gate fails the build on any inline script, style, or `on*=` handler.
- **Self-hosted fonts**: WOFF2 under `static/fonts/`. Zero external CDN at visitor runtime. OFL families only.
- **Root Atom ownership**: `config.extra.feed_source_section` assigns the root feed through one canonical `_index.md` path. That owner and every translation use `sort_by = "date"`; missing, empty, or wrongly sorted sources fail while native section/taxonomy feeds remain Zola-owned.
- **Fail-closed checkout**: product price is catalog data. Checkout and Offer URLs require sourced purchasable availability, and shipping text requires its own source.
- **Push authority**: `origin` is GitHub (`forkwright/typikon`); no forge remote is configured. The typed forge/GitHub authority split is unresolved — forkwright/kanon#3045 owns it.
- **License**: PolyForm Noncommercial 1.0.0 (`LicenseRef-PolyForm-Noncommercial-1.0.0`). `LICENSE` is authoritative.
- **Consumer schema registry**: a consumer site's custom-templated content types register in `schemas/registry.toml` and validate against their own schema, composed from typikon's open `page.core.schema.json`/`section.core.schema.json` building blocks and closed with `unevaluatedProperties: false`. A custom `template` with no registry entry fails validation naming the missing registration rather than falling back to `page`'s shape. See `docs/SCHEMAS.md#consumer-schema-registry`. <!-- kanon:ignore STANDARDS/citation-must-be-resolvable -- anchor exists at docs/SCHEMAS.md:26. Resolver drops the docs/ prefix and checks the wrong directory. Filed kanon (forge) issue #10073. -->

## How an agent operates here

1. **Read the schema first.** Every content type has a JSON Schema. Frontmatter shape, required fields, validation rules are documented there. Do not invent fields.
2. **Use the scaffolder.** `bin/typikon-init <type>` produces valid scaffolded content. Do not hand-write frontmatter.
3. **Validate before push.** `bin/typikon-validate` exits 1 on any frontmatter violation with JSONL output (file path, JSON pointer). Run it in your loop.
4. **Run the gate.** `bin/typikon-check` runs the full CI sequence locally. If it fails, fix; do not push to bypass.
5. **No inline scripts or styles.** Anywhere. The CSP gate enforces this. Extract to `static/js/` or `static/css/`.
6. **Schemas and primitives change in typikon, not in consumers.** When two consumer sites disagree on a primitive, parameterize the schema; don't fork the theme.

## Boundaries

- **Push to `origin`.** It is GitHub; there is no mirror step. Verify with `git remote -v` rather than assuming.
- **Never bypass the CI gate.** No `--no-verify`, no `[skip ci]`, no commit on green failure.
- **Schema changes are migrations.** Ship a `bin/` migration for incompatible transformations that can preserve truth. A newly required provenance value is the explicit exception: name every blocked consumer, then author the source or intentionally remove the gated fact in a consumer PR; never synthesize provenance.

<!-- kanon:auto-start -->
## Generated kanon context

- Registry name: `typikon`
- Forge repo: `forkwright/typikon`
- Kanon prefix: `ty`
- Config source: `workflow/kanon.toml [projects.typikon]`
- Standards source: `crates/basanos/standards/STANDARDS.md`
- MCP routing catalog: `workflow/AGENTS-mcp-tools.md`

Run `kanon docs sync --check --repo typikon` to verify this generated
section and `kanon docs sync --apply --repo typikon` to refresh it.

## Blast zone

- Paths explicitly named by the rendered prompt, role, or template input.

## Acceptance verifier

```bash
kanon gate
```
<!-- kanon:auto-end -->
