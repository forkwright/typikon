#!/usr/bin/env python3
"""Keep Typikon's Zola pin and template dialect internally coherent.

Zola 0.23 moved to Tera 2. A version-only bump is not a migration: Tera 1
macros/imports, namespace calls, several filters, and positional test arguments
all fail when Zola compiles the theme. This static check catches those known
incompatibilities before the public GitHub gate downloads Zola and renders the
fixtures. It does not replace that renderer proof.
"""

from __future__ import annotations

import copy
import json
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
    "unsupported Tera 2 date format": re.compile(r'date\(format="%\+"\)'),
}

PATTERN_WITNESSES = {
    "Tera 1 macro/import tag": '{% import "partials/assert.html" as assert %}',
    "Tera 1 namespace call": "assert::required(ok=true)",
    "removed collection filter": "items | concat(with=item)",
    "removed string filter": "value | escape",
    "renamed trim filter": 'value | trim_end_matches(pat="/")',
    "positional Tera 2 test argument": 'value is ending_with(".svg")',
    "unsupported Tera 2 date format": 'value | date(format="%+")',
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
        # WHY the lock rather than bin/typikon-defaults.sh: that file now
        # DERIVES its value from ci/tool-lock.toml (forkwright/typikon#58), so
        # grepping it would read a copy of the answer instead of the answer.
        default = first_match(
            r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$',
            ROOT / "ci" / "tool-lock.toml",
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
            f"ci/tool-lock.toml: Zola {default} predates the Tera 2 runtime"
        )
    if own_gate != default:
        failures.append(
            f".github/workflows/gate-attestation.yml pins {own_gate}, the lock says {default}"
        )
    if minimum != default:
        failures.append(f"theme.toml min_version is {minimum}, the lock says {default}")

    # WHY this no longer compares copies of the hash across the templates:
    # they no longer hold one. Both carry {{ ZOLA_SHA256 }} and are rendered
    # from ci/tool-lock.toml, so "the copies agree" became unrepresentable
    # rather than merely true -- which is the point of forkwright/typikon#58.
    # What remains checkable is that the one surface which CANNOT be generated,
    # typikon's own gate workflow, still matches the lock.
    artifact_hash = first_match(r'^sha256 = "([0-9a-f]{64})"$', ROOT / "ci" / "tool-lock.toml")
    own_gate_hash_path = ROOT / ".github" / "workflows" / "gate-attestation.yml"
    own_gate_hash = re.search(
        r"ZOLA_SHA256(?::|=)\s*([0-9a-f]{64})",
        own_gate_hash_path.read_text(encoding="utf-8"),
    )
    if not own_gate_hash:
        failures.append(f"{own_gate_hash_path.relative_to(ROOT)}: missing 64-hex ZOLA_SHA256")
    elif own_gate_hash.group(1) != artifact_hash:
        failures.append(
            f"{own_gate_hash_path.relative_to(ROOT)} pins Zola sha256 "
            f"{own_gate_hash.group(1)}, the lock says {artifact_hash}"
        )

    try:
        inventory = json.loads(
            (ROOT / "release" / "components.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"release/components.json: cannot read Zola inventory: {exc}")
    else:
        failures.extend(check_inventory_zola_pin(inventory, default, artifact_hash))

    # Both generated surfaces must carry the PLACEHOLDERS, not literals: a
    # literal reintroduced here is a copy that can drift, which is exactly what
    # the lock removed.
    for path in (ROOT / "ci" / "github-workflow.yml.tmpl", ROOT / "ci" / "kanon-ci.toml.tmpl"):
        text = path.read_text(encoding="utf-8")
        for placeholder in ("{{ ZOLA_VERSION }}", "{{ ZOLA_SHA256 }}"):
            if placeholder not in text:
                failures.append(f"{path.relative_to(ROOT)}: missing canonical {placeholder} placeholder")
        if re.search(r"ZOLA_SHA256(?::|=)\s*[0-9a-f]{64}", text):
            failures.append(
                f"{path.relative_to(ROOT)}: carries a literal Zola sha256; it must render "
                "from ci/tool-lock.toml so the version and the checksum cannot drift apart"
            )

    return failures


def check_inventory_zola_pin(
    inventory: object, version: str, artifact_hash: str
) -> list[str]:
    if not isinstance(inventory, dict) or not isinstance(
        inventory.get("components"), list
    ):
        return ["release/components.json: components must be an array"]
    rows = [
        row
        for row in inventory["components"]
        if isinstance(row, dict) and row.get("name") == "zola"
    ]
    if len(rows) != 1:
        return ["release/components.json: expected exactly one zola component"]
    row = rows[0]
    expected_url = (
        "https://github.com/getzola/zola/releases/download/"
        f"v{version}/zola-v{version}-x86_64-unknown-linux-gnu.tar.gz"
    )
    expected = {
        "version": version,
        "purl": f"pkg:github/getzola/zola@{version}?arch=x86_64&os=linux",
        "hash": {
            "kind": "external-distribution",
            "url": expected_url,
            "sha256": artifact_hash,
        },
    }
    actual = {key: row.get(key) for key in expected}
    if actual != expected:
        return [
            "release/components.json: Zola distribution differs from the runtime pin: "
            f"{actual!r} != {expected!r}"
        ]
    return []


def check_inventory_pin_witness() -> list[str]:
    """Prove a drifted inventory digest is rejected by the coherence check."""
    try:
        inventory = json.loads(
            (ROOT / "release" / "components.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    mutated = copy.deepcopy(inventory)
    for row in mutated.get("components", []):
        if isinstance(row, dict) and row.get("name") == "zola":
            row.get("hash", {})["sha256"] = "0" * 64
    # WHY the expected pair is read from the lock rather than written here: a
    # witness carrying its own copy of the version and digest is one more place
    # the fact lives, and it would keep "proving" detection against a pair the
    # repository no longer uses.
    try:
        version = first_match(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', ROOT / "ci" / "tool-lock.toml")
        digest = first_match(r'^sha256 = "([0-9a-f]{64})"$', ROOT / "ci" / "tool-lock.toml")
    except ValueError as exc:
        return [f"cannot read the Zola pin from ci/tool-lock.toml: {exc}"]
    if not check_inventory_zola_pin(mutated, version, digest):
        return ["internal Zola inventory detector accepted a drifted artifact digest"]
    return []


def check_xml_preamble() -> list[str]:
    """Keep the XML declaration at the first byte of the Atom template source."""
    atom = ROOT / "templates" / "atom.xml"
    declaration = b'<?xml version="1.0" encoding="UTF-8"?>'
    if not atom.read_bytes().startswith(declaration):
        return [
            "templates/atom.xml: XML declaration must begin at byte zero; "
            "leading template whitespace renders an invalid feed"
        ]
    return []


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
        *check_inventory_pin_witness(),
        *check_pin_coherence(),
        *check_xml_preamble(),
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
