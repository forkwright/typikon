#!/usr/bin/env python3
"""check-interactive-contrast-selftest — regression test for
ci/check-interactive-contrast.py.

WHY this file exists: the PR that added the class-level #64 fix claimed a
mutation-testing narrative in its own body ("I ran both versions against
five separate mutations ... a reviewer can reproduce any of these with
sed -i ...") but never committed it as a fixture — it was run by hand,
once. A gate that has never watched its own checker fail is an unverified
claim wearing a verdict's clothes. This file turns that manual recipe into
something CI re-runs on every push.

Two kinds of proof, mirroring how the underlying bug was actually found:

PART A (function-level, synthetic CSS, no file I/O): loads
check-interactive-contrast.py via importlib and calls find_declared_var()
directly against small CSS snippets built to exercise the exact defect
class this checker's own review caught — an unanchored property regex
that lets prop_alt="color" match the "color:" substring inside
"background-color:"/"text-decoration-color:"/etc. and silently resolve
the WRONG property's value. These are fast and deterministic, and they
fail the moment the anchor regresses even though no real style.css rule
happens to exercise the bug today (the review found it by luck-of-source-
order, not by any live failure).

PART B (end-to-end, real files, restore-guaranteed): mutates the ACTUAL
static/css/style.css and/or static/css/skins/leather.css the same way a
future regression would, runs check-interactive-contrast.py as a real
subprocess against them, asserts the expected failure, then restores the
original bytes of both in a `finally` and re-verifies the restore is
byte-identical before declaring success. This is the #64 regression and
the coverage-scan gap from the PR body's own five-mutation list, now
committed instead of hand-typed. The #64 mutation targets the skin file
specifically (forkwright/typikon#55 moved the dye-token mapping there;
see check-interactive-contrast.py's FIRST_PARTY_SKINS).

NOTE: runs standalone (no consumer site or zola build needed) as part of
ci/run-fixtures.sh. Order relative to check-interactive-contrast.py in that
run is NOT guaranteed (forkwright/typikon#169: the runner discovers
ci/check-*.py alphabetically rather than declaring an order, and
"-selftest.py" sorts before ".py") -- harmless here because Part B invokes
check-interactive-contrast.py itself as a real subprocess against a
guaranteed-restored file rather than depending on a prior run's state.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

CI_DIR = Path(__file__).resolve().parent
THEME_ROOT = CI_DIR.parent
CHECK_SCRIPT = CI_DIR / "check-interactive-contrast.py"
STYLE_CSS = THEME_ROOT / "static" / "css" / "style.css"
# The #64 regression's actual token mapping lives here since
# forkwright/typikon#55 split the dye palette out of core — see that
# skin's own :root block.
LEATHER_SKIN_CSS = THEME_ROOT / "static" / "css" / "skins" / "leather.css"


def _load_check_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_interactive_contrast", CHECK_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load a module spec from {CHECK_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_check() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )


# --- Part A: property-regex boundary (function-level, synthetic) ----------


def _part_a(mod: ModuleType, failures: list[str]) -> None:
    # A1 — the exact bug: prop_alt="color" must NOT match inside
    # "background-color:". Before the fix this returned "danger".
    css = ".widget { background-color: var(--danger); }"
    result = mod.find_declared_var(css, ".widget", "color")
    if result is not None:
        failures.append(
            "A1: find_declared_var(prop_alt='color') matched inside "
            f"'background-color:' and returned {result!r} instead of None — "
            "the property regex has regressed to being unanchored"
        )

    # A2 — a genuine `color:` declaration must still resolve (an
    # over-broad anchor would break the common case instead of the bug).
    css = ".widget { color: var(--text); }"
    result = mod.find_declared_var(css, ".widget", "color")
    if result != "text":
        failures.append(
            "A2: find_declared_var(prop_alt='color') failed to resolve a "
            f"genuine 'color:' declaration (got {result!r}, want 'text')"
        )

    # A3 — the real reviewer repro: reorder style.css's actual `a { ... }`
    # rule (text-decoration-color before color) and confirm resolution
    # still lands on the real `color` token, not the decoration one.
    css = "a { text-decoration-color: var(--rule); color: var(--text); }"
    token, _via = mod.resolve_chain(css, ["a"], "color")
    if token != "text":
        failures.append(
            f"A3: resolve_chain on a reordered a{{}} rule resolved 'color' "
            f"to {token!r}, not 'text' — text-decoration-color leaked "
            "through the boundary"
        )

    # A4 — the same boundary class in _prop_inherit_re: a body with only
    # `background-color: inherit;` (no real `color` declaration at all)
    # must resolve to None, not the INHERIT_SENTINEL.
    css = ".widget { background-color: inherit; }"
    result = mod.find_declared_var(css, ".widget", "color")
    if result is not None:
        failures.append(
            "A4: find_declared_var(prop_alt='color') treated "
            "'background-color: inherit;' as if `color` itself were "
            f"declared inherit (got {result!r}, want None)"
        )

    # A5 — the alternation form used for backgrounds ("background|"
    # "background-color") must still resolve background-color correctly
    # now that a boundary sits in front of the whole group.
    css = ".widget { background-color: var(--bg-accent); }"
    result = mod.find_declared_var(css, ".widget", "background|background-color")
    if result != "bg-accent":
        failures.append(
            "A5: find_declared_var(prop_alt='background|background-color') "
            f"failed to resolve background-color (got {result!r}, want "
            "'bg-accent') — the anchor broke the alternation case"
        )


# --- Part B: end-to-end, real file, restore-guaranteed --------------------


def _part_b(failures: list[str]) -> None:
    original = STYLE_CSS.read_bytes()
    original_text = original.decode("utf-8")
    skin_original = LEATHER_SKIN_CSS.read_bytes()
    skin_original_text = skin_original.decode("utf-8")

    try:
        # B1 — the #64 regression itself, one hop deeper since
        # forkwright/typikon#55: core's .nav-links a:nth-child(3):hover
        # resolves through --accent-3, and the leather skin's OWN :root is
        # what maps --accent-3 to --aporia-interactive (not raw --aporia).
        # Reverting that mapping in the skin is the exact regression #64
        # was filed over, now expressed one level of indirection down.
        regressed_needle = "--accent-3: var(--aporia-interactive);"
        regressed_replacement = "--accent-3: var(--aporia);"
        if skin_original_text.count(regressed_needle) != 1:
            failures.append(
                "B1 setup: expected exactly one occurrence of the pre-fix "
                f"#64 mapping in {LEATHER_SKIN_CSS} to mutate; found "
                f"{skin_original_text.count(regressed_needle)} — this fixture is "
                "stale against the current source and needs updating"
            )
        else:
            LEATHER_SKIN_CSS.write_text(
                skin_original_text.replace(regressed_needle, regressed_replacement, 1),
                encoding="utf-8",
            )
            result = _run_check()
            if result.returncode != 1:
                failures.append(
                    "B1: reverting the #64 fix did not fail the gate "
                    f"(exit {result.returncode}); stderr:\n{result.stderr}"
                )
            elif "below the 4.5:1 WCAG 1.4.3 floor" not in result.stderr:
                failures.append(
                    "B1: reverting the #64 fix failed, but not with the "
                    f"expected WCAG floor message; stderr:\n{result.stderr}"
                )
            LEATHER_SKIN_CSS.write_text(skin_original_text, encoding="utf-8")

        # B2 — coverage-scan negative case: a brand-new, unreviewed
        # interactive-state color rule must fail closed, not pass silently.
        uncovered_rule = "\n.selftest-uncovered-element:hover { color: var(--text); }\n"
        STYLE_CSS.write_text(original_text + uncovered_rule, encoding="utf-8")
        result = _run_check()
        if result.returncode != 1:
            failures.append(
                "B2: an uncovered new :hover{color:...} rule did not fail "
                f"the gate (exit {result.returncode}); stderr:\n{result.stderr}"
            )
        elif ".selftest-uncovered-element:hover" not in result.stderr:
            failures.append(
                "B2: the uncovered-rule failure fired, but didn't name the "
                f"offending selector; stderr:\n{result.stderr}"
            )
        STYLE_CSS.write_text(original_text, encoding="utf-8")

    finally:
        # SAFETY: never leave the real stylesheets mutated, even if an
        # assertion above raised instead of appending to `failures`.
        STYLE_CSS.write_bytes(original)
        LEATHER_SKIN_CSS.write_bytes(skin_original)

    restored = STYLE_CSS.read_bytes()
    skin_restored = LEATHER_SKIN_CSS.read_bytes()
    if restored != original or skin_restored != skin_original:
        failures.append(
            f"B: {STYLE_CSS} and/or {LEATHER_SKIN_CSS} did not restore "
            "byte-identical after the mutation fixtures — the gate has "
            "corrupted the real stylesheet(s)"
        )
        return

    # B3 — with both files genuinely restored, the checker must pass again.
    # Proves B1/B2's failures were caused by the mutations, not by some
    # other break this fixture introduced.
    result = _run_check()
    if result.returncode != 0:
        failures.append(
            "B3: check-interactive-contrast.py did not pass against the "
            f"restored, unmodified stylesheets (exit {result.returncode}); "
            f"stderr:\n{result.stderr}"
        )


def main() -> int:
    failures: list[str] = []

    mod = _load_check_module()
    _part_a(mod, failures)
    _part_b(failures)

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print("OK: check-interactive-contrast.py's property-boundary resolver rejects a "
          "cross-property match (5 synthetic cases)")
    print("OK: check-interactive-contrast.py fails closed on the #64 regression, "
          "fails closed on an uncovered new state rule, and restores + re-passes clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
