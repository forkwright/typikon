#!/usr/bin/env python3
"""check-init-favicon-path — regression test for bin/typikon-init's config.toml scaffold.

WHY: forkwright/typikon#110's fix routes templates/base.html's favicon <link> through
config.extra.favicon_path (ci/check-favicon-path.py proves the template side). The
issue's Desired correction is explicit that the key belongs in config.toml [extra]
alongside logo_path — bin/typikon-init's scaffold is the literal artifact a new
consumer starts from, and a fix that only touches the template leaves every freshly
scaffolded site with no visible way to discover the key exists.

Runs the real bin/typikon-init against a throwaway destination. The theme submodule
step is pointed at this checkout instead of the forge (TYPIKON_THEME_REPO(_GH)) and
cloned over the local-path transport (GIT_ALLOW_PROTOCOL=file — git blocks that
transport for submodules by default, CVE-2022-39253), so the check needs neither
network nor a running local forge.

NOTE: runs standalone (no examples/ site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
INIT_SCRIPT = THEME_ROOT / "bin" / "typikon-init"

FAVICON_LINE_RE = re.compile(r'^\s*#?\s*favicon_path\s*=\s*"([^"]+)"', re.MULTILINE)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="typikon-init-favicon-") as tmp:
        dest = Path(tmp) / "probe-site"
        env = {
            **os.environ,
            "GIT_ALLOW_PROTOCOL": "file",
            "TYPIKON_THEME_REPO": str(THEME_ROOT),
            "TYPIKON_THEME_REPO_GH": str(THEME_ROOT),
        }
        result = subprocess.run(
            [str(INIT_SCRIPT), "probe-site", str(dest)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"FAIL: bin/typikon-init exited {result.returncode}:\n{result.stderr}",
                file=sys.stderr,
            )
            return 1

        config = dest / "config.toml"
        if not config.is_file():
            print(f"FAIL: {config} was not created", file=sys.stderr)
            return 1

        text = config.read_text(encoding="utf-8")
        match = FAVICON_LINE_RE.search(text)
        if match is None:
            print(
                "FAIL: scaffolded config.toml [extra] carries no favicon_path key "
                "(forkwright/typikon#110)",
                file=sys.stderr,
            )
            return 1
        if match.group(1) != "img/favicon.svg":
            print(
                f"FAIL: scaffolded favicon_path default is {match.group(1)!r}, expected "
                "'img/favicon.svg' (must match base.html's default so an unset key is a no-op)",
                file=sys.stderr,
            )
            return 1

    print(
        "OK: bin/typikon-init scaffolds config.toml [extra] with a favicon_path key "
        "defaulted to img/favicon.svg"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
