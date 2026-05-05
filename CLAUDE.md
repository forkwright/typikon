# CLAUDE.md: Typikon

## Repository

Typikon (τυπικόν): the rule by which a thing of a given kind is enacted. A Zola theme + frontmatter schemas + agentic scaffolding + CI gates. Fleet web-property substrate. Sites of the family consume typikon as a git submodule.

A typikon governs *how* a service is performed without specifying *what* the service contains. Concretely: templates, schemas, scaffolders, and gates that produce coherent fleet sites without specifying their content.

## Operating principle

This repository is optimized for agentic operation. Humans should not need to develop here. Every change should leave the substrate more agent-operable, not less. If an edit makes a primitive harder to script, validate, or scaffold, it's the wrong shape.

```
typikon/
├── theme/                  # Zola theme (consumed by sites)
│   ├── templates/          # Tera templates: base, page, section, journal
│   ├── static/             # css, js, fonts (self-hosted WOFF2)
│   └── sass/               # design tokens, type scale, layout primitives
├── schemas/                # JSON Schema per content type
├── scaffolds/              # content templates copied by typikon-init
├── bin/                    # typikon-init, typikon-validate, typikon-check
├── ci/                     # strict gate config (lychee, pa11y, playwright, csp-enforce)
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

- **Static SSG**: Zola 0.22.x. No JavaScript build step, no Node toolchain, no npm in the deploy path.
- **Theme distribution**: git submodule under consumer's `theme/`. (Zola has no theme registry; submodule is current best practice.)
- **Strict CSP**: no `unsafe-inline` anywhere. CSP-enforce CI gate fails the build on any inline script, style, or `on*=` handler.
- **Self-hosted fonts**: WOFF2 under `theme/static/fonts/`. Zero external CDN at visitor runtime. OFL families only.
- **Forge-primary**: `origin` points at the forkwright forge (`http://127.0.0.1:7878/forkwright/typikon.git`). GitHub is push-mirror only via `kanon forge set-mirror`.
- **License**: AGPL-3.0-or-later. Matches dioptron, aletheia. AI-training prohibition in NOTICE.

## How an agent operates here

1. **Read the schema first.** Every content type has a JSON Schema. Frontmatter shape, required fields, validation rules are documented there. Do not invent fields.
2. **Use the scaffolder.** `bin/typikon-init <type>` produces valid scaffolded content. Do not hand-write frontmatter.
3. **Validate before push.** `bin/typikon-validate` exits 1 on any frontmatter violation with JSONL output (file path, JSON pointer). Run it in your loop.
4. **Run the gate.** `bin/typikon-check` runs the full CI sequence locally. If it fails, fix; do not push to bypass.
5. **No inline scripts or styles.** Anywhere. The CSP gate enforces this. Extract to `theme/static/js/` or `theme/static/css/`.
6. **Schemas and primitives change in typikon, not in consumers.** When two consumer sites disagree on a primitive, parameterize the schema; don't fork the theme.

## Boundaries

- **Push to `origin` (forge), not `github`.** Mirror handles GitHub. Verify with `git remote -v`.
- **Never bypass the CI gate.** No `--no-verify`, no `[skip ci]`, no commit on green failure.
- **Schema changes are migrations.** When a schema changes incompatibly, the change PR ships a migration script for existing consumers in `bin/`.
