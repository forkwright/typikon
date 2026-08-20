#!/usr/bin/env python3
"""Require an exact published predecessor before Release Please advances."""

from __future__ import annotations

import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_secret import SecretToken

PUBLISHER_SCRIPT = Path(__file__).resolve().parent / "publish-locked-release.py"
PUBLISHER_LOADER = importlib.machinery.SourceFileLoader(
    "publish_locked_release", str(PUBLISHER_SCRIPT)
)
PUBLISHER_SPEC = importlib.util.spec_from_loader(
    PUBLISHER_LOADER.name, PUBLISHER_LOADER
)
assert PUBLISHER_SPEC is not None
publisher = importlib.util.module_from_spec(PUBLISHER_SPEC)
PUBLISHER_LOADER.exec_module(publisher)

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
LEGACY = {
    "version": "0.5.0",
    "tag": "v0.5.0",
    "commit": "f0da785dad30d15790929040a5c0f67f0b9cfb54",
    "release_id": 372569747,
    "body_sha256": "94b65ccc22705ee6b534a73c006d83d4e9c4357c962fc49d46ac199d285498fd",
}


class PublishedReleaseError(RuntimeError):
    pass


def verify_legacy(api: Any, version: str) -> None:
    if version != LEGACY["version"]:
        raise PublishedReleaseError("version is not the one explicit legacy bootstrap")
    ref = api.get_ref(str(LEGACY["tag"]))
    object_identity = ref.get("object") if isinstance(ref, dict) else None
    if (
        not isinstance(object_identity, dict)
        or object_identity.get("type") != "commit"
        or object_identity.get("sha") != LEGACY["commit"]
    ):
        raise PublishedReleaseError("legacy bootstrap tag identity drifted")
    release = api.get_release(str(LEGACY["tag"]))
    if not isinstance(release, dict):
        raise PublishedReleaseError("legacy bootstrap release is missing")
    actual = {
        "id": release.get("id"),
        "tag_name": release.get("tag_name"),
        "target_commitish": release.get("target_commitish"),
        "name": release.get("name"),
        "draft": release.get("draft"),
        "prerelease": release.get("prerelease"),
        "body_sha256": hashlib.sha256(
            str(release.get("body", "")).encode("utf-8")
        ).hexdigest(),
    }
    expected = {
        "id": LEGACY["release_id"],
        "tag_name": LEGACY["tag"],
        "target_commitish": LEGACY["commit"],
        "name": LEGACY["tag"],
        "draft": False,
        "prerelease": False,
        "body_sha256": LEGACY["body_sha256"],
    }
    if actual != expected:
        raise PublishedReleaseError("legacy bootstrap release identity drifted")
    if api.list_assets(int(LEGACY["release_id"])):
        raise PublishedReleaseError("legacy bootstrap release unexpectedly has assets")


def verify_locked(api: Any, version: str, root: Path = ROOT) -> None:
    tag = f"v{version}"
    lock_path = root / "release" / "compatibility" / f"{tag}.json"
    try:
        lock_bytes = lock_path.read_bytes()
        lock = json.loads(lock_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishedReleaseError(f"cannot read tracked compatibility lock: {exc}") from exc
    candidate = lock.get("release", {}).get("candidate_commit")
    if not isinstance(candidate, str):
        raise PublishedReleaseError("compatibility lock has no candidate commit")
    lock_sha256 = hashlib.sha256(lock_bytes).hexdigest()
    release = api.get_release(tag)
    if not isinstance(release, dict) or release.get("draft") is not False:
        raise PublishedReleaseError("exact published release is missing")
    assets = api.list_assets(int(release["id"]))
    names = [str(asset.get("name", "")) for asset in assets]
    expected_names = publisher.expected_asset_names(tag)
    if len(names) != len(set(names)) or set(names) != expected_names:
        raise PublishedReleaseError("published release asset names are not exact")
    with tempfile.TemporaryDirectory(prefix="typikon-published-release-") as tmp:
        staging = Path(tmp)
        for asset in assets:
            name = str(asset["name"])
            (staging / name).write_bytes(api.download_asset(int(asset["id"])))
        payloads = publisher.expected_assets(staging, tag)
        publisher.validate_staged_evidence(
            payloads, tag, candidate, lock_sha256, lock_path
        )
        if publisher.inspect(api, tag, candidate, lock_sha256, payloads) != "published":
            raise PublishedReleaseError("release is not exact and published")


def verify(api: Any, version: str, root: Path = ROOT) -> str:
    if SEMVER.fullmatch(version) is None:
        raise PublishedReleaseError("manifest version is not SemVer")
    if version == LEGACY["version"]:
        verify_legacy(api, version)
        return "legacy-bootstrap"
    verify_locked(api, version, root)
    return "locked-release"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()
    try:
        if not args.repository:
            raise PublishedReleaseError("GITHUB_REPOSITORY is required")
        try:
            token = SecretToken.from_env("GITHUB_TOKEN")
        except ValueError as exc:
            raise PublishedReleaseError("GITHUB_TOKEN is required") from exc
        api = publisher.GitHubApi(args.repository, token)
        authority = verify(api, args.version)
        print(json.dumps({"status": "pass", "authority": authority}, sort_keys=True))
    except (
        PublishedReleaseError,
        publisher.PublishError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(f"verify-published-release: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
