#!/usr/bin/env python3
"""check-home-heading — regression test for the home-route <h1> assertion in
ci/smoke/shared.spec.ts (forkwright/typikon#142), and for the build-time
guard in templates/partials/assert.html's `typikon.assert.no_h1` component
(forkwright/typikon#152).

Runs the real `zola build` against ISOLATED COPIES of this theme's
templates/static/theme.toml (never the live checkout in place, so this
is safe to run concurrently and never leaves the working tree mutated) to
prove both directions of each of the two failure modes the review of #152
identified. A check nobody has watched fail is an unverified claim:

1. MISSING heading (the defect #142 itself filed). With the
   `<h1 class="sr-only">` line stripped from a COPY of templates/index.html
   (simulating a future template edit regressing it), a built home page
   must have ZERO <h1> elements. Proves the shared.spec.ts assertion
   (`page.locator('h1').toHaveCount(1)`) has something to catch — Playwright
   renders static, unmutated HTML for this route, so counting `<h1` in
   Zola's own build output is a faithful stand-in for what that locator
   would see, matching this repo's existing check-asset-provenance.py
   pattern of exercising the real render path instead of a browser.
   Paired against the SAME templates unmodified, which must produce
   exactly ONE <h1> — the positive case restored.

2. DUPLICATE heading (the review finding on #152: the unconditional
   `{{ section.content | safe }}` render below the sr-only <h1> can itself
   contribute an <h1> when a consumer's home content body starts with a
   markdown `# ` line, Zola's own leading-heading convention). Against the
   THEME AS SHIPPED (guard included), a home page whose body starts with
   `# ` must make the zola build FAIL LOUDLY (the `no_h1` guard firing),
   never silently ship two <h1> elements. Paired against a body starting
   with `##` (a consumer's escape hatch) and a body with no markdown at
   all, both of which must build clean with exactly one <h1>.

NOTE: runs standalone (no consumer site or playwright/browser needed) as
part of ci/run-fixtures.sh, alongside check-asset-provenance.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
ZOLA = shutil.which("zola")

# WHY these exact [extra] fields (not a minimal guess): mirrors
# examples/sample-blog/config.toml, which is the theme's own proof that
# this shape builds clean — a hand-trimmed config risks passing for the
# wrong reason (missing a typikon.assert.required field this template does not
# actually reach) rather than proving the heading behavior under test.
CONFIG_TOML = """title = "Fixture"
description = "typikon home-heading regression fixture"
base_url = "https://fixture.example.com"
default_language = "en"
output_dir = "public"
theme = "typikon"

[extra]
brand_name = "Fixture"
brand_greek = "Δοκιμή"
logo_path = "img/logo.svg"
theme_color = "#FBF7EC"
og_locale = "en_US"
founding_date = "2026"

