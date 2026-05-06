+++
title = "first entry"
description = "The first journal entry in the sample fixture. Tests that the journal-entry schema's required fields all flow through to the rendered page."
date = 2026-01-15

[extra]
components = "λόγος · attention · the work"
words = "~120 words"
+++

The first journal entry exists to prove that `journal-entry.schema.json` validates a real file with all required fields populated.

The frontmatter declares its `date`, `description`, and the entry-extras (`components`, `words`). The template renders the date through `<time datetime="...">`, the title as `<h1>`, the body inside `<article class="journal-entry-page">`, and the prev/next nav at the bottom (with no targets in a one-entry corpus).

When this fixture grows past one entry, the prev/next links should appear and follow the older=prev, newer=next convention.
