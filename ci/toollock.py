#!/usr/bin/env python3
"""toollock — read and validate ci/tool-lock.toml (forkwright/typikon#58).

The lock is the only place a gate tool's version and its integrity value are
written. Everything that needs either reads them from here, so the pair cannot
drift: a version bumped without its checksum is not a mistake this shape can
express.

Importable as a module (ci/render-template.py, ci/check-tool-lock.py) and
runnable as a command for shell callers that need one value.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

LOCK_PATH = Path(__file__).resolve().parent / "tool-lock.toml"
SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

# An archive is the only kind whose integrity is cryptographic. The rest carry
# a version contract, and are named so a reader can tell which is which rather
# than having to infer it from whether a hash field happens to be present.
KINDS_REQUIRING_SHA256 = {"archive"}
VALID_KINDS = {"archive", "npm", "runtime", "pypi"}
VALID_INTEGRITY = {"registry-version-pin", "action-toolcache"}


class LockError(Exception):
    """The lock is unusable, so nothing derived from it can be trusted."""


@dataclass(frozen=True)
class Tool:
    name: str
    kind: str
    version: str
    sha256: str | None
    url: str | None
    integrity: str | None
    placeholder_version: str | None
    placeholder_sha256: str | None

    def resolved_url(self) -> str | None:
        """The download URL with the locked version substituted.

        WHY derived rather than stored whole: a stored URL and a stored version
        are two places one fact can be written, which is the defect this file
        exists to remove -- at the smallest possible scale.
        """
        return self.url.format(version=self.version) if self.url else None


def _require(row: dict, key: str, index: int) -> object:
    if key not in row:
        raise LockError(f"[[tool]] #{index}: missing required key {key!r}")
    return row[key]


def load(path: Path | str = LOCK_PATH) -> list[Tool]:
    """Parse and validate the lock, or raise. Never returns a partial read."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LockError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise LockError(f"{path} is not parseable TOML: {exc}") from exc

    declared = raw.get("schema_version")
    if declared != SCHEMA_VERSION:
        raise LockError(
            f"{path}: schema_version is {declared!r}, this reader speaks {SCHEMA_VERSION}"
        )

    rows = raw.get("tool")
    if not isinstance(rows, list) or not rows:
        raise LockError(f"{path}: no [[tool]] entries")

    tools: list[Tool] = []
    seen: set[str] = set()
    placeholders: dict[str, str] = {}
    for index, row in enumerate(rows, start=1):
        name = str(_require(row, "name", index))
        kind = str(_require(row, "kind", index))
        version = str(_require(row, "version", index))
        if name in seen:
            raise LockError(f"{path}: {name!r} is declared twice; one tool, one entry")
        seen.add(name)
        if kind not in VALID_KINDS:
            raise LockError(f"{path}: {name!r} has unknown kind {kind!r}")
        if not version:
            raise LockError(f"{path}: {name!r} has an empty version")

        sha256 = row.get("sha256")
        if kind in KINDS_REQUIRING_SHA256:
            if not isinstance(sha256, str) or not SHA256_RE.match(sha256):
                raise LockError(
                    f"{path}: {name!r} is kind={kind!r} and needs a 64-hex sha256; got {sha256!r}"
                )
            if not row.get("url"):
                raise LockError(f"{path}: {name!r} is kind={kind!r} and needs a url")
            if "{version}" not in str(row["url"]):
                raise LockError(
                    f"{path}: {name!r} url does not carry {{version}}, so the URL and the "
                    "checksum could name different releases"
                )
        elif sha256 is not None:
            raise LockError(
                f"{path}: {name!r} is kind={kind!r} and carries a sha256; only "
                f"{sorted(KINDS_REQUIRING_SHA256)} may, so a version contract is not "
                "mistaken for a cryptographic one"
            )
        else:
            integrity = row.get("integrity")
            if integrity not in VALID_INTEGRITY:
                raise LockError(
                    f"{path}: {name!r} must declare integrity as one of "
                    f"{sorted(VALID_INTEGRITY)}; got {integrity!r}"
                )

        for key in ("placeholder_version", "placeholder_sha256"):
            value = row.get(key)
            if value is None:
                continue
            if not PLACEHOLDER_RE.match(str(value)):
                raise LockError(f"{path}: {name!r} {key}={value!r} is not an UPPER_SNAKE name")
            if value in placeholders:
                raise LockError(
                    f"{path}: placeholder {value!r} is claimed by both "
                    f"{placeholders[value]!r} and {name!r}"
                )
            placeholders[str(value)] = name

        if row.get("placeholder_sha256") and not row.get("sha256"):
            raise LockError(
                f"{path}: {name!r} exposes a sha256 placeholder but has no sha256 to fill it"
            )

        tools.append(Tool(
            name=name,
            kind=kind,
            version=version,
            sha256=sha256,
            url=row.get("url"),
            integrity=row.get("integrity"),
            placeholder_version=row.get("placeholder_version"),
            placeholder_sha256=row.get("placeholder_sha256"),
        ))
    return tools


def substitutions(tools: list[Tool]) -> dict[str, str]:
    """The {{ PLACEHOLDER }} -> value map the renderer applies."""
    out: dict[str, str] = {}
    for tool in tools:
        if tool.placeholder_version:
            out[tool.placeholder_version] = tool.version
        if tool.placeholder_sha256 and tool.sha256:
            out[tool.placeholder_sha256] = tool.sha256
    return out


def by_name(tools: list[Tool]) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


def resolved_versions(tools: list[Tool]) -> dict[str, str]:
    """What a receipt records: every locked tool and the version it resolved to."""
    return {tool.name: tool.version for tool in sorted(tools, key=lambda t: t.name)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="read ci/tool-lock.toml")
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--get", metavar="PLACEHOLDER",
                        help="print one substitution value, e.g. ZOLA_VERSION")
    parser.add_argument("--list", action="store_true",
                        help="print every placeholder=value pair")
    args = parser.parse_args(argv)
    try:
        tools = load(args.lock)
    except LockError as exc:
        print(f"toollock: {exc}", file=sys.stderr)
        return 1
    subs = substitutions(tools)
    if args.get:
        if args.get not in subs:
            print(f"toollock: no placeholder {args.get!r} in the lock", file=sys.stderr)
            return 1
        print(subs[args.get])
        return 0
    if args.list:
        for key in sorted(subs):
            print(f"{key}={subs[key]}")
        return 0
    print(f"toollock: ok ({len(tools)} tools, {len(subs)} placeholders)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
