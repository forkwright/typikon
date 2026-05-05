# Bootstrap: scaffolding a new typikon-consuming site

`bin/typikon-init` creates a new fleet site that consumes typikon. It is idempotent — running against an existing directory refreshes scaffolded files but does not overwrite content.

## Status

This document is a placeholder. The full scaffolder lands in Phase 4 of the typikon v1 plan. When it does, this document covers:

- Invocation and flags
- What the scaffolder writes
- How the typikon submodule is wired
- How forge + GitHub remotes are configured
- Idempotency semantics
- How to refresh a consumer when typikon ships a new schema or primitive

## Anticipated invocation

```bash
bin/typikon-init <site-name> <destination-path>
```

Behavior (anticipated):

1. Create destination directory if missing.
2. Initialize git, `git remote add origin http://127.0.0.1:7878/forkwright/<site-name>.git`, `git remote add github git@github.com:forkwright/<site-name>.git`.
3. Add typikon as a submodule under `themes/typikon/`.
4. Write `config.toml` with `theme = "typikon"` and a stub `[extra]` block keyed for the consumer.
5. Copy `scaffolds/new-site/` skeleton into `content/`: `_index.md`, `philosophy.md`, `contact.md`, journal section index, products section index.
6. Copy `_headers.tmpl` → `_headers`, `_redirects.tmpl` → `_redirects`, with consumer-specific values templated.
7. Copy `ci/github-workflow.yml.tmpl` → `.github/workflows/deploy.yml` with consumer's project name templated for `wrangler pages deploy`.
8. Stage everything, write the initial commit.
9. Run `bin/typikon-validate` and `bin/typikon-check` against the new site. Exit 0 only if both pass.

## Refreshing an existing consumer

```bash
bin/typikon-init --refresh <existing-site-path>
```

Behavior (anticipated):

- Bumps the typikon submodule to the latest tag.
- Re-runs scaffolds for files that have not been edited (unchanged from previous scaffold hash).
- Reports which files were skipped because the consumer has diverged.
- Never overwrites consumer-edited files.

This is how schema migrations propagate: typikon ships a migration script in `bin/typikon-migrate-<from>-<to>`, the consumer runs `--refresh`, the migration applies.
