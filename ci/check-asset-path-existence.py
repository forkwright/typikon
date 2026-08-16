#!/usr/bin/env python3
"""check-asset-path-existence — regression test for bin/typikon-check-assets.

WHY (forkwright/typikon#155): `config.extra.favicon_path`, `config.extra.logo_path`,
and `config.extra.og_image` are each rendered into `public/` via Zola's `get_url()`
or raw string concatenation, and neither `zola build` nor `zola check` verifies the
referenced file exists. A mistyped or stale value in any of the three keys builds
and checks clean while shipping a broken reference.

This proves both halves of the fix with the REAL shipped scripts (`zola` itself and
bin/typikon-check-assets as subprocesses — not a reimplementation of either):

- the underlying gap still exists in zola/zola-check themselves (case
  `bad-favicon`, mirroring the issue's own reproduction) — this check does not
  patch Zola, it adds a check alongside it;
- bin/typikon-check-assets closes it: each of the three keys, corrupted ONE AT A
  TIME while the other two stay valid, is caught individually — the failure names
  exactly the corrupted key and does not also flag the two valid ones. Corrupting
  all three but asserting only an aggregate failure would leave a check that
  fails for the wrong key undetected; these cases rule that out.
- a fully-valid config (default favicon, real logo/og_image assets) passes clean.
- a value containing a `..` segment (`test_path_escape`) is rejected even though
  the file it points at genuinely EXISTS on disk at the site root — a real file
  `zola build` never copies into `public/` (only `static/` content is copied),
  so a check that merely joins the path and calls `is_file()` reports it passing
  (this was the shipped defect: `Path.is_file()` performs real OS resolution and
  honors `..`, walking straight out of `public/`). Proves containment, not just
  existence.

NOTE: runs standalone (no examples/ site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
CHECK_ASSETS = THEME_ROOT / "bin" / "typikon-check-assets"

BASE_CONFIG = """\
title = "Fixture"
description = "asset-path-existence fixture"
base_url = "https://fixture.example.com"
default_language = "en"
output_dir = "public"
theme = "typikon"

