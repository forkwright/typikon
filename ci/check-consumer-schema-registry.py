#!/usr/bin/env python3
"""check-consumer-schema-registry — regression test for the fail-closed
consumer schema registry (forkwright/typikon#60).

WHY: before this registry existed, a consumer site's custom-templated
content (a page type typikon does not ship, e.g. an "our approach" or
"case study" template) fell through `bin/typikon-validate`'s classifier to
`page.schema.json`, whose `extra` object accepted any additional field
without checking its type. A typo like `kanon_ci = "false"` (string, not
boolean) was schema-valid and became truthy wherever a consumer template
did `bool(...)` on it. This script proves three things bin/typikon-validate
itself cannot self-certify by import (it has no test suite of its own):

1. A template registered in schemas/registry.toml validates against its
   own composed schema — namespaced fields are checked, not ignored.
2. A wrong-typed or unrecognized field under a registered template's
   `extra` is REJECTED, not silently coerced — the exact defect #60 reports.
3. A custom `template` value with NO registry.toml entry FAILS validation
   with the exact missing-registration error, rather than silently
   inheriting page.schema.json's shape. This is the fail-closed guarantee:
   the absence of a registration is itself a defect, not a fallback.

Every case builds a throwaway consumer-site tree under a tempdir and runs
the real `bin/typikon-validate` CLI as a subprocess — this exercises the
actual classification + registry-loading + composed-schema-validation
path end to end, not a mocked slice of it.

NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
VALIDATE = THEME_ROOT / "bin" / "typikon-validate"

CONSULTING_SCHEMA = """\
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ardent.tools/schemas/consulting.schema.json",
  "title": "ardent consulting page",
  "allOf": [{"$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json"}],
  "properties": {
    "extra": {
      "allOf": [{"$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json#/properties/extra"}],
      "unevaluatedProperties": false,
      "properties": {
        "ardent": {
          "type": "object",
          "additionalProperties": false,
          "required": ["kanon_ci"],
          "properties": {"kanon_ci": {"type": "boolean"}}
        }
      }
    }
  },
  "unevaluatedProperties": false
}
"""

DOSSIER_SCHEMA = """\
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ardent.tools/schemas/system-dossier.schema.json",
  "title": "ardent system dossier page",
  "allOf": [{"$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json"}],
  "properties": {
    "extra": {
      "allOf": [{"$ref": "https://github.com/forkwright/typikon/schemas/page.core.schema.json#/properties/extra"}],
      "unevaluatedProperties": false,
      "properties": {
        "ardent": {
          "type": "object",
          "additionalProperties": false,
          "required": ["repo_url"],
          "properties": {"repo_url": {"type": "string"}}
        }
      }
    }
  },
  "unevaluatedProperties": false
}
"""

REGISTRY_TOML = """\
[[entry]]
template = "consulting.html"
schema = "schemas/consulting.schema.json"
extends = "page"

