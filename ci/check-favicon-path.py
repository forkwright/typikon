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
  the theme default — the actual defect (favicon_path had no effect at all).

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

ICON_LINK_RE = re.compile(r'<link\s+rel="icon"\s+href="([^"]+)"[^>]*>')

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


def build_site(root: Path, extra_lines: str, custom_favicon: bool) -> subprocess.CompletedProcess:
    (root / "themes").mkdir(parents=True)
    (root / "themes" / "typikon").symlink_to(THEME_ROOT, target_is_directory=True)
    (root / "content").mkdir()
    (root / "content" / "_index.md").write_text(INDEX_MD, encoding="utf-8")
    (root / "config.toml").write_text(BASE_CONFIG.format(extra_lines=extra_lines), encoding="utf-8")
    if custom_favicon:
        img = root / "static" / "img"
        img.mkdir(parents=True)
        (img / "custom-favicon.svg").write_text("<svg/>", encoding="utf-8")
    return subprocess.run(
        ["zola", "build"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def icon_href(root: Path) -> str | None:
    html = (root / "public" / "index.html").read_text(encoding="utf-8")
    match = ICON_LINK_RE.search(html)
    return match.group(1) if match else None


def main() -> int:
    if shutil.which("zola") is None:
        print("FAIL: zola not on PATH (required to build the favicon_path fixture)", file=sys.stderr)
        return 1

    failures: list[str] = []

    # Case 1: favicon_path unset — default must still resolve to the theme's
    # own asset, proving the fix leaves existing consumers unaffected.
    with tempfile.TemporaryDirectory(prefix="typikon-favicon-default-") as tmp:
        root = Path(tmp)
        result = build_site(root, extra_lines="", custom_favicon=False)
        if result.returncode != 0:
            failures.append(f"default-favicon fixture: zola build failed:\n{result.stderr}")
        else:
            href = icon_href(root)
            if href is None:
                failures.append("default-favicon fixture: no <link rel=\"icon\"> found in public/index.html")
            elif not href.endswith("/img/favicon.svg"):
                failures.append(f"default-favicon fixture: expected href ending in /img/favicon.svg, got {href!r}")
            elif not href.startswith("https://fixture.example.com/"):
                failures.append(f"default-favicon fixture: href not resolved through get_url() against base_url, got {href!r}")

    # Case 2: favicon_path set to a consumer asset — the <link> must point at
    # THAT asset, not the theme default. This is the exact defect: prior to
    # the fix, config.extra.favicon_path had no effect on the rendered href.
    with tempfile.TemporaryDirectory(prefix="typikon-favicon-custom-") as tmp:
        root = Path(tmp)
        result = build_site(root, extra_lines='favicon_path = "img/custom-favicon.svg"', custom_favicon=True)
        if result.returncode != 0:
            failures.append(f"custom-favicon fixture: zola build failed:\n{result.stderr}")
        else:
            href = icon_href(root)
            if href is None:
                failures.append("custom-favicon fixture: no <link rel=\"icon\"> found in public/index.html")
            elif not href.endswith("/img/custom-favicon.svg"):
                failures.append(f"custom-favicon fixture: expected href ending in /img/custom-favicon.svg, got {href!r}")

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print("OK: favicon <link> resolves the theme default when unset and a consumer's favicon_path when set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
