# Typikon

> τυπικόν: the rule by which a thing of a given kind is enacted.

A Zola theme + frontmatter schemas + agentic scaffolding + CI gates. The fleet's web-property substrate. Sites consume typikon as a git submodule. Typikon governs how those sites are built, validated, and deployed.

A typikon does not contain the service. It governs how the site enacts the service.

## Design

Optimized for agentic operation. Humans should not need to develop here. The substrate ships:

- **Templates** (`templates/`) - Zola 0.23/Tera 2 templates for base, page, section, journal.
- **Schemas** (`schemas/`) - JSON Schema for every content type. Frontmatter must validate before commit.
- **Binaries** (`bin/`) - `typikon-init` (scaffolds a consumer site's content and config inline, no separate template directory), `typikon-validate`, `typikon-check`, `typikon-refresh`, `typikon-migrate-template` (skeleton for schema-migration scripts). Idempotent CLIs with JSONL output where applicable.
- **CI** (`ci/`) - strict gate: build, CSP enforcement, internal + external link integrity, a11y, smoke. No pass = no deploy.
- **Headers** (`_headers.tmpl`, `_redirects.tmpl`) - Cloudflare Pages strict-CSP + redirect templates.

## Visitor runtime

- Self-hosted WOFF2 fonts. Zero external CDN dependencies at visitor runtime.
- Strict CSP with no `unsafe-inline` anywhere. Inline scripts and styles are CI failures.
- All third-party form actions explicitly allowlisted in CSP `form-action`.

## Topology

| Name | Role |
|------|------|
| **kanon** | the canon, the law |
| **basanos** | the touchstone, the test |
| **gnomon** | the indicator that makes pattern legible |
| **typikon** | the rule of execution for fleet web properties |

## Usage

```bash
# Scaffold a new consumer site
bin/typikon-init <site-name> /path/to/new/site

# Validate content against schemas
bin/typikon-validate /path/to/consumer/site

# Run all CI gates locally
bin/typikon-check /path/to/consumer/site

# Refresh a consumer site against the latest typikon main
# (run from the consumer site root; bumps the submodule + re-renders
#  every substituted template; stages the diff but doesn't commit).
themes/typikon/bin/typikon-refresh
```

See `docs/AGENTIC.md` for the agent contract, `docs/SCHEMAS.md` for the frontmatter reference, `docs/BOOTSTRAP.md` for the scaffolder behavior.

## License

PolyForm Noncommercial 1.0.0 (`LicenseRef-PolyForm-Noncommercial-1.0.0`). See LICENSE and NOTICE.

Self-hosted fonts under `static/fonts/` are OFL-1.1. See NOTICE for attributions.

<!-- kanon:auto-start -->
## Repository Metadata

- Registry name: `typikon`
- Description: Kanon-managed forkwright repository `typikon`.
- Forge repo: `forkwright/typikon`
- Kanon prefix: `ty`
- Config source: `workflow/kanon.toml [projects.typikon]`
- Planning state: `projects/typikon/STATE.md`
- Last state update: `not recorded`

Run `kanon docs sync --check --repo typikon` to verify this generated
section and `kanon docs sync --apply --repo typikon` to refresh it.

## Blast zone

- Paths explicitly named by the rendered prompt, role, or template input.

## Acceptance verifier

```bash
kanon gate
```
<!-- kanon:auto-end -->
