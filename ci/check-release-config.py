#!/usr/bin/env python3
"""check-release-config — a one-shot release pin must not outlive its release.

`release-as` in release-please-config.json forces the next release to a specific
version. It is the right tool for substantiating a version the manifest already
claims (forkwright/typikon#73 — the manifest asserted 0.1.0 with no tag behind it),
and a trap afterwards: left in place it pins EVERY subsequent release to the same
version, and the symptom is a release-please PR that proposes the version already
released rather than any error.

JSON carries no comments, so the config cannot warn about itself. This check is the
warning: once a tag exists for the pinned version, the pin has done its job and must
be removed.

Exit 0 when there is nothing to say, 1 when the pin has outlived its release.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "release-please-config.json"


CHANGELOG = ROOT / "CHANGELOG.md"


def tags() -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "--list"],
        capture_output=True, text=True, check=False,
    )
    return {t.strip() for t in out.stdout.splitlines() if t.strip()}


def released(version: str) -> bool:
    """Has `version` actually been released?

    WARNING: do not ask git alone. actions/checkout defaults to fetch-depth 1 and
    fetches NO tags, so `git tag --list` is empty in CI — this check would pass on
    every run there while failing locally, which is the blindness it exists to
    prevent, relocated. The changelog section release-please writes is committed
    content, so it survives any checkout depth; the tag is the belt to its braces.
    """
    if version in tags() or f"v{version}" in tags():
        return True
    if CHANGELOG.exists():
        heading = re.compile(rf"^##\s*\[?{re.escape(version)}\]?", re.M)
        return bool(heading.search(CHANGELOG.read_text(encoding="utf-8")))
    return False


def find_pins(node, path="") -> list[tuple[str, str]]:
    """Every truthy `release-as` anywhere in the config, with where it was found.

    WHY a walk and not a fixed lookup: release-please accepts `release-as` at the
    root, per package, and this repo's config also carries a `github.release-as`
    slot. A check that knew only one location would report "no pin" for a config
    that pins — the same shape of blindness the pin itself creates.
    """
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}[{key!r}]" if path else key
            if key == "release-as" and value:
                found.append((path or "<root>", str(value)))
            else:
                found.extend(find_pins(value, here))
    return found


def main() -> None:
    if not CONFIG.exists():
        print("check-release-config: no release-please-config.json; nothing to check")
        return

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    pins = find_pins(config)
    if not pins:
        print("check-release-config: ok (no release-as pin)")
        return

    problems = []
    for where, pinned in pins:
        if released(pinned):
            problems.append(
                f"{where} pins release-as={pinned!r}, which has already been released "
                f"— remove the pin or every later release repeats {pinned}"
            )
        else:
            print(f"check-release-config: {where} pins release-as={pinned!r}, not yet "
                  f"released — pin is doing its job")

    if problems:
        for p in problems:
            print(f"check-release-config: {p}", file=sys.stderr)
        sys.exit(1)
    print("check-release-config: ok")


if __name__ == "__main__":
    main()