[[entry]]
path_prefix = "systems/"
schema = "schemas/system-dossier.schema.json"
extends = "page"
"""


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def run_validate(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE), str(root)],
        capture_output=True, text=True, check=False,
    )


BASE_FILES = {
    "schemas/registry.toml": REGISTRY_TOML,
    "schemas/consulting.schema.json": CONSULTING_SCHEMA,
    "schemas/system-dossier.schema.json": DOSSIER_SCHEMA,
}


def content_only(files: dict[str, str]) -> dict[str, str]:
    return {**BASE_FILES, **files}


# Each case: (label, extra_files, expected_exit, required_stderr_substrings)
CASES: list[tuple[str, dict[str, str], int, list[str]]] = [
    (
        "registered template, valid namespaced field — passes",
        content_only({
            "content/consulting.md": (
                '+++\ntitle = "Consulting"\ntemplate = "consulting.html"\n\n'
                '[extra.ardent]\nkanon_ci = true\n+++\nbody\n'
            ),
        }),
        0,
        [],
    ),
    (
        "registered template, wrong-typed namespaced field — the exact #60 defect, rejected",
        content_only({
            "content/consulting.md": (
                '+++\ntitle = "Consulting"\ntemplate = "consulting.html"\n\n'
                '[extra.ardent]\nkanon_ci = "false"\n+++\nbody\n'
            ),
        }),
        1,
        ["'false' is not of type 'boolean'"],
    ),
    (
        "registered template, unrecognized extra field — rejected, not silently accepted",
        content_only({
            "content/consulting.md": (
                '+++\ntitle = "Consulting"\ntemplate = "consulting.html"\n\n'
                '[extra]\nbogus_field = "x"\n\n[extra.ardent]\nkanon_ci = true\n+++\nbody\n'
            ),
        }),
        1,
        ["bogus_field", "not allowed"],
    ),
    (
        "unregistered custom template — fails closed with the exact missing-registration error",
        content_only({
            "content/home.md": '+++\ntitle = "Home"\ntemplate = "home.html"\n+++\nbody\n',
        }),
        1,
        ["custom template 'home.html'", "schemas/registry.toml", "docs/SCHEMAS.md#consumer-schema-registry"],
    ),
    (
        "path_prefix discriminator, valid — passes",
        content_only({
            "content/systems/dossier.md": (
                '+++\ntitle = "Dossier"\n\n[extra.ardent]\nrepo_url = "https://github.com/x/y"\n+++\nbody\n'
            ),
        }),
        0,
        [],
    ),
    (
        "path_prefix discriminator, missing required namespaced field — rejected",
        content_only({
            "content/systems/dossier.md": (
                '+++\ntitle = "Dossier"\n\n[extra.ardent]\n+++\nbody\n'
            ),
        }),
        1,
        ["'repo_url' is a required property"],
    ),
    (
        "typikon's own shipped template with no registry entry — not a fail-closed trigger",
        content_only({
            "content/plain.md": '+++\ntitle = "Plain"\ntemplate = "page.html"\n+++\nbody\n',
        }),
        0,
        [],
    ),
    (
        "no registry.toml at all — unchanged pre-#60 behavior for a consumer with no custom templates",
        {"content/plain.md": '+++\ntitle = "Plain"\n+++\nbody\n'},
        0,
        [],
    ),
    (
        "malformed registry: both template and path_prefix on one entry — refused at load time",
        {
            "schemas/registry.toml": REGISTRY_TOML + (
                '\n[[entry]]\ntemplate = "x.html"\npath_prefix = "y/"\n'
                'schema = "schemas/consulting.schema.json"\nextends = "page"\n'
            ),
            "schemas/consulting.schema.json": CONSULTING_SCHEMA,
            "schemas/system-dossier.schema.json": DOSSIER_SCHEMA,
            "content/plain.md": '+++\ntitle = "Plain"\n+++\nbody\n',
        },
        2,
        ["must set exactly one of"],
    ),
    (
        "malformed registry: extends names a non-composable slug — refused at load time",
        {
            "schemas/registry.toml": (
                '[[entry]]\ntemplate = "consulting.html"\n'
                'schema = "schemas/consulting.schema.json"\nextends = "product"\n'
            ),
            "schemas/consulting.schema.json": CONSULTING_SCHEMA,
            "content/plain.md": '+++\ntitle = "Plain"\n+++\nbody\n',
        },
        2,
        ["extends = 'product'", "composable"],
    ),
    (
        "malformed registry: referenced schema file does not exist — refused at load time",
        {
            "schemas/registry.toml": (
                '[[entry]]\ntemplate = "consulting.html"\n'
                'schema = "schemas/missing.schema.json"\nextends = "page"\n'
            ),
            "content/plain.md": '+++\ntitle = "Plain"\n+++\nbody\n',
        },
        2,
        ["schema file not found"],
    ),
    (
        "malformed registry: consumer schema missing $id — refused at load time",
        {
            "schemas/registry.toml": (
                '[[entry]]\ntemplate = "consulting.html"\n'
                'schema = "schemas/consulting.schema.json"\nextends = "page"\n'
            ),
            "schemas/consulting.schema.json": json.dumps({"type": "object"}),
            "content/plain.md": '+++\ntitle = "Plain"\n+++\nbody\n',
        },
        2,
        ["must declare"],
    ),
    (
        "malformed registry: duplicate template discriminator — refused at load time",
        {
            "schemas/registry.toml": REGISTRY_TOML + (
                '\n[[entry]]\ntemplate = "consulting.html"\n'
                'schema = "schemas/system-dossier.schema.json"\nextends = "page"\n'
            ),
            "schemas/consulting.schema.json": CONSULTING_SCHEMA,
            "schemas/system-dossier.schema.json": DOSSIER_SCHEMA,
            "content/plain.md": '+++\ntitle = "Plain"\n+++\nbody\n',
        },
        2,
        ["duplicate template discriminator"],
    ),
]


def main() -> int:
    failed = []
    for label, files, expected_exit, required_substrings in CASES:
        with tempfile.TemporaryDirectory(prefix="typikon-registry-check-") as tmp:
            root = Path(tmp)
            write_tree(root, files)
            result = run_validate(root)
            if result.returncode != expected_exit:
                failed.append(
                    f"{label}: expected exit {expected_exit}, got {result.returncode}\n"
                    f"  stdout: {result.stdout.strip()}\n  stderr: {result.stderr.strip()}"
                )
                continue
            missing = [s for s in required_substrings if s not in result.stderr]
            if missing:
                failed.append(f"{label}: stderr missing expected substring(s) {missing}\n  stderr: {result.stderr.strip()}")

    if failed:
        for line in failed:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(json.dumps({"checked": len(CASES), "passed": len(CASES), "failed": 0}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
