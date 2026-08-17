+++
title = "first entry"
description = "The first journal entry in the sample fixture. Tests that the journal-entry schema's required fields all flow through to the rendered page."
date = 2026-01-15

[extra]
audience = "typikon fixture readers"
components = "λόγος · attention · the work"
words = "~120 words"
words_source = "fixture hand count"
+++

The first journal entry exists to prove that `journal-entry.schema.json` validates a real file with all required fields populated.

The frontmatter declares its own `words`/`words_source`, overriding the derived `page.word_count` the template renders by default (see `second-entry.md` for the derived count actually rendering). The template renders `audience` and `components` in the entry header, the date through `<time datetime="...">`, the title as `<h1>`, the body inside `<article class="journal-entry-page">`, and the prev/next nav at the bottom (with no targets in a one-entry corpus).

When this fixture grows past one entry, the prev/next links should appear and follow the older=prev, newer=next convention.
