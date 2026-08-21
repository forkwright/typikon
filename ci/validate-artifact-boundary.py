#!/usr/bin/env python3
"""validate-artifact-boundary — prove a repository-only agent corpus stayed out of
the rendered site (forkwright/typikon#188).

WHY this exists rather than a consumer-side browser assertion: a consumer can
declare `extra.agent_corpus_exposure = "repository"` and mean it, while the
rendered tree ships the corpus anyway. A browser test reaches one route on one
consumer, after the build, and a generated pipeline can regress before it gets
there. The declaration is only a contract if something proves the artifact
honours it, on every consumer, at the boundary where the bytes become public.

WHY case-insensitive matching: the check is fail-closed about what a host might
serve. Cloudflare Pages resolves some paths case-insensitively and a
case-preserving filesystem will happily hold `LLMS.txt`, so matching only the
exact lowercase spelling would let the same corpus through under a different
capitalisation. A guard keyed to one spelling is a guard on a spelling.

WHY symlinks are judged by name and never followed: a symlink named `llms.txt`
serves the corpus exactly as a regular file does, and following one could walk
outside the tree entirely. The name is the disclosure, so the name is what is
checked.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

FORBIDDEN_BASENAME = "llms.txt"
FORBIDDEN_COMPONENT = "_llm"
DECLARED_REPOSITORY_ONLY = "repository"
FIELD = "agent_corpus_exposure"


class BoundaryError(Exception):
    """The declaration could not be read, so the boundary cannot be asserted."""


def read_declaration(root: Path) -> str | None:
    """Return the consumer's declared exposure, or None when it declares none.

    INVARIANT: an absent config or an absent field means the consumer never
    claimed the boundary, which is not a failure. A config that exists and
    cannot be parsed is a failure, because then the claim is unknowable and
    silently skipping would report a guarantee this never checked.
    """
    config_path = root / "config.toml"
    if not config_path.is_file():
        return None
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BoundaryError(f"config.toml exists but could not be read: {exc}") from exc
    extra = config.get("extra")
    if not isinstance(extra, dict):
        return None
    declared = extra.get(FIELD)
    if declared is None:
        return None
    if declared != DECLARED_REPOSITORY_ONLY:
        raise BoundaryError(
            f"extra.{FIELD} must be {DECLARED_REPOSITORY_ONLY!r} when present, "
            f"got {declared!r}"
        )
    return declared


def _forbidden_target(entry: Path) -> bool:
    """True when `entry` is a symlink whose target path names the corpus.

    WHY: renaming is the cheap way around a name check. `public/docs -> ../_llm`
    publishes every byte of the corpus under a basename this would otherwise
    admit, and os.walk never descends it because links are not followed. Reading
    the link's own target costs one syscall and closes that.

    NOTE: this reads the recorded target, not a resolved one. A chain of links
    through a directory this walk never visits is outside what a name-based
    check can see, and is stated as a limit rather than implied to be covered.
    """
    if not entry.is_symlink():
        return False
    target = os.readlink(entry)
    return any(part.lower() == FORBIDDEN_COMPONENT for part in Path(target).parts)


def violations(tree: Path) -> list[str]:
    """Every path under `tree` that would publish the repository-only corpus."""
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(tree, followlinks=False):
        here = Path(dirpath)
        rel_dir = here.relative_to(tree)
        for name in dirnames:
            if name.lower() == FORBIDDEN_COMPONENT:
                found.add(f"{rel_dir / name}/")
            elif _forbidden_target(here / name):
                found.add(f"{rel_dir / name} -> {os.readlink(here / name)}")
        for name in filenames:
            if name.lower() == FORBIDDEN_BASENAME:
                found.add(str(rel_dir / name))
            elif _forbidden_target(here / name):
                found.add(f"{rel_dir / name} -> {os.readlink(here / name)}")
    return sorted(found)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."),
                        help="consumer root holding config.toml (default: cwd)")
    parser.add_argument("trees", type=Path, nargs="+",
                        help="rendered output trees to scan, e.g. public public-local")
    args = parser.parse_args(argv)

    try:
        declared = read_declaration(args.root)
    except BoundaryError as exc:
        print(f"validate-artifact-boundary: {exc}", file=sys.stderr)
        return 1

    if declared is None:
        print(
            f"validate-artifact-boundary: skipped — no extra.{FIELD} declared, "
            "so no repository-only boundary is claimed"
        )
        return 0

    scanned: list[str] = []
    failures: list[str] = []
    for tree in args.trees:
        if not tree.is_dir():
            # A tree the local gate did not build is not a violation; the hosted
            # pipeline passes only trees it produced.
            continue
        scanned.append(str(tree))
        for hit in violations(tree):
            failures.append(f"{tree}/{hit}")

    if not scanned:
        print(
            "validate-artifact-boundary: no rendered tree found among "
            f"{', '.join(str(t) for t in args.trees)} — nothing to assert",
            file=sys.stderr,
        )
        return 1

    if failures:
        print(
            f"validate-artifact-boundary: extra.{FIELD} = {declared!r} promises the "
            "agent corpus stays in the repository, but the rendered output would "
            "publish it:",
            file=sys.stderr,
        )
        for hit in failures:
            print(f"  {hit}", file=sys.stderr)
        return 1

    print(
        f"validate-artifact-boundary: ok ({', '.join(scanned)} carry no "
        f"{FORBIDDEN_BASENAME} and no {FORBIDDEN_COMPONENT} path component)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
