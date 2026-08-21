<!--
scope: typikon repo cross-tool agent guide (Claude Code, Kimi, Codex, Cursor, Windsurf, Copilot)
defers_to: CLAUDE.md for locked decisions and boundaries; docs/AGENTIC.md for the full agent contract
tightens: docs/SCHEMAS.md frontmatter validation; docs/BOOTSTRAP.md scaffolder behavior
-->

# AGENTS.md

Agent operating manual for forkwright/typikon. Read this before contributing to the theme substrate.

## Quick start

Typikon is a Zola theme + frontmatter schemas + CI gates for agentic fleet web properties. Read the entry points in order:

1. [README.md](README.md) — overview, design, usage
2. [CLAUDE.md](CLAUDE.md) — locked decisions, boundaries
3. [docs/AGENTIC.md](docs/AGENTIC.md) — agent contract
4. [docs/SCHEMAS.md](docs/SCHEMAS.md) — frontmatter field reference
5. [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md) — scaffolder behavior
6. [docs/RELEASING.md](docs/RELEASING.md) — exact candidate and consumer-lock protocol

## Key binaries

| Binary | Purpose |
|--------|---------|
| `bin/typikon-init` | Scaffold a new consumer site or content primitive. Usage: `bin/typikon-init <site-name> <dest>`. |
| `bin/typikon-validate` | Validate frontmatter against schemas. Usage: `bin/typikon-validate <consumer-site-root>`. JSONL output on stderr. |
| `bin/typikon-check` | Run the full local pre-push gate. Usage: `bin/typikon-check <consumer-site-root>`. |
| `bin/typikon-refresh` | Bump consumer site submodule + re-render templates. Run from consumer site root. |
| `bin/typikon-migrate-template` | Skeleton for schema-migration scripts. Copy and adapt when frontmatter changes incompatibly. |

All CLIs are idempotent; JSONL output for parsing.

## Development loop

### Theme changes

1. Edit template, schema, scaffold, or CI gate in typikon.
2. Validate: `cd <consumer-site> && themes/typikon/bin/typikon-check .` (every stage passes).
3. Run the theme gate locally: `cd <typikon> && ci/run-fixtures.sh` (validates typikon's own fixtures).
4. Commit with conventional commit (type: feat/fix/chore/docs). No inline scripts/styles. No unsafe-inline CSP.
5. Push to origin (GitHub). The gate is .github/workflows/gate-attestation.yml; no forge
   remote is configured, so the `.kanon-ci.toml` lint stage does not execute anywhere.

### Consumer site updates

Consumer sites use typikon as a git submodule under `themes/typikon/` and scaffold content via the binaries above. When typikon changes:

1. Consumer runs `themes/typikon/bin/typikon-refresh` (bumps submodule, re-renders templates).
2. Consumer validates: `bin/typikon-check .` (every stage).
3. Consumer commits the diff.

## Locked decisions

All decisions are in [CLAUDE.md](CLAUDE.md) under "Locked decisions". Key ones:

- **Static SSG**: Zola 0.23.x with Tera 2 templates. No JavaScript build step in site build path.
- **Strict CSP**: no `unsafe-inline` anywhere. CSP-enforce CI gate fails the build on inline script/style/handler.
- **Self-hosted fonts**: WOFF2 under `static/fonts/`. Zero external CDN at visitor runtime.
- **Root Atom ownership**: a consumer may set `extra.feed_source_section` to one canonical `_index.md` path. That owner and every translation use `sort_by = "date"`; missing, empty, or wrongly sorted sources fail while native section/taxonomy feeds remain Zola-owned.
- **Repository-only agent corpus**: a consumer may set `extra.agent_corpus_exposure = "repository"`, the only accepted value. It is enforced, not advisory: `ci/validate-artifact-boundary.py` fails the local gate and both generated pipelines — before the consumer receipt and before deploy — if the rendered `public/` or `public-local/` tree carries an `llms.txt` basename or an `_llm` path component, under any casing or behind a renamed symlink. Omit the field to make no claim.
- **Fail-closed checkout**: a catalog price does not imply readiness. Checkout and Offer URLs require sourced purchasable availability; shipping copy requires paired provenance.
- **Push authority**: `origin` is GitHub; no forge remote is configured. forkwright/kanon#3045 owns the typed authority split.
- **License**: PolyForm Noncommercial 1.0.0 (`LicenseRef-PolyForm-Noncommercial-1.0.0`). `LICENSE` is authoritative.
- **Two-phase releases**: the SemVer tag targets the frozen one-parent release commit, not the later evidence commit. Tools and Leather must pass that exact gitlink; the typed lock records both promotion and per-consumer rollback subjects.

## Boundaries

- **Push to origin, which is GitHub.** There is no forge remote and no mirror step.
  Verify with `git remote -v` rather than assuming either shape.
- **Never bypass the CI gate.** No `--no-verify`, no `[skip ci]`, no commit on green failure.
- **Schema changes are migrations.** Ship a `bin/` migration for incompatible transformations that can preserve truth. A newly required provenance value is the explicit exception: name every blocked consumer, then author the source or intentionally remove the gated fact in a consumer PR; never synthesize provenance.
- **Schemas and primitives change in typikon, not in consumers.** When two consumer sites disagree on a primitive, parameterize the schema here; do not fork the theme.
- **Owned headings carry qualified metadata.** Default page and section H1s consume typed `extra.greek`; consumers do not hand-author a replacement H1 to attach that metadata.
- **Do not publish from a provisional tree.** Keep the Release Please PR untagged until both consumer receipts and the evidence-only lock pass `ci/verify-release-lock.py`. Credential installation and the final manual dispatch remain operator-owned actions.

## Dispatch entry points

When a kimi (T3) worker lands changes to typikon:

- All changes go through `bin/typikon-check` (or CI runs it). Gate must pass.
- Recent-work review (5 days): commits must be sound (complete, no stubs/TODO-left), no AI indicators.
- Docs (README/CLAUDE/AGENTS/llms.txt/_llm/) must be kept current — do not defer doc updates to a follow-up PR.

When typikon changes, all consumer sites that use it as a submodule must refresh:

- A parent orchestrator (T2) coordinates typikon bumps across the fleet once per release.
- Consumers validate and commit the bump.

## Glossary

See [_llm/glossary.toml](_llm/glossary.toml) for typikon vocabulary (scaffold, schema, primitive, substrate, gate, CSP).

## Architecture

See [_llm/architecture.toml](_llm/architecture.toml) for theme layers and tool surfaces.