[extra]
brand_name = "Fixture"
{extra_lines}
"""

INDEX_MD = """\
+++
title = "Fixture"
description = "asset-path-existence fixture"
template = "index.html"
+++
"""


def build_site(root: Path, extra_lines: str, real_assets: list[str]) -> subprocess.CompletedProcess:
    (root / "themes").mkdir(parents=True)
    (root / "themes" / "typikon").symlink_to(THEME_ROOT, target_is_directory=True)
    (root / "content").mkdir()
    (root / "content" / "_index.md").write_text(INDEX_MD, encoding="utf-8")
    (root / "config.toml").write_text(BASE_CONFIG.format(extra_lines=extra_lines), encoding="utf-8")
    if real_assets:
        img = root / "static" / "img"
        img.mkdir(parents=True, exist_ok=True)
        for name in real_assets:
            (img / name).write_text("stub", encoding="utf-8")
    return subprocess.run(["zola", "build"], cwd=root, capture_output=True, text=True, check=False)


def run_check_assets(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK_ASSETS), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def stderr_records(result: subprocess.CompletedProcess) -> list[dict]:
    records = []
    for line in result.stderr.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


def main() -> int:
    if shutil.which("zola") is None:
        print("FAIL: zola not on PATH (required to build the asset-path-existence fixtures)", file=sys.stderr)
        return 1

    failures: list[str] = []

    # Case: all three valid — favicon_path unset (theme default), logo_path and
    # og_image set to assets that really exist. Proves the check does not flag a
    # correctly-configured consumer.
    with tempfile.TemporaryDirectory(prefix="typikon-assets-valid-") as tmp:
        root = Path(tmp)
        build = build_site(
            root,
            extra_lines='logo_path = "img/logo.svg"\nog_image = "img/og.png"\n',
            real_assets=["logo.svg", "og.png"],
        )
        if build.returncode != 0:
            failures.append(f"valid fixture: zola build failed:\n{build.stderr}")
        else:
            check = run_check_assets(root)
            if check.returncode != 0:
                failures.append(
                    f"valid fixture: typikon-check-assets expected exit 0, got {check.returncode}\n"
                    f"stdout: {check.stdout}\nstderr: {check.stderr}"
                )
            summary = json.loads(check.stdout.strip().splitlines()[-1]) if check.stdout.strip() else {}
            if summary.get("failed") != 0 or summary.get("checked") != 3:
                failures.append(f"valid fixture: expected checked=3 failed=0, got {summary}")

    # Per-key isolation: corrupt exactly ONE of the three keys while the other
    # two stay valid, and assert the failure names ONLY the corrupted key.
    per_key_cases = [
        (
            "favicon_path",
            'favicon_path = "img/does-not-exist-favicon.svg"\nlogo_path = "img/logo.svg"\nog_image = "img/og.png"\n',
            ["logo.svg", "og.png"],
        ),
        (
            "logo_path",
            'logo_path = "img/does-not-exist-logo.svg"\nog_image = "img/og.png"\n',
            ["og.png"],
        ),
        (
            "og_image",
            'logo_path = "img/logo.svg"\nog_image = "img/does-not-exist-og.png"\n',
            ["logo.svg"],
        ),
    ]

    for bad_key, extra_lines, real_assets in per_key_cases:
        with tempfile.TemporaryDirectory(prefix=f"typikon-assets-bad-{bad_key}-") as tmp:
            root = Path(tmp)
            build = build_site(root, extra_lines=extra_lines, real_assets=real_assets)
            if build.returncode != 0:
                failures.append(f"{bad_key} fixture: zola build failed:\n{build.stderr}")
                continue

            check_cmd = subprocess.run(
                ["zola", "check", "--skip-external-links"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            if bad_key == "favicon_path":
                # Mirrors forkwright/typikon#155's own reported evidence: the
                # underlying gap in zola build/check is still there — this
                # check exists BECAUSE those two exit 0 on a stale asset path.
                if build.returncode != 0 or check_cmd.returncode != 0:
                    failures.append(
                        f"{bad_key} fixture: expected zola build/check to both exit 0 (documenting "
                        f"forkwright/typikon#155's underlying gap), got build={build.returncode} "
                        f"check={check_cmd.returncode}"
                    )

            check = run_check_assets(root)
            if check.returncode != 1:
                failures.append(
                    f"{bad_key} fixture: typikon-check-assets expected exit 1, got {check.returncode}\n"
                    f"stdout: {check.stdout}\nstderr: {check.stderr}"
                )
                continue

            records = stderr_records(check)
            flagged_keys = {r.get("key") for r in records if "key" in r}
            if flagged_keys != {bad_key}:
                failures.append(
                    f"{bad_key} fixture: expected exactly {{'{bad_key}'}} flagged, got {flagged_keys} "
                    f"(stderr: {check.stderr})"
                )

    # Path escape: a `..`-bearing value that resolves to a file which genuinely
    # EXISTS on disk (at the site root — the physical location the traversal
    # reaches) but was never, and can never be, copied into public/ by zola
    # build (zola copies static/ content into public/; it does not copy
    # arbitrary root-level files). A join-then-is_file() check reports this
    # passing because is_file() performs real OS resolution and honors `..`;
    # a correct check must confine resolution to public/ and reject anything
    # that resolves outside it, regardless of whether a file happens to sit
    # at the escaped location.
    with tempfile.TemporaryDirectory(prefix="typikon-assets-escape-") as tmp:
        root = Path(tmp)
        build = build_site(
            root,
            extra_lines=(
                'favicon_path = "../outside-public-secret.svg"\n'
                'logo_path = "img/logo.svg"\n'
                'og_image = "img/og.png"\n'
            ),
            real_assets=["logo.svg", "og.png"],
        )
        # The escape target: a real file, but at the site ROOT, never under
        # static/, so zola build cannot and does not copy it into public/.
        (root / "outside-public-secret.svg").write_text("secret", encoding="utf-8")
        if build.returncode != 0:
            failures.append(f"path-escape fixture: zola build failed:\n{build.stderr}")
        else:
            escaped_path = (root / "outside-public-secret.svg").resolve()
            in_public = (root / "public" / "outside-public-secret.svg")
            if in_public.exists():
                failures.append(
                    "path-escape fixture: test premise broken — zola build unexpectedly "
                    f"copied {escaped_path} into public/; fixture no longer proves anything"
                )

            check = run_check_assets(root)
            if check.returncode != 1:
                failures.append(
                    f"path-escape fixture: typikon-check-assets expected exit 1, got {check.returncode}\n"
                    f"stdout: {check.stdout}\nstderr: {check.stderr}"
                )
            else:
                records = stderr_records(check)
                flagged_keys = {r.get("key") for r in records if "key" in r}
                if flagged_keys != {"favicon_path"}:
                    failures.append(
                        f"path-escape fixture: expected exactly {{'favicon_path'}} flagged, "
                        f"got {flagged_keys} (stderr: {check.stderr})"
                    )
                escape_error = next(
                    (r.get("error", "") for r in records if r.get("key") == "favicon_path"), ""
                )
                if "outside public" not in escape_error and "outside" not in escape_error:
                    failures.append(
                        "path-escape fixture: favicon_path failure did not name the escape "
                        f"(expected an 'outside public/' style message, got: {escape_error!r})"
                    )

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(
        "OK: typikon-check-assets passes a fully-valid consumer config, fails naming exactly "
        "the corrupted key for each of favicon_path/logo_path/og_image in isolation, and "
        "rejects a `..`-escaping value pointing at a real file outside public/ — all while "
        "zola build/check themselves stay silent (forkwright/typikon#155)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
