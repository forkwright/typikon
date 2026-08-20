# Bootstrap: scaffolding and refreshing a typikon-consuming site

Two separate binaries cover the lifecycle of a consumer site: `bin/typikon-init` scaffolds a new one, `bin/typikon-refresh` (invoked from inside a consumer site, via its `themes/typikon/` submodule) bumps an existing one to the latest typikon. They are distinct commands with distinct contracts — `typikon-init` has no `--refresh` flag.

## `typikon-init` — scaffold a new consumer site

```bash
bin/typikon-init <site-name> <destination-path>
```

`site-name` must be lowercase ASCII, starting with a letter (`^[a-z][a-z0-9-]*$`). It becomes the forge/GitHub repo slug. The scaffolder creates `destination-path` if absent.

Environment overrides:

| Var | Default | Purpose |
|-----|---------|---------|
| `TYPIKON_THEME_REPO` | `http://127.0.0.1:7878/forkwright/typikon.git` | forge URL for the `themes/typikon` submodule |
| `TYPIKON_THEME_REPO_GH` | `git@github.com:forkwright/typikon.git` | GitHub remote URL |
| `TYPIKON_ZOLA_VERSION` | value in `bin/typikon-defaults.sh` | Zola version substituted into CI templates |
| `TYPIKON_WRANGLER_VERSION` | value in `bin/typikon-defaults.sh` | wrangler version substituted into CI templates |

Behavior:

1. Run `git init -b main` when `.git` does not exist yet. Add `origin` (forge) and `github` (mirror) remotes.
2. Add `themes/typikon` as a git submodule if missing. Otherwise, run `git pull --ff-only origin main` inside it (best-effort — failure doesn't abort the run).
3. Copy `_headers.tmpl` → `_headers` and `_redirects.tmpl` → `_redirects` verbatim, skipping either that already exists. These are one-time copies: consumers hand-edit them afterward, and `typikon-init`/`typikon-refresh` never overwrite them again.
4. Render `ci/kanon-ci.toml.tmpl` → `.kanon-ci.toml` and `ci/github-workflow.yml.tmpl` → `.github/workflows/deploy.yml`, substituting `{{ PROJECT_NAME }}`, `{{ ZOLA_VERSION }}`, and `{{ WRANGLER_VERSION }}`. Skipped if the destination file already exists — re-rendering an existing consumer's CI files is `typikon-refresh`'s job, not `typikon-init`'s.
5. Write `.gitignore`, `config.toml` (Zola config, `theme = "typikon"`, stub `[extra]` block), `content/_index.md`, `content/about.md`, `content/contact.md`, and `CLAUDE.md` (the consumer-specific operator brief) — each only if absent, so re-running against an existing destination never clobbers consumer-edited content.
6. Create `static/img/.gitkeep` and `tests/smoke/.gitkeep`.
7. Force-add `CLAUDE.md` (excluded by the operator's global gitignore by default), stage everything, and commit if this is the first commit. Otherwise, leave the refresh staged.
8. Print next steps: run `bin/typikon-check .`, push with `ALLOW_PROTECTED_PUSH=1` on the first push, `kanon forge init` the new repo.

Idempotency is per-file: `write_if_absent` and `copy_template` steps (3–5) skip anything already on disk. Only a re-run bumps the submodule pointer (step 2). There is no `--refresh` flag — re-running `typikon-init` against an existing destination fills in anything still missing, it does not re-render already-scaffolded CI templates.

## `bin/typikon-refresh` — bump a consumer to the latest typikon

```bash
# from the consumer site root
themes/typikon/bin/typikon-refresh
```

A separate binary from `typikon-init`, invoked through the consumer's own `themes/typikon/` submodule checkout, not from typikon's own repo directly (it verifies the checkout it's running from matches the consumer's submodule path and refuses otherwise).

Environment overrides:

| Var | Default | Purpose |
|-----|---------|---------|
| `TYPIKON_PROJECT_NAME` | basename of `git config remote.origin.url`, `.git` suffix stripped | project slug substituted into CI templates |
| `TYPIKON_ZOLA_VERSION` | value in `bin/typikon-defaults.sh` (shared with `typikon-init`) | Zola version substituted into CI templates |
| `TYPIKON_WRANGLER_VERSION` | value in `bin/typikon-defaults.sh` (shared with `typikon-init`) | wrangler version substituted into CI templates |

Behavior:

1. Sanity-check: must run from a consumer root containing `themes/typikon/theme.toml`, from the matching submodule checkout, inside a git repo.
2. `cd themes/typikon && git pull --ff-only origin main`. Exits 1 if the submodule has diverged from `origin/main` — reconcile manually and re-run.
3. Derive `PROJECT_NAME`, `ZOLA_VERSION`, and `WRANGLER_VERSION` (env override or default).
4. Unconditionally re-render `ci/kanon-ci.toml.tmpl` → `.kanon-ci.toml` and `ci/github-workflow.yml.tmpl` → `.github/workflows/deploy.yml`. This is the only place these two files are re-rendered post-init. Hand-edits to them are lost by design (per-site CI deltas belong in sibling files or an operator-authored follow-up commit). `_headers`/`_redirects` are never touched here — they're one-time copies from step 3 of `typikon-init`.
5. Stage the bumped submodule pointer and each re-rendered file (named `git add`, not `-A`, so unrelated operator-side work isn't swept in).
6. Print a summary (submodule SHA before/after, `PROJECT_NAME`, `ZOLA_VERSION`, what it rendered or skipped) and the staged diffstat.

`typikon-refresh` never commits — it stages and prints a suggested commit message. The operator or agent reviews `git diff --cached` and authors the commit. Idempotent: re-running with no upstream change is a no-op (the re-render is byte-identical, so nothing new gets staged beyond what's already there).

## Schema migrations

When an incompatible schema change can transform existing bytes without inventing facts, the migration ships as `bin/typikon-migrate-<from>-<to>` in the same PR. Running `typikon-refresh` bumps the submodule to the version carrying the migration script. The operator runs the migration script against the consumer separately — `typikon-refresh` itself does not invoke migrations. Newly required provenance is the exception: the Typikon PR names blocked consumers, and each consumer authors the source or intentionally removes the gated fact in its own PR.
