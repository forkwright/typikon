#!/usr/bin/env python3
"""check-triad-schema — regression test for extra.triad cardinality."""

# WHY: templates/index.html indexes english[loop.index0] for every greek
# entry, and static/js/triad.js + the .triad-1/.triad-2/.triad-3 CSS rules
# are hard-coded for exactly three terms. schemas/section.schema.json must
# therefore constrain both greek and english to minItems=maxItems=3 — a
# schema that validated them independently would admit a mismatched-
# cardinality fixture that passes bin/typikon-validate and then fails
# Zola's render with an out-of-bounds index. This script proves a
# mismatched-cardinality fixture is rejected at the schema boundary, and
# that a valid three-term triad still passes.
#
# NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

THEME_ROOT = Path(__file__).resolve().parent.parent

# WHY importlib, not a normal import: bin/typikon-validate has no .py suffix
# (it's a CLI entry point, not a package module). Its load_schemas() is the
# SSOT for turning schemas/section.schema.json's internal $ref into
# something jsonschema can actually resolve — section.schema.json composes
# section.core.schema.json via $ref (forkwright/typikon#60), so constructing
# a bare Draft202012Validator(json.load(...)) here would raise Unresolvable
# the moment a triad case reached that $ref, independent of the case data.
_loader = importlib.machinery.SourceFileLoader("typikon_validate", str(THEME_ROOT / "bin" / "typikon-validate"))
_spec = importlib.util.spec_from_loader("typikon_validate", _loader)
_typikon_validate = importlib.util.module_from_spec(_spec)
sys.modules["typikon_validate"] = _typikon_validate  # dataclass() resolves types via sys.modules[__module__]
_spec.loader.exec_module(_typikon_validate)

_SCHEMAS, _REGISTRY = _typikon_validate.load_schemas()
SCHEMA = _SCHEMAS["section"]


def section_with_triad(triad: dict) -> dict:
    return {"title": "Home", "extra": {"triad": triad}}


CASES = [
    (
        "valid three-term triad",
        section_with_triad({"greek": ["χείρ", "μνήμη", "προσοχή"], "english": ["hand", "memory", "attention"]}),
        True,
    ),
    (
        "mismatched cardinality (4 greek / 2 english) — the exact reported regression",
        section_with_triad({"greek": ["a", "b", "c", "d"], "english": ["x", "y"]}),
        False,
    ),
    (
        "uniform two-term triad — schema-valid before this fix, contradicts triad.js/CSS three-term lifecycle",
        section_with_triad({"greek": ["a", "b"], "english": ["x", "y"]}),
        False,
    ),
    (
        "uniform four-term triad — schema-valid before this fix, contradicts triad.js/CSS three-term lifecycle",
        section_with_triad({"greek": ["a", "b", "c", "d"], "english": ["w", "x", "y", "z"]}),
        False,
    ),
]


def main() -> int:
    validator = Draft202012Validator(SCHEMA, registry=_REGISTRY)
    failed = []
    for label, doc, should_be_valid in CASES:
        errors = list(validator.iter_errors(doc))
        is_valid = not errors
        if is_valid != should_be_valid:
            want = "valid" if should_be_valid else "invalid"
            got = "valid" if is_valid else "invalid"
            failed.append(f"{label}: expected {want}, got {got}")

    if failed:
        for line in failed:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(json.dumps({"checked": len(CASES), "passed": len(CASES), "failed": 0}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
