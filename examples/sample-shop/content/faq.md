+++
title = "Questions"
description = "Sample FAQ. Exercises faq.schema.json's required questions array and the FAQPage JSON-LD partial."
template = "faq.html"

[extra]
audience = "sample shop visitors"

[[extra.questions]]
q = "What is this fixture for?"
a = "Validating the FAQ schema and template against a real consumer-shaped file. The rendered page should emit FAQPage JSON-LD covering both questions."
anchor = "fixture"

[[extra.questions]]
q = "How are anchors generated?"
a = "When `anchor` is omitted, the template slugifies the question text. When set explicitly (as on this entry), the template honors the explicit value."

[[extra.questions]]
q = "Do you ship worldwide?"
a = "Yes — worldwide shipping is available."

[[extra.questions]]
q = "Do you ship worldwide?!"
a = "Same auto-slugify as the previous question (forkwright/typikon#92); the anchor must still be unique."

[[extra.questions]]
q = "What if a question contains </script> ?"
a = "It renders as inert text, both here and inside the FAQPage JSON-LD block — </script> must never terminate the ld+json <script> element early."
+++

This fixture's FAQ exists only to prove the substrate works.
