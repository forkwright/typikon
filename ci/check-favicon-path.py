#!/usr/bin/env python3
"""check-favicon-path — regression test for base.html's favicon <link>.

WHY: templates/base.html used to hardcode `<link rel="icon" href="/img/favicon.svg">`,
so a consumer whose brand mark lives at any other path had to place a second copy at
that literal path (forkwright/typikon#110; ardent-site#12 is the filed consequence).
The fix routes the href through `config.extra.favicon_path` and `get_url()`, matching
the sibling `og_image` pattern, with a default that preserves existing consumers.

This builds a minimal fixture site against the real theme (via a `themes/typikon`
symlink to THEME_ROOT, the same shape `examples/*/themes/typikon` uses) with real
`zola build`, proving two things a template-source grep cannot:

- a consumer that never sets `favicon_path` still gets the theme's own
  `static/img/favicon.svg`, resolved through `get_url()` — unaffected by the fix;
- a consumer that sets `favicon_path` gets ITS asset rendered in the `<link>`, not
  the theme default — the actual defect (favicon_path had no effect at all);
- a consumer that sets `favicon_path` to a non-SVG asset gets a `type=` attribute
  that matches that asset's extension, not a hardcoded `image/svg+xml` — the
  second defect adversarial review found in this same PR (typikon#141 finding 2):
  making the path configurable without deriving `type` from it ships a
  MIME-type mismatch for any consumer favicon that isn't itself an SVG.

NOTE: runs standalone (no examples/ site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent

ICON_LINK_RE = re.compile(r'<link\s+rel="icon"\s+href="([^"]+)"\s+type="([^"]+)">')

BASE_CONFIG = """\
title = "Fixture"
description = "favicon_path fixture"
base_url = "https://fixture.example.com"
default_language = "en"
output_dir = "public"
theme = "typikon"

[extra]
brand_name = "Fixture"
logo_path = "img/logo.svg"
{extra_lines}
"""

INDEX_MD = """\
+++
title = "Fixture"
description = "favicon_path fixture"
template = "index.html"
+++
"""


def build_site(root: Path, extra_lines: str, favicon_asset: str | None) -> subprocess.CompletedProcess:
    (root / "themes").mkdir(parents=True)
    (root / "themes" / "typikon").symlink_to(THEME_ROOT, target_is_directory=True)
    (root / "content").mkdir()
    (root / "content" / "_index.md").write_text(INDEX_MD, encoding="utf-8")
    (root / "config.toml").write_text(BASE_CONFIG.format(extra_lines=extra_lines), encoding="utf-8")
    if favicon_asset is not None:
        img = root / "static" / "img"
        img.mkdir(parents=True, exist_ok=True)
        # WHY: content is irrelevant — only the extension drives the type=
        # derivation under test, and get_url() performs no existence check
        # (a real gap, not exercised here; see PR body).
        (img / favicon_asset).write_text("stub", encoding="utf-8")
    return subprocess.run(
        ["zola", "build"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def icon_link(root: Path) -> tuple[str, str] | None:
    """Return (href, type) of the rendered favicon <link>, or None if absent."""
    html = (root / "public" / "index.html").read_text(encoding="utf-8")
    match = ICON_LINK_RE.search(html)
    return (match.group(1), match.group(2)) if match else None


def main() -> int:
    if shutil.which("zola") is None:
        print("FAIL: zola not on PATH (required to build the favicon_path fixture)", file=sys.stderr)
        return 1

    failures: list[str] = []

    # Case 1: favicon_path unset — default must still resolve to the theme's
    # own asset with the theme's own SVG type, proving the fix leaves
    # existing consumers unaffected.
    with tempfile.TemporaryDirectory(prefix="typikon-favicon-default-") as tmp:
        root = Path(tmp)
        result = build_site(root, extra_lines="", favicon_asset=None)
        if result.returncode != 0:
            failures.append(f"default-favicon fixture: zola build failed:\n{result.stderr}")
        else:
            link = icon_link(root)
            if link is None:
                failures.append("default-favicon fixture: no <link rel=\"icon\"> found in public/index.html")
            else:
                href, mime_type = link
                if not href.endswith("/img/favicon.svg"):
                    failures.append(f"default-favicon fixture: expected href ending in /img/favicon.svg, got {href!r}")
                if not href.startswith("https://fixture.example.com/"):
                    failures.append(f"default-favicon fixture: href not resolved through get_url() against base_url, got {href!r}")
                if mime_type != "image/svg+xml":
                    failures.append(f"default-favicon fixture: expected type image/svg+xml, got {mime_type!r}")

    # Case 2: favicon_path set to a consumer SVG asset — the <link> must point
    # at THAT asset, not the theme default. This is the original defect: prior
    # to the fix, config.extra.favicon_path had no effect on the rendered href.
    with tempfile.TemporaryDirectory(prefix="typikon-favicon-custom-") as tmp:
        root = Path(tmp)
        result = build_site(root, extra_lines='favicon_path = "img/custom-favicon.svg"', favicon_asset="custom-favicon.svg")
        if result.returncode != 0:
            failures.append(f"custom-favicon fixture: zola build failed:\n{result.stderr}")
        else:
            link = icon_link(root)
            if link is None:
                failures.append("custom-favicon fixture: no <link rel=\"icon\"> found in public/index.html")
            else:
                href, mime_type = link
                if not href.endswith("/img/custom-favicon.svg"):
                    failures.append(f"custom-favicon fixture: expected href ending in /img/custom-favicon.svg, got {href!r}")
                if mime_type != "image/svg+xml":
                    failures.append(f"custom-favicon fixture: expected type image/svg+xml, got {mime_type!r}")

    # Case 3: favicon_path set to a NON-svg consumer asset (.ico) — the <link>
    # type= must follow the asset's own extension, not stay hardcoded to the
    # theme's SVG type. Adversarial review on typikon#141 found the path had
    # been made configurable while type stayed literally "image/svg+xml"; a
    # consumer pointing favicon_path at a .ico shipped a MIME-type mismatch.
    # Reverting templates/base.html's type-derivation block reproduces that:
    # this case alone goes red (href correct, type still "image/svg+xml"
    # instead of "image/x-icon") while cases 1-2 stay green, since neither of
    # them exercises a non-svg extension.
    with tempfile.TemporaryDirectory(prefix="typikon-favicon-ico-") as tmp:
        root = Path(tmp)
        result = build_site(root, extra_lines='favicon_path = "img/custom-favicon.ico"', favicon_asset="custom-favicon.ico")
        if result.returncode != 0:
            failures.append(f"ico-favicon fixture: zola build failed:\n{result.stderr}")
        else:
            link = icon_link(root)
            if link is None:
                failures.append("ico-favicon fixture: no <link rel=\"icon\"> found in public/index.html")
            else:
                href, mime_type = link
                if not href.endswith("/img/custom-favicon.ico"):
                    failures.append(f"ico-favicon fixture: expected href ending in /img/custom-favicon.ico, got {href!r}")
                if mime_type != "image/x-icon":
                    failures.append(
                        f"ico-favicon fixture: expected type image/x-icon for a .ico favicon_path, got {mime_type!r} "
                        "(MIME-type mismatch: the <link> type stayed hardcoded to the theme default "
                        "instead of following the configured asset's own extension)"
                    )

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(
        "OK: favicon <link> resolves the theme default when unset, a consumer's "
        "favicon_path when set, and a type= matching that asset's own extension"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
