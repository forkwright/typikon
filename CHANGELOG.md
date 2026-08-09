# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project follows semantic versioning.

No version has been cut yet — everything below is unreleased work on `main`. Once release-please automation is wired (RELEASES.md § Required configuration files), version cuts populate this file with dated, tagged sections below `## Unreleased`.

## Unreleased

### Features

- **ci**: Scaffold kanon deploy template (#17) — consumer sites now scaffold `.kanon-ci.toml` from `ci/kanon-ci.toml.tmpl` with full 14-stage pipeline (zola, CSP, links, a11y, playwright smoke). Dual-CI migration window: forge is primary, GitHub is fallback until forge deploy path validates end-to-end.
- **bin**: Add `typikon-migrate-template` binary — skeleton for schema-migration scripts when frontmatter evolves incompatibly. Consumer sites run this once per major typikon bump.
- **templates**: Enforce required metadata (#2) — frontmatter validation now runs pre-commit.

### Fixes

- **ci**: Drive typikon CI to green (#27) — lychee excludes self-host URLs to break the deploy chicken-and-egg.
- **ci**: Suppress SHELL/strict-mode with intent directive (#15) — `ci/csp-enforce.sh` preserves full-report CSP scan behavior (accumulate violations, do not abort on first miss).
- **lint**: Drop stale CSP inline ignore — follow-up to #18.

### Documentation

- **README**: Add `typikon-migrate-template` to binary inventory (#14).
- **CLAUDE.md**: Add preamble with scope/defers_to/tightens per kanon CONTEXT/preamble-required.

### Changed

- **repo**: Align with FLEET-REPO-SETUP standard (forge-primary) (#13) — add .gitattributes with markdown trailing-whitespace carve-out (D-055), bootstrap empty CHANGELOG.md.
- **lint**: Preserve typikon prose voice — scoped `.kanon-lint-ignore` for typikon#9 (substrate/example prose) and typikon#15 (CSP scan full-report behavior). Per operator decision, em-dash policy is intentional and preserved.
