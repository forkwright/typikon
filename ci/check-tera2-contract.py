#!/usr/bin/env python3
"""Keep Typikon's Zola pin and template dialect internally coherent.

Zola 0.23 moved to Tera 2. A version-only bump is not a migration: Tera 1
macros/imports, namespace calls, several filters, and positional test arguments
all fail when Zola compiles the theme. This static check catches those known
incompatibilities before the public GitHub gate downloads Zola and renders the
fixtures. It does not replace that renderer proof.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_SUFFIXES = {".html", ".xml", ".json", ".txt", ".ics", ".md"}

FORBIDDEN = {
    "Tera 1 macro/import tag": re.compile(r"\{%[-+]?\s*(?:macro|endmacro|import)\b"),
    "Tera 1 namespace call": re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*::[A-Za-z_][A-Za-z0-9_]*\s*\("),
    "removed collection filter": re.compile(r"\|\s*(?:concat|slice|map|filter)\b"),
    "removed string filter": re.compile(
        r"\|\s*(?:as_str|addslashes|linebreaksbr|escape)(?![A-Za-z0-9_])"
    ),
    "renamed trim filter": re.compile(r"\|\s*trim_(?:start|end)_matches\b"),
    "positional Tera 2 test argument": re.compile(
        r"\bis\s+(?:matching|starting_with|ending_with)\s*\(\s*[^)=]+\)"
    ),
}

PATTERN_WITNESSES = {
    "Tera 1 macro/import tag": '{% import "partials/assert.html" as assert %}',
    "Tera 1 namespace call": "assert::required(ok=true)",
    "removed collection filter": "items | concat(with=item)",
    "removed string filter": "value | escape",
    "renamed trim filter": 'value | trim_end_matches(pat="/")',
    "positional Tera 2 test argument": 'value is ending_with(".svg")',
}


def first_match(pattern: str, path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"{path.relative_to(ROOT)}: expected pattern {pattern!r}")
    return match.group(1)


def version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise ValueError(f"invalid dotted Zola version {value!r}") from exc


def check_pattern_witnesses() -> list[str]:
    """Prove every static detector observes the old syntax it claims to reject."""
    failures: list[str] = []
    for label, pattern in FORBIDDEN.items():
        witness = PATTERN_WITNESSES[label]
        if not pattern.search(witness):
            failures.append(f"internal detector {label!r} missed its witness {witness!r}")
    return failures


def check_pin_coherence() -> list[str]:
    failures: list[str] = []
    try:
        default = first_match(
            r'ZOLA_VERSION:=([0-9]+\.[0-9]+\.[0-9]+)',
            ROOT / "bin" / "typikon-defaults.sh",
        )
        own_gate = first_match(
            r"^\s*ZOLA_VERSION=([0-9]+\.[0-9]+\.[0-9]+)$",
            ROOT / ".github" / "workflows" / "gate-attestation.yml",
        )
        minimum = first_match(
            r'^min_version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"$',
            ROOT / "theme.toml",
        )
    except ValueError as exc:
        return [str(exc)]

    if version_tuple(default) < (0, 23, 0):
        failures.append(
            f"bin/typikon-defaults.sh: Zola {default} predates the Tera 2 runtime"
        )
    if own_gate != default:
        failures.append(
            f".github/workflows/gate-attestation.yml pins {own_gate}, default is {default}"
        )
    if minimum != default:
        failures.append(f"theme.toml min_version is {minimum}, default is {default}")

    hash_paths = [
        ROOT / ".github" / "workflows" / "gate-attestation.yml",
        ROOT / "ci" / "github-workflow.yml.tmpl",
        ROOT / "ci" / "kanon-ci.toml.tmpl",
    ]
    hashes: list[tuple[Path, str]] = []
    for path in hash_paths:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"ZOLA_SHA256(?::|=)\s*([0-9a-f]{64})", text)
        if not match:
            failures.append(f"{path.relative_to(ROOT)}: missing 64-hex ZOLA_SHA256")
            continue
        hashes.append((path, match.group(1)))
    if len({value for _, value in hashes}) > 1:
        detail = ", ".join(f"{path.relative_to(ROOT)}={value}" for path, value in hashes)
        failures.append(f"Zola artifact hashes disagree: {detail}")

    for path in (ROOT / "ci" / "github-workflow.yml.tmpl", ROOT / "ci" / "kanon-ci.toml.tmpl"):
        if "{{ ZOLA_VERSION }}" not in path.read_text(encoding="utf-8"):
            failures.append(f"{path.relative_to(ROOT)}: missing canonical ZOLA_VERSION placeholder")

    return failures


def check_template_dialect() -> list[str]:
    failures: list[str] = []
    definitions: dict[str, Path] = {}
    shortcodes = ROOT / "templates" / "shortcodes"
    if shortcodes.is_dir() and any(path.is_file() for path in shortcodes.rglob("*")):
        failures.append(
            "templates/shortcodes: Zola 0.23 removed shortcodes; migrate them to Tera 2 components"
        )

    for path in sorted((ROOT / "templates").rglob("*")):
        if not path.is_file() or path.suffix not in TEMPLATE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {label}: {match.group(0)!r}")
        for match in re.finditer(r"\{%[-+]?\s*component\s+([A-Za-z_][A-Za-z0-9_.]*)", text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            if not name.startswith("typikon."):
                failures.append(
                    f"{path.relative_to(ROOT)}:{line}: component {name!r} lacks typikon namespace"
                )
            if name in definitions:
                failures.append(
                    f"{path.relative_to(ROOT)}:{line}: duplicate component {name!r}; first in "
                    f"{definitions[name].relative_to(ROOT)}"
                )
            else:
                definitions[name] = path
        for match in re.finditer(r"\{\{[-+]?\s*<([A-Za-z_][A-Za-z0-9_.]*)", text):
            name = match.group(1)
            if not name.startswith("typikon."):
                line = text.count("\n", 0, match.start()) + 1
                failures.append(
                    f"{path.relative_to(ROOT)}:{line}: component call {name!r} lacks typikon namespace"
                )
    return failures


def main() -> int:
    failures = [
        *check_pattern_witnesses(),
        *check_pin_coherence(),
        *check_template_dialect(),
    ]
    if failures:
        for failure in failures:
            print(f"check-tera2-contract: {failure}", file=sys.stderr)
        return 1
    print("check-tera2-contract: ok (pin/hash coherence and Tera 2 source dialect)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
