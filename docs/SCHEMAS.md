# Schemas

JSON Schema definitions for every content type a typikon-consuming site can author. Schemas are authoritative; this document is a human-readable index.

Validation runs via `bin/typikon-validate`. Schema files live in `schemas/`.

## Status

This document is a placeholder. Schemas land in Phase 4 (per the typikon v1 plan). When they do, this document gets:

- One section per schema (page, section, journal-entry, product)
- For each: required fields, optional fields, validation rules, the JSON Schema reference, an example valid frontmatter block.

## Schema files

| Schema | Path | Status |
|--------|------|--------|
| Page | `schemas/page.schema.json` | TODO (Phase 4) |
| Section | `schemas/section.schema.json` | TODO (Phase 4) |
| Journal entry | `schemas/journal-entry.schema.json` | TODO (Phase 4) |
| Product | `schemas/product.schema.json` | TODO (Phase 4) |

## Adding a new content type

1. Identify the type. If two existing types could absorb it via an optional field, use that instead.
2. Write `schemas/<type>.schema.json`, extending `page.schema.json` where possible.
3. Add a scaffold under `scaffolds/new-<type>.md.tmpl`.
4. Update `bin/typikon-init` to recognize the type.
5. Update this document with the new section.
6. Add a fixture in `examples/` exercising the type.
7. Run `bin/typikon-check examples/<fixture>` end-to-end.