[extra.author]
name = "Fixture Author"
uri = "https://fixture.example.com/about/"
"""

H1_RE = re.compile(r"<h1[ >]", re.IGNORECASE)


def copy_theme(dest: Path) -> None:
    # NOTE: sass/ was removed as an empty reservation (forkwright/typikon#99).
    # The loop still skips anything absent, so a future sass/ needs no edit here.
    for item in ("templates", "static", "theme.toml"):
        src = THEME_ROOT / item
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dest / item)
        else:
            shutil.copy2(src, dest / item)


def make_site(root: Path, theme_dir: Path, body: str) -> Path:
    site = root / "site"
    (site / "content").mkdir(parents=True)
    (site / "themes").mkdir()
    (site / "themes" / "typikon").symlink_to(theme_dir, target_is_directory=True)
    (site / "config.toml").write_text(CONFIG_TOML)
    frontmatter = '+++\ntitle = "Fixture"\n\n[extra]\nbody_class = "home-page"\n+++\n'
    (site / "content" / "_index.md").write_text(frontmatter + body)
    return site


def zola_build(site: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ZOLA, "build"],
        cwd=site,
        capture_output=True,
        text=True,
        check=False,
    )


def h1_count(site: Path) -> int:
    html = (site / "public" / "index.html").read_text()
    return len(H1_RE.findall(html))


def strip_h1_line(theme_dir: Path) -> None:
    """Simulate a future regression: remove the sr-only <h1> from a COPY."""
    index_html = theme_dir / "templates" / "index.html"
    text = index_html.read_text()
    new_text = re.sub(r'\n\s*<h1 class="sr-only">.*?</h1>\n', "\n", text)
    if new_text == text:
        raise RuntimeError(
            "strip_h1_line: pattern did not match templates/index.html — "
            "the sr-only <h1> line's shape changed; update this fixture"
        )
    index_html.write_text(new_text)


def main() -> int:
    # WHY a hard failure, not a skip (forkwright/typikon#49's precedent, cited
    # in bin/typikon-check's own docstring): ci/run-fixtures.sh has no "dev
    # mode" — every invocation is the gate. zola is installed unconditionally
    # before this script runs (.github/workflows/gate-attestation.yml, before
    # the `ci/run-fixtures.sh` line), so its absence here means the install
    # step broke, not that this check is optional. A green run must mean the
    # instrument ran, never that it was quietly unavailable.
    if ZOLA is None:
        print("check-home-heading: FAIL — zola not on PATH (see gate-attestation.yml's install step)", file=sys.stderr)
        return 1

    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="typikon-home-heading-") as tmp:
        root = Path(tmp)

        # ── Case 1: missing heading (forkwright/typikon#142) ──────────
        good_theme = root / "theme-good"
        copy_theme(good_theme)

        bad_theme = root / "theme-missing-h1"
        copy_theme(bad_theme)
        strip_h1_line(bad_theme)

        bad_site = make_site(root / "case1-bad", bad_theme, body="")
        result = zola_build(bad_site)
        if result.returncode != 0:
            failures.append(
                "case1(missing-h1, bad-fixture): expected a clean build "
                "(the assertion under test is <h1> COUNT, not build success) "
                f"but zola exited {result.returncode}:\n{result.stderr}"
            )
        else:
            n = h1_count(bad_site)
            if n != 0:
                failures.append(
                    "case1(missing-h1, bad-fixture): expected 0 <h1> elements "
                    f"with the sr-only heading stripped, got {n} — the fixture "
                    "did not actually simulate the regression; this proves "
                    "NOTHING about the real check"
                )
            else:
                print("check-home-heading: case1 bad-fixture confirmed 0 <h1> (regression reproduced)")

        good_site = make_site(root / "case1-good", good_theme, body="")
        result = zola_build(good_site)
        if result.returncode != 0:
            failures.append(
                f"case1(missing-h1, good-fixture): unmodified templates failed to build:\n{result.stderr}"
            )
        else:
            n = h1_count(good_site)
            if n != 1:
                failures.append(
                    "case1(missing-h1, good-fixture): expected exactly 1 <h1> "
                    f"from unmodified templates/index.html, got {n}"
                )
            else:
                print("check-home-heading: case1 good-fixture confirmed exactly 1 <h1> (positive case holds)")

        # ── Case 2: duplicate heading (forkwright/typikon#152 review) ─
        dup_site = make_site(root / "case2-dup", good_theme, body="# Leading heading\n\nBody copy.\n")
        result = zola_build(dup_site)
        if result.returncode == 0:
            n = h1_count(dup_site)
            failures.append(
                "case2(duplicate-h1): a home content body starting with `# ` "
                "was expected to fail the build via the no_h1 guard, but zola "
                f"exited 0 with {n} <h1> element(s) — the guard did not fire"
            )
        elif "no_h1" not in result.stderr and "collides with this page's required heading" not in result.stderr:
            failures.append(
                "case2(duplicate-h1): build failed as expected but not via the "
                f"no_h1 guard (got a different error) — the guard may not be wired:\n{result.stderr}"
            )
        else:
            print("check-home-heading: case2 confirmed the no_h1 guard fails the build on a colliding body")

        subheading_site = make_site(root / "case2-sub", good_theme, body="## A subheading is fine\n\nBody copy.\n")
        result = zola_build(subheading_site)
        if result.returncode != 0:
            failures.append(
                f"case2(subheading escape hatch): a body starting with `##` must build clean:\n{result.stderr}"
            )
        else:
            n = h1_count(subheading_site)
            if n != 1:
                failures.append(
                    "case2(subheading escape hatch): expected exactly 1 <h1> "
                    f"(the sr-only one; body's own heading is h2), got {n}"
                )
            else:
                print("check-home-heading: case2 subheading-only fixture confirmed exactly 1 <h1>")

    if failures:
        print("check-home-heading: FAIL", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("check-home-heading: ok (4/4 fixtures behaved as required)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
