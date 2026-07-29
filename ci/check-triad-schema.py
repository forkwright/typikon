#!/usr/bin/env python3
"""check-triad-schema — regression test for extra.triad cardinality."""

# WHY: schemas/section.schema.json used to validate `greek` and `english`
# independently at 2-4 items with no equal-cardinality constraint.
# templates/index.html indexes english[loop.index0] for every greek entry,
# and static/js/triad.js + the .triad-1/.triad-2/.triad-3 CSS rules are
# hard-coded for exactly three terms. A schema-valid mismatched-cardinality
# fixture (e.g. 4 greek / 2 english) passed bin/typikon-validate and then
# failed Zola's render with an out-of-bounds index. Fixed by pinning both
# arrays to minItems=maxItems=3. This script proves the fixture that used
# to slip through validation is now rejected at the schema boundary, and
# that a valid three-term triad still passes.
#
# NOTE: runs standalone (no consumer site needed) as part of ci/run-fixtures.sh.

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

THEME_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((THEME_ROOT / "schemas" / "section.schema.json").read_text(encoding="utf-8"))


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
    validator = Draft202012Validator(SCHEMA)
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
