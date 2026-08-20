#!/usr/bin/env python3
"""Causal fixture for interrupted, conflicting, and completed publication states."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "publish-locked-release.py"
LOADER = importlib.machinery.SourceFileLoader("publish_locked_release", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
publication = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(publication)

TAG = "v0.6.0"
CANDIDATE = "a" * 40
LOCK = "b" * 64
MESSAGE = publication.exact_tag_message(TAG, LOCK)
MARKER = publication.release_marker(CANDIDATE, LOCK)
EVIDENCE = "d" * 40


class ClientFixture(BaseHTTPRequestHandler):
    paths = []
    authorization = []
    release_pages = {}
    asset_pages = {}

    def do_GET(self):  # noqa: N802
        type(self).paths.append(self.path)
        type(self).authorization.append(self.headers.get("Authorization"))
        if self.path == "/repos/forkwright/typikon":
            payload = json.dumps({"default_branch": "main"}).encode()
        elif self.path.startswith(
            "/repos/forkwright/typikon/releases?per_page=100&page="
        ):
            page = int(self.path.rsplit("=", 1)[1])
            payload = json.dumps(type(self).release_pages.get(page, [])).encode()
        elif self.path.startswith(
            "/repos/forkwright/typikon/releases/77/assets?per_page=100&page="
        ):
            page = int(self.path.rsplit("=", 1)[1])
            payload = json.dumps(type(self).asset_pages.get(page, [])).encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_DELETE(self):  # noqa: N802
        type(self).paths.append(self.path)
        type(self).authorization.append(self.headers.get("Authorization"))
        if self.path != "/repos/forkwright/typikon/releases/assets/42":
            self.send_error(404)
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def client_probe() -> None:
    ClientFixture.paths = []
    ClientFixture.authorization = []
    target_release = {
        "id": 77,
        "tag_name": TAG,
        "target_commitish": CANDIDATE,
        "name": f"Typikon {TAG}",
        "body": MARKER,
        "draft": True,
        "prerelease": False,
    }
    ClientFixture.release_pages = {
        1: [{"id": index, "tag_name": f"v0.0.{index}"} for index in range(100)],
        2: [target_release],
    }
    ClientFixture.asset_pages = {
        1: [{"id": index, "name": f"decoy-{index}"} for index in range(100)],
        2: [{"id": 101, "name": "page-two"}],
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), ClientFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            publication.GitHubApi("forkwright/typikon", "fixture-token")
        except TypeError:
            pass
        else:
            raise AssertionError("publisher accepted a bare token string")
        api = publication.GitHubApi(
            "forkwright/typikon", publication.SecretToken("fixture-token")
        )
        api.api_root = f"http://127.0.0.1:{server.server_port}/repos/forkwright/typikon"
        assert api.get_default_branch() == "main"
        draft = api.get_release(TAG)
        assert draft is not None and draft["draft"] is True
        assert len(api.list_assets(77)) == 101
        ClientFixture.release_pages = {
            1: [
                *[{"id": index, "tag_name": f"v0.0.{index}"} for index in range(99)],
                target_release,
            ],
            2: [dict(target_release, id=78)],
        }
        try:
            api.get_release(TAG)
        except publication.PublishError as exc:
            assert "multiple releases" in str(exc)
        else:
            raise AssertionError("publisher accepted duplicate releases across pages")
        ClientFixture.asset_pages = {
            1: [
                {"id": index, "name": f"decoy-{index}", "state": "uploaded"}
                for index in range(100)
            ],
            2: [{"id": 101, "name": "decoy-0", "state": "uploaded"}],
        }
        try:
            publication.reconcile_assets(
                api,
                {"id": 77},
                {f"decoy-{index}": b"" for index in range(100)},
                allow_upload=False,
            )
        except publication.PublishError as exc:
            assert "duplicate asset" in str(exc)
        else:
            raise AssertionError("publisher accepted duplicate assets across pages")
        assert api.delete_asset(42) is None
        assert any(path.endswith("releases?per_page=100&page=2") for path in ClientFixture.paths)
        assert any(path.endswith("assets?per_page=100&page=2") for path in ClientFixture.paths)
        assert ClientFixture.paths[-1] == "/repos/forkwright/typikon/releases/assets/42"
        assert all(value == "Bearer fixture-token" for value in ClientFixture.authorization)
    finally:
        server.shutdown()
        server.server_close()


class FakeApi:
    def __init__(self):
        self.ref = None
        self.tag = None
        self.release = None
        self.assets: dict[str, dict[str, object]] = {}
        self.next_asset = 100
        self.body = "Release notes"
        self.main = EVIDENCE
        self.calls: Counter[str] = Counter()
        self.hook = None

    def event(self, name):
        self.calls[name] += 1
        if self.hook is not None:
            self.hook(self, name, self.calls[name])

    def get_branch_head(self, branch):
        assert branch == "main"
        self.event("get_branch_head")
        return self.main

    def get_default_branch(self):
        self.event("get_default_branch")
        return "main"

    def get_ref(self, tag):
        assert tag == TAG
        self.event("get_ref")
        return self.ref

    def create_tag(self, tag, message, candidate):
        assert (tag, message, candidate) == (TAG, MESSAGE, CANDIDATE)
        self.tag = {
            "sha": "c" * 40,
            "tag": tag,
            "message": message,
            "object": {"type": "commit", "sha": candidate},
        }
        self.event("create_tag")
        return self.tag

    def create_ref(self, tag, object_id):
        assert (tag, object_id) == (TAG, "c" * 40)
        self.ref = {"object": {"type": "tag", "sha": object_id}}
        self.event("create_ref")

    def get_tag(self, object_id):
        assert self.tag is not None and object_id == self.tag["sha"]
        self.event("get_tag")
        return self.tag

    def get_release(self, tag):
        assert tag == TAG
        self.event("get_release")
        return self.release

    def pull_body(self, number):
        assert number == 182
        return self.body

    def create_release(self, tag, candidate, name, body):
        assert tag == TAG and candidate == CANDIDATE and name == f"Typikon {TAG}"
        assert MARKER in body
        self.release = {
            "id": 77,
            "tag_name": tag,
            # GitHub may report the default branch because target_commitish is
            # unused once the exact annotated tag exists. The tag object and
            # release marker, not this response field, bind the candidate.
            "target_commitish": "main",
            "name": name,
            "body": body,
            "draft": True,
            "prerelease": False,
        }
        self.event("create_release")
        return self.release

    def list_assets(self, release_id):
        assert release_id == 77
        return [dict(value) for value in self.assets.values()]

    def download_asset(self, asset_id):
        for asset in self.assets.values():
            if asset["id"] == asset_id:
                self.event("download_asset")
                return asset["payload"]
        raise AssertionError(f"unknown asset {asset_id}")

    def upload_asset(self, release_id, name, payload):
        assert release_id == 77 and name not in self.assets
        self.next_asset += 1
        asset = {
            "id": self.next_asset,
            "name": name,
            "state": "uploaded",
            "payload": payload,
        }
        self.assets[name] = asset
        self.event("upload_asset")
        return asset

    def delete_asset(self, asset_id):
        for name, asset in list(self.assets.items()):
            if asset["id"] == asset_id:
                del self.assets[name]
                return
        raise AssertionError(f"unknown asset {asset_id}")

    def publish_release(self, release_id):
        assert release_id == 77 and self.release is not None
        self.release["draft"] = False
        self.event("publish_release")
        return self.release


def expect_failure(api, payloads, fragment):
    try:
        publication.publish(api, TAG, CANDIDATE, LOCK, payloads, api.main)
    except publication.PublishError as exc:
        if fragment not in str(exc):
            raise AssertionError(f"expected {fragment!r}, got {exc!r}") from exc
    else:
        raise AssertionError(f"publication accepted mutant: {fragment}")


def main() -> int:
    global CANDIDATE, EVIDENCE, LOCK, MARKER, MESSAGE
    client_probe()
    with tempfile.TemporaryDirectory(prefix="typikon-publication-") as tmp:
        repo = Path(tmp) / "repo"
        staging = Path(tmp) / "staging"
        repo.mkdir()
        staging.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "fixture"], check=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "fixture@example.test"],
            check=True,
        )
        (repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [0.6.0](https://example.test/v0.6.0)\n\n"
            "### Features\n\n* exact fixture release\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(repo), "add", "CHANGELOG.md"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "release candidate"],
            check=True,
        )
        CANDIDATE = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        publication.ROOT = repo
        archive_name = f"typikon-{TAG}.tar.gz"
        sbom_name = f"{archive_name}.cdx.json"
        archive = subprocess.check_output(
            ["git", "-C", str(repo), "archive", "--format=tar.gz", CANDIDATE]
        )
        checksum = f"{publication.digest_bytes(archive)}  {archive_name}\n".encode()
        sbom = b'{"bomFormat":"CycloneDX"}\n'
        provenance_bundle = b'{"mediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}\n'
        sbom_bundle = b'{"mediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}\n'
        tools_receipt = b'{"consumer":"tools"}\n'
        leather_receipt = b'{"consumer":"leather"}\n'
        candidate_manifest = {
            "release": {
                "version": "0.6.0",
                "tag": TAG,
                "candidate_commit": CANDIDATE,
            },
            "archive": {
                "name": archive_name,
                "sha256": publication.digest_bytes(archive),
                "size": len(archive),
            },
            "checksum": {
                "name": f"{archive_name}.sha256",
                "sha256": publication.digest_bytes(checksum),
                "size": len(checksum),
            },
            "sbom": {
                "name": sbom_name,
                "sha256": publication.digest_bytes(sbom),
                "size": len(sbom),
            },
            "attestations": {
                "provenance": {
                    "name": f"{archive_name}.provenance.intoto.jsonl",
                    "sha256": publication.digest_bytes(provenance_bundle),
                    "size": len(provenance_bundle),
                },
                "sbom": {
                    "name": f"{archive_name}.sbom.intoto.jsonl",
                    "sha256": publication.digest_bytes(sbom_bundle),
                    "size": len(sbom_bundle),
                },
            },
            "notes": {
                "body": "### Features\n\n* exact fixture release",
                "sha256": publication.digest_bytes(
                    b"### Features\n\n* exact fixture release"
                ),
                "size": len(b"### Features\n\n* exact fixture release"),
            },
        }
        lock = {
            "release": {
                "version": "0.6.0",
                "tag": TAG,
                "candidate_commit": CANDIDATE,
            },
            "candidate_artifact": {
                "archive_name": archive_name,
                "archive_sha256": publication.digest_bytes(archive),
                "archive_size": len(archive),
                "checksum_name": f"{archive_name}.sha256",
                "checksum_sha256": publication.digest_bytes(checksum),
                "checksum_size": len(checksum),
                "sbom_name": sbom_name,
                "sbom_sha256": publication.digest_bytes(sbom),
                "sbom_size": len(sbom),
                "provenance_bundle_name": f"{archive_name}.provenance.intoto.jsonl",
                "provenance_bundle_sha256": publication.digest_bytes(provenance_bundle),
                "provenance_bundle_size": len(provenance_bundle),
                "sbom_bundle_name": f"{archive_name}.sbom.intoto.jsonl",
                "sbom_bundle_sha256": publication.digest_bytes(sbom_bundle),
                "sbom_bundle_size": len(sbom_bundle),
            },
            "consumers": [
                {
                    "id": "tools",
                    "receipt_path": "release/compatibility/receipts/tools.json",
                    "receipt_sha256": publication.digest_bytes(tools_receipt),
                },
                {
                    "id": "leather",
                    "receipt_path": "release/compatibility/receipts/leather.json",
                    "receipt_sha256": publication.digest_bytes(leather_receipt),
                },
            ],
        }
        (staging / "candidate.json").write_text(json.dumps(candidate_manifest))
        (staging / archive_name).write_bytes(archive)
        (staging / f"{archive_name}.sha256").write_bytes(checksum)
        (staging / sbom_name).write_bytes(sbom)
        (staging / f"{archive_name}.provenance.intoto.jsonl").write_bytes(
            provenance_bundle
        )
        (staging / f"{archive_name}.sbom.intoto.jsonl").write_bytes(sbom_bundle)
        tracked_lock = repo / "release" / "compatibility" / "v0.6.0.json"
        receipts = tracked_lock.parent / "receipts"
        receipts.mkdir(parents=True)
        tracked_lock.write_text(json.dumps(lock), encoding="utf-8")
        (receipts / "tools.json").write_bytes(tools_receipt)
        (receipts / "leather.json").write_bytes(leather_receipt)
        subprocess.run(["git", "-C", str(repo), "add", "release"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", "release evidence"],
            check=True,
        )
        EVIDENCE = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        lock_path = staging / f"typikon-{TAG}-compatibility-lock.json"
        lock_path.write_bytes(tracked_lock.read_bytes())
        (staging / f"typikon-{TAG}-tools-receipt.json").write_bytes(tools_receipt)
        (staging / f"typikon-{TAG}-leather-receipt.json").write_bytes(leather_receipt)
        payloads = publication.expected_assets(staging, TAG)
        staged_lock_digest = publication.digest_bytes(lock_path.read_bytes())
        LOCK = staged_lock_digest
        MESSAGE = publication.exact_tag_message(TAG, LOCK)
        MARKER = publication.release_marker(CANDIDATE, LOCK)
        publication.validate_staged_evidence(
            payloads, TAG, CANDIDATE, staged_lock_digest, tracked_lock
        )
        try:
            publication.validate_staged_evidence(
                payloads, TAG, CANDIDATE, "0" * 64, tracked_lock
            )
        except publication.PublishError as exc:
            assert "lock digest" in str(exc)
        else:
            raise AssertionError("publisher accepted a different staged lock digest")
        release_body = publication.exact_release_body(
            payloads, CANDIDATE, LOCK
        )

        # While the verified evidence commit remains current, a fresh attempt
        # can tear after the tag, draft, or any upload and resumes exactly.
        api = FakeApi()
        publication.ensure_tag(api, TAG, CANDIDATE, MESSAGE, api.main)
        assert publication.inspect(api, TAG, CANDIDATE, LOCK, payloads) == "tagged"
        assert publication.publish(api, TAG, CANDIDATE, LOCK, payloads, api.main) == "published"
        assert publication.publish(api, TAG, CANDIDATE, LOCK, payloads, api.main) == "published"

        # An already-public retry still reads every asset before returning a
        # success receipt. Movement during that readback must invalidate the
        # receipt even though the exact public release remains unchanged.
        published_resume_race = FakeApi()
        evidence = published_resume_race.main
        assert publication.publish(
            published_resume_race, TAG, CANDIDATE, LOCK, payloads, evidence
        ) == "published"
        published_resume_race.calls.clear()
        published_resume_race.hook = (
            lambda value, name, count: setattr(value, "main", "e" * 40)
            if name == "download_asset" and count == 1
            else None
        )
        try:
            publication.publish(
                published_resume_race,
                TAG,
                CANDIDATE,
                LOCK,
                payloads,
                evidence,
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError(
                "published resume ignored main movement during asset readback"
            )
        assert published_resume_race.release is not None
        assert published_resume_race.release["draft"] is False

        partial = FakeApi()
        publication.ensure_tag(partial, TAG, CANDIDATE, MESSAGE, partial.main)
        release = partial.create_release(
            TAG, CANDIDATE, f"Typikon {TAG}", release_body
        )
        first = sorted(payloads)[0]
        partial.upload_asset(int(release["id"]), first, payloads[first])
        assert publication.inspect(partial, TAG, CANDIDATE, LOCK, payloads) == "draft"
        assert publication.publish(partial, TAG, CANDIDATE, LOCK, payloads, partial.main) == "published"

        starter = FakeApi()
        publication.ensure_tag(starter, TAG, CANDIDATE, MESSAGE, starter.main)
        release = starter.create_release(
            TAG, CANDIDATE, f"Typikon {TAG}", release_body
        )
        first = sorted(payloads)[0]
        starter.upload_asset(int(release["id"]), first, b"")
        starter.assets[first]["state"] = "starter"
        assert publication.publish(starter, TAG, CANDIDATE, LOCK, payloads, starter.main) == "published"

        wrong_tag = FakeApi()
        publication.ensure_tag(wrong_tag, TAG, CANDIDATE, MESSAGE, wrong_tag.main)
        wrong_tag.tag["message"] = "wrong"
        expect_failure(wrong_tag, payloads, "tag identity drifted")

        wrong_asset = FakeApi()
        publication.ensure_tag(
            wrong_asset, TAG, CANDIDATE, MESSAGE, wrong_asset.main
        )
        release = wrong_asset.create_release(
            TAG, CANDIDATE, f"Typikon {TAG}", release_body
        )
        first = sorted(payloads)[0]
        wrong_asset.upload_asset(int(release["id"]), first, b"wrong")
        expect_failure(wrong_asset, payloads, "differs from staged bytes")

        published_partial = FakeApi()
        publication.ensure_tag(
            published_partial, TAG, CANDIDATE, MESSAGE, published_partial.main
        )
        release = published_partial.create_release(
            TAG, CANDIDATE, f"Typikon {TAG}", release_body
        )
        release["draft"] = False
        expect_failure(published_partial, payloads, "published release is missing asset")

        moved = FakeApi()
        try:
            publication.publish(
                moved, TAG, CANDIDATE, LOCK, payloads, "e" * 40
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publication accepted a stale evidence commit")

        # Movement while inspect reads the release is caught before any tag
        # object or ref can be created.
        inspect_race = FakeApi()
        evidence = inspect_race.main
        inspect_race.hook = (
            lambda value, name, count: setattr(value, "main", "e" * 40)
            if name == "get_release" and count == 1
            else None
        )
        try:
            publication.publish(
                inspect_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publication ignored main movement during inspect")
        assert inspect_race.calls["create_tag"] == 0
        assert inspect_race.ref is None and inspect_race.release is None

        # Movement during tag-object creation leaves no named tag, draft, or
        # assets. The unreferenced tag object is harmless API residue.
        object_race = FakeApi()
        evidence = object_race.main
        object_race.hook = (
            lambda value, name, count: setattr(value, "main", "e" * 40)
            if name == "create_tag" and count == 1
            else None
        )
        try:
            publication.publish(
                object_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publication ignored main movement after tag object")
        assert object_race.ref is None and object_race.release is None
        assert object_race.calls["create_ref"] == 0

        # The GitHub API cannot atomically compare main and create another ref.
        # Movement during the tag-ref POST may therefore leave one exact,
        # provisional tag. It must stop before the draft. Because restoring an
        # old main tip is not a safe recovery, retries stay failed until a
        # separately reviewed tag-residue action resolves the public ref.
        ref_race = FakeApi()
        evidence = ref_race.main
        ref_race.hook = (
            lambda value, name, count: setattr(value, "main", "e" * 40)
            if name == "create_ref" and count == 1
            else None
        )
        try:
            publication.publish(
                ref_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publication ignored main movement after tag ref")
        assert ref_race.ref is not None and ref_race.release is None
        assert ref_race.calls["create_tag"] == 1
        ref_race.hook = None
        try:
            publication.publish(
                ref_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publisher resumed a provisional tag from stale evidence")
        assert ref_race.calls["create_tag"] == 1

        # Movement after tag/draft/assets but before publication leaves an
        # exact private draft and also refuses stale-evidence retries.
        readback_race = FakeApi()
        evidence = readback_race.main
        readback_race.hook = (
            lambda value, name, count: setattr(value, "main", "e" * 40)
            if name == "download_asset" and count == 1
            else None
        )
        try:
            publication.publish(
                readback_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publication ignored main movement before publish")
        assert readback_race.release is not None
        assert readback_race.release["draft"] is True
        readback_race.hook = None
        try:
            publication.publish(
                readback_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publisher resumed a private draft from stale evidence")

        # GitHub cannot atomically compare main with the draft-to-public PATCH.
        # Movement during that write is detected after exact release readback,
        # leaving a public exact release but never a green publication receipt.
        publish_race = FakeApi()
        evidence = publish_race.main
        publish_race.hook = (
            lambda value, name, count: setattr(value, "main", "e" * 40)
            if name == "publish_release" and count == 1
            else None
        )
        try:
            publication.publish(
                publish_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publication ignored main movement during publish")
        assert publish_race.release is not None
        assert publish_race.release["draft"] is False
        publish_race.hook = None
        try:
            publication.publish(
                publish_race, TAG, CANDIDATE, LOCK, payloads, evidence
            )
        except publication.PublishError as exc:
            assert "main moved" in str(exc)
        else:
            raise AssertionError("publisher accepted a public release from stale evidence")

    print("check-release-publication: ok (exact retries and fail-closed race residue)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
