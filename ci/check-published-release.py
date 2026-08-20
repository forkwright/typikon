#!/usr/bin/env python3
"""Causal fixture for the exact predecessor-publication gate."""

from __future__ import annotations

import copy
import importlib.machinery
import importlib.util
import json
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "verify-published-release.py"
LOADER = importlib.machinery.SourceFileLoader("verify_published_release", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
published = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(published)

LEGACY_BODY = """## [0.5.0](https://github.com/forkwright/typikon/compare/v0.4.2...v0.5.0) (2026-08-17)


### Features

* **templates,css,ci:** expose a real consumer design API, split Leather's skin out of core ([#175](https://github.com/forkwright/typikon/issues/175)) ([b61228c](https://github.com/forkwright/typikon/commit/b61228cbbf3ca9e88a04161173dcf2faea79a8ec))
* **templates,schemas:** render audience, derive the journal word count from Zola ([#178](https://github.com/forkwright/typikon/issues/178)) ([af66fa0](https://github.com/forkwright/typikon/commit/af66fa027563466ba3e36df99dbf3f598c3c2ff9))"""


class FakeApi:
    def __init__(self):
        self.ref = {
            "object": {
                "type": "commit",
                "sha": published.LEGACY["commit"],
                "url": (
                    "https://api.github.com/repos/forkwright/typikon/git/commits/"
                    + published.LEGACY["commit"]
                ),
            }
        }
        self.release = {
            "id": published.LEGACY["release_id"],
            "tag_name": published.LEGACY["tag"],
            "target_commitish": published.LEGACY["commit"],
            "name": published.LEGACY["tag"],
            "body": LEGACY_BODY,
            "draft": False,
            "prerelease": False,
        }
        self.assets = []
        self.downloads: dict[int, bytes] = {}

    def get_ref(self, _tag):
        return self.ref

    def get_release(self, _tag):
        return self.release

    def list_assets(self, _release_id):
        return self.assets

    def download_asset(self, asset_id):
        return self.downloads[asset_id]


def expect_error(call, fragment: str) -> None:
    try:
        call()
    except published.PublishedReleaseError as exc:
        if fragment not in str(exc):
            raise AssertionError(f"expected {fragment!r}, got {exc!r}") from exc
    else:
        raise AssertionError(f"published predecessor gate accepted mutant: {fragment}")


def main() -> int:
    api = FakeApi()
    assert published.verify(api, "0.5.0") == "legacy-bootstrap"
    for label, mutate in (
        ("tag identity", lambda value: value.ref["object"].update(type="tag")),
        ("release identity", lambda value: value.release.update(draft=True)),
        ("unexpectedly has assets", lambda value: value.assets.append({"id": 1})),
    ):
        mutant = copy.deepcopy(api)
        mutate(mutant)
        expect_error(lambda mutant=mutant: published.verify(mutant, "0.5.0"), label)

    with tempfile.TemporaryDirectory(prefix="typikon-published-release-") as tmp:
        root = Path(tmp)
        lock_dir = root / "release" / "compatibility"
        lock_dir.mkdir(parents=True)
        candidate = "a" * 40
        (lock_dir / "v0.6.0.json").write_text(
            json.dumps({"release": {"candidate_commit": candidate}}),
            encoding="utf-8",
        )
        locked = FakeApi()
        locked.release = {"id": 88, "draft": False}
        names = sorted(published.publisher.expected_asset_names("v0.6.0"))
        locked.assets = [
            {"id": index, "name": name}
            for index, name in enumerate(names, start=1)
        ]
        locked.downloads = {
            index: name.encode() for index, name in enumerate(names, start=1)
        }
        original_validate = published.publisher.validate_staged_evidence
        original_inspect = published.publisher.inspect
        original_expected = published.publisher.expected_assets
        observed = {}

        def expected_assets(directory, tag):
            values = original_expected(directory, tag)
            observed["names"] = set(values)
            return values

        def validate_staged(payloads, tag, subject, _digest, lock_path):
            assert set(payloads) == set(names)
            assert tag == "v0.6.0" and subject == candidate
            assert lock_path == lock_dir / "v0.6.0.json"

        published.publisher.expected_assets = expected_assets
        published.publisher.validate_staged_evidence = validate_staged
        published.publisher.inspect = lambda *_args: "published"
        try:
            assert published.verify(locked, "0.6.0", root) == "locked-release"
            assert observed["names"] == set(names)

            missing = copy.deepcopy(locked)
            missing.assets.pop()
            expect_error(
                lambda: published.verify(missing, "0.6.0", root),
                "asset names are not exact",
            )

            duplicate = copy.deepcopy(locked)
            duplicate.assets[-1]["name"] = duplicate.assets[0]["name"]
            expect_error(
                lambda: published.verify(duplicate, "0.6.0", root),
                "asset names are not exact",
            )

            published.publisher.inspect = lambda *_args: "draft"
            expect_error(
                lambda: published.verify(locked, "0.6.0", root),
                "not exact and published",
            )
        finally:
            published.publisher.expected_assets = original_expected
            published.publisher.validate_staged_evidence = original_validate
            published.publisher.inspect = original_inspect

    print("check-published-release: ok (legacy and locked predecessor states)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
