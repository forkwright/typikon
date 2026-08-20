#!/usr/bin/env python3
"""Causal snapshot fixture for the release compatibility-lock verifier."""

from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import release_archive as archive_verifier

SCRIPT = Path(__file__).resolve().parent / "verify-release-lock.py"
LOADER = importlib.machinery.SourceFileLoader("verify_release_lock", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
verifier = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(verifier)
SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "release" / "compatibility-lock.schema.json").read_text(
        encoding="utf-8"
    )
)


def git(root: Path, *args: str, binary: bool = False):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=not binary,
        check=True,
    )
    return result.stdout if binary else result.stdout.strip()


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(
        root,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-m",
        message,
    )
    return git(root, "rev-parse", "HEAD")


def zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in sorted(files.items()):
            archive.writestr(name, payload)
    return output.getvalue()


def rewrite_tar(
    payload: bytes,
    *,
    mutate=None,
    extra: list[tuple[tarfile.TarInfo, bytes | None]] | None = None,
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as source:
        with tarfile.open(
            fileobj=output,
            mode="w:gz",
            format=tarfile.PAX_FORMAT,
            pax_headers=dict(source.pax_headers),
        ) as destination:
            for source_member in source.getmembers():
                member = copy.copy(source_member)
                handle = source.extractfile(source_member) if source_member.isfile() else None
                body = handle.read() if handle is not None else None
                if mutate is not None:
                    mutate(member, body)
                destination.addfile(member, io.BytesIO(body) if body is not None else None)
            for member, body in extra or []:
                destination.addfile(member, io.BytesIO(body) if body is not None else None)
    return output.getvalue()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def expect_lock_error(call, fragment: str) -> None:
    try:
        call()
    except verifier.LockError as exc:
        if fragment not in str(exc):
            raise AssertionError(f"expected {fragment!r}, got {exc!r}") from exc
    else:
        raise AssertionError(f"verifier accepted mutant: {fragment}")


def receipt(consumer: dict[str, object]) -> bytes:
    value = {
        "schema_version": 1,
        "consumer": {
            "repository": consumer["repository"],
            "pull_request": consumer["pull_request"],
            "base_commit": consumer["base_commit"],
            "head_commit": consumer["head_commit"],
            "checkout_commit": consumer["merge_commit"],
            "checkout_tree": consumer["merge_tree"],
            "checkout_parents": [consumer["base_commit"], consumer["head_commit"]],
        },
        "typikon": {
            "path": "themes/typikon",
            "mode": "160000",
            "commit": consumer["gitlink_commit"],
            "tree": consumer["gitlink_tree"],
        },
        "workflow": {
            "path": consumer["workflow_path"],
            "commit": consumer["workflow_commit"],
            "blob": consumer["workflow_blob"],
            "run_id": consumer["workflow_run_id"],
            "run_attempt": consumer["run_attempt"],
            "event": "pull_request",
        },
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def build_fixture(root: Path):
    git(root, "init", "-q", "-b", "main")
    (root / "templates").mkdir()
    (root / "templates" / "page.html").write_text(
        "fixture template\n", encoding="utf-8"
    )
    (root / ".release-please-manifest.json").write_text(
        '{".": "0.4.0"}\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    old_leather = commit(root, "old leather pin")
    old_leather_tree = git(root, "rev-parse", "HEAD^{tree}")
    (root / ".release-please-manifest.json").write_text(
        '{".": "0.5.0"}\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.5.0\n", encoding="utf-8"
    )
    old_tools = commit(root, "old tools pin")
    old_tools_tree = git(root, "rev-parse", "HEAD^{tree}")
    (root / ".release-please-manifest.json").write_text(
        '{".": "0.6.0"}\n', encoding="utf-8"
    )
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.6.0](https://example.test/v0.6.0) (2026-08-20)\n\n"
        "### Features\n\n* exact release fixture\n",
        encoding="utf-8",
    )
    candidate = commit(root, "chore(main): release 0.6.0 (#182)")
    candidate_tree = git(root, "rev-parse", "HEAD^{tree}")
    release_head = "9" * 40
    archive = git(root, "archive", "--format=tar.gz", candidate, binary=True)
    checksum = f"{digest(archive)}  typikon-v0.6.0.tar.gz\n".encode()
    sbom = b'{"bomFormat":"CycloneDX","specVersion":"1.6"}\n'
    provenance_bundle = (
        b'{"mediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}\n'
    )
    sbom_bundle = (
        b'{"mediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}\n'
    )

    consumers = []
    definitions = [
        (
            "tools",
            "ardent-tools/ardent-tools-site",
            169,
            old_tools,
            old_tools_tree,
            "1",
        ),
        (
            "leather",
            "forkwright/ardent-site",
            37,
            old_leather,
            old_leather_tree,
            "2",
        ),
    ]
    for index, (identifier, repository, pr, previous, previous_tree, digit) in enumerate(
        definitions, start=1
    ):
        consumer = {
            "id": identifier,
            "repository": repository,
            "pull_request": pr,
            "base_commit": digit * 40,
            "head_commit": format(index + 2, "x") * 40,
            "head_tree": format(index + 4, "x") * 40,
            "merge_commit": format(index + 6, "x") * 40,
            "merge_tree": format(index + 8, "x") * 40,
            "gitlink_path": "themes/typikon",
            "previous_gitlink_commit": previous,
            "previous_gitlink_tree": previous_tree,
            "gitlink_commit": candidate,
            "gitlink_tree": candidate_tree,
            "workflow_path": ".github/workflows/deploy.yml",
            "workflow_commit": format(index + 6, "x") * 40,
            "workflow_blob": chr(ord("a") + index) * 40,
            "workflow_run_id": 1000 + index,
            "run_attempt": 1,
            "required_job": "gate-and-deploy",
            "receipt_path": f"release/compatibility/receipts/{identifier}.json",
            "receipt_sha256": "",
            "artifact_id": 2000 + index,
            "artifact_name": f"typikon-consumer-receipt-{1000 + index}-1",
            "artifact_digest": "",
        }
        receipt_bytes = receipt(consumer)
        receipt_zip = zip_bytes({"typikon-consumer-receipt.json": receipt_bytes})
        consumer["receipt_sha256"] = digest(receipt_bytes)
        consumer["artifact_digest"] = f"sha256:{digest(receipt_zip)}"
        consumer["_receipt"] = receipt_bytes
        consumer["_artifact"] = receipt_zip
        consumers.append(consumer)

    candidate_doc = {
        "schema_version": 1,
        "release": {
            "version": "0.6.0",
            "tag": "v0.6.0",
            "release_pr": 182,
            "candidate_commit": candidate,
            "candidate_tree": candidate_tree,
            "parent_commit": old_tools,
        },
        "workflow": {
            "repository": "forkwright/typikon",
            "run_id": 900,
            "run_attempt": 1,
        },
        "archive": {
            "name": "typikon-v0.6.0.tar.gz",
            "sha256": digest(archive),
            "size": len(archive),
        },
        "checksum": {
            "name": "typikon-v0.6.0.tar.gz.sha256",
            "sha256": digest(checksum),
            "size": len(checksum),
        },
        "sbom": {
            "name": "typikon-v0.6.0.tar.gz.cdx.json",
            "sha256": digest(sbom),
            "size": len(sbom),
        },
        "notes": {
            "body": "### Features\n\n* exact release fixture",
            "sha256": digest(b"### Features\n\n* exact release fixture"),
            "size": len(b"### Features\n\n* exact release fixture"),
        },
        "attestations": {
            "provenance": {
                "name": "typikon-v0.6.0.tar.gz.provenance.intoto.jsonl",
                "sha256": digest(provenance_bundle),
                "size": len(provenance_bundle),
            },
            "sbom": {
                "name": "typikon-v0.6.0.tar.gz.sbom.intoto.jsonl",
                "sha256": digest(sbom_bundle),
                "size": len(sbom_bundle),
            },
        },
    }
    candidate_json = (json.dumps(candidate_doc, indent=2, sort_keys=True) + "\n").encode()
    candidate_zip = zip_bytes(
        {
            "candidate.json": candidate_json,
            "typikon-v0.6.0.tar.gz": archive,
            "typikon-v0.6.0.tar.gz.sha256": checksum,
            "typikon-v0.6.0.tar.gz.cdx.json": sbom,
            "typikon-v0.6.0.tar.gz.provenance.intoto.jsonl": provenance_bundle,
            "typikon-v0.6.0.tar.gz.sbom.intoto.jsonl": sbom_bundle,
        }
    )

    lock_consumers = []
    for consumer in consumers:
        public = {key: value for key, value in consumer.items() if not key.startswith("_")}
        lock_consumers.append(public)
    lock = {
        "schema_version": 1,
        "release": {
            "version": "0.6.0",
            "tag": "v0.6.0",
            "release_pr": 182,
            "candidate_commit": candidate,
            "candidate_tree": candidate_tree,
        },
        "candidate_artifact": {
            "workflow_run_id": 900,
            "run_attempt": 1,
            "artifact_id": 1900,
            "artifact_name": "typikon-v0.6.0-candidate",
            "artifact_digest": f"sha256:{digest(candidate_zip)}",
            "archive_name": "typikon-v0.6.0.tar.gz",
            "archive_sha256": digest(archive),
            "archive_size": len(archive),
            "checksum_name": "typikon-v0.6.0.tar.gz.sha256",
            "checksum_sha256": digest(checksum),
            "checksum_size": len(checksum),
            "sbom_name": "typikon-v0.6.0.tar.gz.cdx.json",
            "sbom_sha256": digest(sbom),
            "sbom_size": len(sbom),
            "provenance_bundle_name": "typikon-v0.6.0.tar.gz.provenance.intoto.jsonl",
            "provenance_bundle_sha256": digest(provenance_bundle),
            "provenance_bundle_size": len(provenance_bundle),
            "sbom_bundle_name": "typikon-v0.6.0.tar.gz.sbom.intoto.jsonl",
            "sbom_bundle_sha256": digest(sbom_bundle),
            "sbom_bundle_size": len(sbom_bundle),
        },
        "consumers": lock_consumers,
    }

    receipt_dir = root / "release" / "compatibility" / "receipts"
    receipt_dir.mkdir(parents=True)
    for consumer in consumers:
        (root / consumer["receipt_path"]).write_bytes(consumer["_receipt"])
    lock_path = root / "release" / "compatibility" / "v0.6.0.json"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence = commit(root, "chore(release): lock v0.6.0 compatibility evidence")

    snapshot = {
        "forkwright/typikon|pulls/182": {
            "merged": True,
            "merge_commit_sha": candidate,
            "title": "chore(main): release 0.6.0",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
            "base": {
                "ref": "main",
                "sha": old_tools,
                "repo": {"full_name": "forkwright/typikon"},
            },
            "head": {
                "ref": "release-please--branches--main",
                "sha": release_head,
                "repo": {"full_name": "forkwright/typikon"},
            },
            "labels": [{"name": "autorelease: pending"}],
        },
        f"forkwright/typikon|git/commits/{candidate}": {
            "tree": {"sha": candidate_tree},
            "parents": [{"sha": old_tools}],
        },
        f"forkwright/typikon|git/commits/{release_head}": {
            "tree": {"sha": candidate_tree}
        },
        f"forkwright/typikon|git/commits/{old_tools}": {
            "tree": {"sha": old_tools_tree}
        },
        f"forkwright/typikon|git/commits/{old_leather}": {
            "tree": {"sha": old_leather_tree}
        },
        "forkwright/typikon|actions/runs/900": {
            "status": "completed",
            "conclusion": "success",
            "event": "push",
            "head_sha": candidate,
            "run_attempt": 1,
            "path": ".github/workflows/release-candidate.yml",
            "pull_requests": [],
        },
        "forkwright/typikon|actions/runs/900/attempts/1/jobs?per_page=100": {
            "jobs": [{"name": "freeze-candidate", "conclusion": "success"}]
        },
        "forkwright/typikon|actions/artifacts/1900": {
            "expired": False,
            "name": "typikon-v0.6.0-candidate",
            "digest": f"sha256:{digest(candidate_zip)}",
            "workflow_run": {"id": 900},
        },
        "forkwright/typikon|artifact_zip/1900": base64.b64encode(candidate_zip).decode(),
    }

    for consumer in consumers:
        repo = consumer["repository"]
        pr = consumer["pull_request"]
        snapshot[f"{repo}|pulls/{pr}"] = {
            "state": "open",
            "base": {
                "ref": "main",
                "sha": consumer["base_commit"],
                "repo": {"full_name": repo},
            },
            "head": {
                "sha": consumer["head_commit"],
                "repo": {"full_name": repo},
            },
            "merge_commit_sha": consumer["merge_commit"],
        }
        base_tree = ("c" if consumer["id"] == "tools" else "d") * 40
        snapshot[f"{repo}|git/commits/{consumer['base_commit']}"] = {
            "tree": {"sha": base_tree}
        }
        snapshot[f"{repo}|git/commits/{consumer['head_commit']}"] = {
            "tree": {"sha": consumer["head_tree"]}
        }
        snapshot[f"{repo}|git/commits/{consumer['merge_commit']}"] = {
            "tree": {"sha": consumer["merge_tree"]},
            "parents": [
                {"sha": consumer["base_commit"]},
                {"sha": consumer["head_commit"]},
            ],
        }
        snapshot[f"{repo}|git/trees/{base_tree}?recursive=1"] = {
            "tree": [
                {
                    "path": "themes/typikon",
                    "mode": "160000",
                    "sha": consumer["previous_gitlink_commit"],
                }
            ]
        }
        snapshot[f"{repo}|git/trees/{consumer['merge_tree']}?recursive=1"] = {
            "tree": [
                {
                    "path": "themes/typikon",
                    "mode": "160000",
                    "sha": candidate,
                },
                {
                    "path": consumer["workflow_path"],
                    "mode": "100644",
                    "sha": consumer["workflow_blob"],
                },
            ]
        }
        run_id = consumer["workflow_run_id"]
        snapshot[f"{repo}|actions/runs/{run_id}"] = {
            "status": "completed",
            "conclusion": "success",
            "event": "pull_request",
            "head_sha": consumer["head_commit"],
            "run_attempt": 1,
            "path": consumer["workflow_path"],
            "pull_requests": [
                {
                    "number": pr,
                    "head": {"sha": consumer["head_commit"]},
                    "base": {"sha": consumer["base_commit"]},
                }
            ],
        }
        snapshot[f"{repo}|actions/runs/{run_id}/attempts/1/jobs?per_page=100"] = {
            "jobs": [{"name": "gate-and-deploy", "conclusion": "success"}]
        }
        snapshot[f"{repo}|actions/artifacts/{consumer['artifact_id']}"] = {
            "expired": False,
            "name": consumer["artifact_name"],
            "digest": consumer["artifact_digest"],
            "workflow_run": {"id": run_id},
        }
        snapshot[f"{repo}|artifact_zip/{consumer['artifact_id']}"] = base64.b64encode(
            consumer["_artifact"]
        ).decode()
    return lock, lock_path, snapshot, evidence


class RedirectApi(BaseHTTPRequestHandler):
    target = ""
    authorization = None

    def do_GET(self):  # noqa: N802
        type(self).authorization = self.headers.get("Authorization")
        self.send_response(302)
        self.send_header("Location", type(self).target)
        self.end_headers()

    def log_message(self, *args):
        pass


class RedirectTarget(BaseHTTPRequestHandler):
    authorization = None

    def do_GET(self):  # noqa: N802
        type(self).authorization = self.headers.get("Authorization")
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def redirect_probe() -> None:
    target = ThreadingHTTPServer(("127.0.0.1", 0), RedirectTarget)
    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectApi)
    RedirectApi.target = f"http://127.0.0.1:{target.server_port}/signed"
    threads = [
        threading.Thread(target=target.serve_forever, daemon=True),
        threading.Thread(target=source.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        token = verifier.SecretToken("fixture-token")
        assert str(token) == "[REDACTED]"
        assert "fixture-token" not in repr(token)
        try:
            verifier.download_signed_redirect(
                f"http://127.0.0.1:{source.server_port}/artifact",
                "fixture-token",
                require_https=False,
            )
        except TypeError:
            pass
        else:
            raise AssertionError("artifact downloader accepted a bare token string")
        payload = verifier.download_signed_redirect(
            f"http://127.0.0.1:{source.server_port}/artifact",
            token,
            require_https=False,
        )
        assert payload == b"ok"
        assert RedirectApi.authorization == "Bearer fixture-token"
        assert RedirectTarget.authorization is None
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()


def main() -> int:
    original_root = verifier.ROOT
    with tempfile.TemporaryDirectory(prefix="typikon-release-lock-") as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        lock, lock_path, snapshot, evidence = build_fixture(root)
        verifier.ROOT = root
        os.environ.pop("GITHUB_ACTIONS", None)
        jsonschema.Draft202012Validator(SCHEMA).validate(lock)
        assert verifier.validate_lock_shape(copy.deepcopy(lock)) == lock

        bundles = verifier.verify_live(lock, verifier.GitHub(snapshot), lock_path)
        verifier.validate_bundle(lock, bundles)

        archive_name = lock["candidate_artifact"]["archive_name"]
        frozen_archive = bundles["candidate"][archive_name]
        tar_bytes = gzip.decompress(frozen_archive)
        recompressed = gzip.compress(tar_bytes, compresslevel=1, mtime=0)
        verifier.verify_archive(
            recompressed, root, lock["release"]["candidate_commit"]
        )
        corrupted_tar = tar_bytes.replace(b'"0.6.0"', b'"9.9.9"', 1)
        if corrupted_tar == tar_bytes:
            raise AssertionError("archive content mutant did not change fixture bytes")
        try:
            verifier.verify_archive(
                gzip.compress(corrupted_tar, mtime=0),
                root,
                lock["release"]["candidate_commit"],
            )
        except verifier.ArchiveError:
            pass
        else:
            raise AssertionError("archive verifier accepted changed tree content")

        for label, changed_mode in (("permission drift", 0o644), ("setuid", 0o4664)):
            changed = False

            def mutate_file_mode(member, _body):
                nonlocal changed
                if not changed and member.isfile():
                    member.mode = changed_mode
                    changed = True

            mode_mutant = rewrite_tar(frozen_archive, mutate=mutate_file_mode)
            try:
                verifier.verify_archive(
                    mode_mutant, root, lock["release"]["candidate_commit"]
                )
            except verifier.ArchiveError:
                pass
            else:
                raise AssertionError(f"archive verifier accepted {label}")

        changed_directory = False

        def mutate_directory_mode(member, _body):
            nonlocal changed_directory
            if not changed_directory and member.isdir():
                member.mode = 0o777
                changed_directory = True

        directory_mode_mutant = rewrite_tar(
            frozen_archive, mutate=mutate_directory_mode
        )
        try:
            verifier.verify_archive(
                directory_mode_mutant, root, lock["release"]["candidate_commit"]
            )
        except verifier.ArchiveError:
            pass
        else:
            raise AssertionError("archive verifier accepted directory mode drift")

        extra_directory = tarfile.TarInfo("untracked/")
        extra_directory.type = tarfile.DIRTYPE
        extra_directory.mode = 0o775
        extra_directory_mutant = rewrite_tar(
            frozen_archive, extra=[(extra_directory, None)]
        )
        try:
            verifier.verify_archive(
                extra_directory_mutant, root, lock["release"]["candidate_commit"]
            )
        except verifier.ArchiveError:
            pass
        else:
            raise AssertionError("archive verifier accepted an extra directory")

        with tarfile.open(fileobj=io.BytesIO(frozen_archive), mode="r:gz") as source:
            original_content_bytes = sum(
                member.size for member in source.getmembers() if member.isfile()
            )
        extra_file = tarfile.TarInfo("aggregate-overflow")
        extra_file.mode = 0o664
        extra_file.size = 1
        aggregate_mutant = rewrite_tar(
            frozen_archive, extra=[(extra_file, b"x")]
        )
        original_limit = archive_verifier.MAX_ARCHIVE_CONTENT_BYTES
        archive_verifier.MAX_ARCHIVE_CONTENT_BYTES = original_content_bytes
        try:
            try:
                verifier.verify_archive(
                    aggregate_mutant, root, lock["release"]["candidate_commit"]
                )
            except verifier.ArchiveError as exc:
                if "expands beyond" not in str(exc):
                    raise AssertionError(
                        f"aggregate archive limit failed for the wrong reason: {exc}"
                    ) from exc
            else:
                raise AssertionError("archive verifier accepted aggregate overflow")
        finally:
            archive_verifier.MAX_ARCHIVE_CONTENT_BYTES = original_limit

        expired = copy.deepcopy(snapshot)
        expired["forkwright/typikon|actions/artifacts/1900"]["expired"] = True
        expect_lock_error(
            lambda: verifier.verify_live(lock, verifier.GitHub(expired), lock_path),
            "expired",
        )

        wrong_pr = copy.deepcopy(snapshot)
        wrong_pr["ardent-tools/ardent-tools-site|pulls/169"]["base"]["ref"] = "staging"
        expect_lock_error(
            lambda: verifier.verify_live(lock, verifier.GitHub(wrong_pr), lock_path),
            "does not target owned main",
        )

        for label, mutate in (
            (
                "title",
                lambda value: value["forkwright/typikon|pulls/182"].__setitem__(
                    "title", "chore(main): release 0.6.1"
                ),
            ),
            (
                "head ref",
                lambda value: value["forkwright/typikon|pulls/182"]["head"].__setitem__(
                    "ref", "manual-release"
                ),
            ),
            (
                "bot author",
                lambda value: value["forkwright/typikon|pulls/182"]["user"].__setitem__(
                    "login", "operator"
                ),
            ),
            (
                "bot author type",
                lambda value: value["forkwright/typikon|pulls/182"]["user"].__setitem__(
                    "type", "User"
                ),
            ),
            (
                "base ref",
                lambda value: value["forkwright/typikon|pulls/182"]["base"].__setitem__(
                    "ref", "staging"
                ),
            ),
            (
                "base repo",
                lambda value: value["forkwright/typikon|pulls/182"]["base"][
                    "repo"
                ].__setitem__("full_name", "forkwright/other"),
            ),
            (
                "base subject",
                lambda value: value["forkwright/typikon|pulls/182"]["base"].__setitem__(
                    "sha", "0" * 40
                ),
            ),
            (
                "head repo",
                lambda value: value["forkwright/typikon|pulls/182"]["head"][
                    "repo"
                ].__setitem__("full_name", "forkwright/other"),
            ),
        ):
            wrong_release_pr = copy.deepcopy(snapshot)
            mutate(wrong_release_pr)
            expect_lock_error(
                lambda value=wrong_release_pr: verifier.verify_live(
                    lock, verifier.GitHub(value), lock_path
                ),
                "exact Release Please main-branch proposal",
            )

        no_release_label = copy.deepcopy(snapshot)
        no_release_label["forkwright/typikon|pulls/182"]["labels"] = []
        expect_lock_error(
            lambda: verifier.verify_live(
                lock, verifier.GitHub(no_release_label), lock_path
            ),
            "no Release Please lifecycle label",
        )

        wrong_release_head = copy.deepcopy(snapshot)
        release_pr = wrong_release_head["forkwright/typikon|pulls/182"]
        release_head = release_pr["head"]["sha"]
        wrong_release_head[f"forkwright/typikon|git/commits/{release_head}"][
            "tree"
        ]["sha"] = "0" * 40
        expect_lock_error(
            lambda: verifier.verify_live(
                lock, verifier.GitHub(wrong_release_head), lock_path
            ),
            "Release Please head tree",
        )

        wrong_release_parent = copy.deepcopy(snapshot)
        candidate_commit = lock["release"]["candidate_commit"]
        wrong_release_parent[
            f"forkwright/typikon|git/commits/{candidate_commit}"
        ]["parents"] = [{"sha": "0" * 40}]
        expect_lock_error(
            lambda: verifier.verify_live(
                lock, verifier.GitHub(wrong_release_parent), lock_path
            ),
            "candidate parent differs",
        )

        wrong_parents = copy.deepcopy(snapshot)
        wrong_parents[
            f"ardent-tools/ardent-tools-site|git/commits/{lock['consumers'][0]['merge_commit']}"
        ]["parents"].reverse()
        expect_lock_error(
            lambda: verifier.verify_live(
                lock, verifier.GitHub(wrong_parents), lock_path
            ),
            "merge parents drifted",
        )

        failed_job = copy.deepcopy(snapshot)
        failed_job[
            "forkwright/ardent-site|actions/runs/1002/attempts/1/jobs?per_page=100"
        ]["jobs"][0]["conclusion"] = "failure"
        expect_lock_error(
            lambda: verifier.verify_live(lock, verifier.GitHub(failed_job), lock_path),
            "required job",
        )

        paged_jobs = copy.deepcopy(snapshot)
        tools_jobs = (
            "ardent-tools/ardent-tools-site|"
            "actions/runs/1001/attempts/1/jobs?per_page=100"
        )
        paged_jobs[tools_jobs]["jobs"] = [
            {"name": f"decoy-{index}", "conclusion": "success"}
            for index in range(100)
        ]
        paged_jobs[f"{tools_jobs}&page=2"] = {
            "jobs": [{"name": "gate-and-deploy", "conclusion": "success"}]
        }
        verifier.verify_live(lock, verifier.GitHub(paged_jobs), lock_path)

        duplicate_paged_job = copy.deepcopy(paged_jobs)
        duplicate_paged_job[tools_jobs]["jobs"][-1] = {
            "name": "gate-and-deploy",
            "conclusion": "success",
        }
        expect_lock_error(
            lambda: verifier.verify_live(
                lock, verifier.GitHub(duplicate_paged_job), lock_path
            ),
            "required job is not exactly one success",
        )

        vacuous_rollback = copy.deepcopy(lock)
        vacuous_rollback["consumers"][0]["previous_gitlink_commit"] = vacuous_rollback[
            "consumers"
        ][0]["gitlink_commit"]
        expect_lock_error(
            lambda: verifier.verify_live(
                vacuous_rollback, verifier.GitHub(snapshot), lock_path
            ),
            "rollback and promotion gitlinks are identical",
        )

        wrong_rollback = copy.deepcopy(lock)
        wrong_rollback["consumers"][0]["previous_gitlink_tree"] = "f" * 40
        expect_lock_error(
            lambda: verifier.verify_live(
                wrong_rollback, verifier.GitHub(snapshot), lock_path
            ),
            "rollback Typikon tree drifted",
        )

        wrong_workflow = copy.deepcopy(lock)
        wrong_workflow["consumers"][1]["workflow_blob"] = "0" * 40
        expect_lock_error(
            lambda: verifier.verify_live(
                wrong_workflow, verifier.GitHub(snapshot), lock_path
            ),
            "workflow blob drifted",
        )

        wrong_workflow_subject = copy.deepcopy(lock)
        wrong_workflow_subject["consumers"][0]["workflow_commit"] = "0" * 40
        expect_lock_error(
            lambda: verifier.validate_lock_shape(wrong_workflow_subject),
            "workflow commit is not its synthetic merge commit",
        )

        wrong_zip = copy.deepcopy(snapshot)
        wrong_zip["forkwright/typikon|artifact_zip/1900"] = base64.b64encode(
            b"not the artifact"
        ).decode()
        expect_lock_error(
            lambda: verifier.verify_live(lock, verifier.GitHub(wrong_zip), lock_path),
            "downloaded artifact digest",
        )

        extra_member_lock = copy.deepcopy(lock)
        extra_member_snapshot = copy.deepcopy(snapshot)
        consumer = extra_member_lock["consumers"][0]
        receipt_bytes = (root / consumer["receipt_path"]).read_bytes()
        extra_zip = zip_bytes(
            {"typikon-consumer-receipt.json": receipt_bytes, "extra.txt": b"extra"}
        )
        extra_digest = f"sha256:{digest(extra_zip)}"
        consumer["artifact_digest"] = extra_digest
        artifact_key = f"{consumer['repository']}|actions/artifacts/{consumer['artifact_id']}"
        zip_key = f"{consumer['repository']}|artifact_zip/{consumer['artifact_id']}"
        extra_member_snapshot[artifact_key]["digest"] = extra_digest
        extra_member_snapshot[zip_key] = base64.b64encode(extra_zip).decode()
        expect_lock_error(
            lambda: verifier.verify_live(
                extra_member_lock, verifier.GitHub(extra_member_snapshot), lock_path
            ),
            "artifact members",
        )

        duplicate = copy.deepcopy(lock)
        duplicate["consumers"][1] = copy.deepcopy(duplicate["consumers"][0])
        try:
            jsonschema.Draft202012Validator(SCHEMA).validate(duplicate)
        except jsonschema.ValidationError:
            pass
        else:
            raise AssertionError("schema accepted a duplicate cohort tuple")
        expect_lock_error(
            lambda: verifier.validate_lock_shape(duplicate),
            "cohort tuple",
        )

        for label, mutate in (
            (
                "malformed candidate SHA",
                lambda value: value["release"].__setitem__("candidate_commit", "abc"),
            ),
            (
                "wrong candidate member name",
                lambda value: value["candidate_artifact"].__setitem__(
                    "checksum_name", "other.sha256"
                ),
            ),
            (
                "unknown lock field",
                lambda value: value.__setitem__("surprise", True),
            ),
            (
                "boolean schema version",
                lambda value: value.__setitem__("schema_version", True),
            ),
            (
                "boolean release PR",
                lambda value: value["release"].__setitem__("release_pr", True),
            ),
            (
                "boolean artifact ID",
                lambda value: value["candidate_artifact"].__setitem__(
                    "artifact_id", True
                ),
            ),
            (
                "boolean consumer run ID",
                lambda value: value["consumers"][0].__setitem__(
                    "workflow_run_id", True
                ),
            ),
        ):
            malformed = copy.deepcopy(lock)
            mutate(malformed)
            try:
                jsonschema.Draft202012Validator(SCHEMA).validate(malformed)
            except jsonschema.ValidationError:
                pass
            else:
                raise AssertionError(f"JSON Schema accepted {label}")
            try:
                verifier.validate_lock_shape(malformed)
            except verifier.LockError:
                pass
            else:
                raise AssertionError(f"stdlib lock validator accepted {label}")

        tagged_without_release = copy.deepcopy(snapshot)
        tagged_without_release["forkwright/typikon|pulls/182"]["labels"] = [
            {"name": "autorelease: tagged"}
        ]
        expect_lock_error(
            lambda: verifier.verify_live(
                lock, verifier.GitHub(tagged_without_release), lock_path
            ),
            "without an exact published release",
        )

        saved_tokens = {
            name: os.environ.pop(name, None)
            for name in ("TOOLS_RECEIPT_TOKEN", "LEATHER_RECEIPT_TOKEN")
        }
        try:
            expect_lock_error(
                lambda: verifier.GitHub().get(
                    "ardent-tools/ardent-tools-site", "pulls/169"
                ),
                "TOOLS_RECEIPT_TOKEN is required",
            )
            expect_lock_error(
                lambda: verifier.GitHub().artifact_zip("forkwright/ardent-site", 2002),
                "LEATHER_RECEIPT_TOKEN is required",
            )
        finally:
            for name, value in saved_tokens.items():
                if value is not None:
                    os.environ[name] = value

        (root / "forbidden.txt").write_text("post-candidate drift\n", encoding="utf-8")
        commit(root, "forbidden evidence drift")
        expect_lock_error(
            lambda: verifier.verify_evidence_delta(lock, lock_path),
            "evidence delta",
        )
        git(root, "reset", "--hard", evidence)

    verifier.ROOT = original_root
    redirect_probe()
    print("check-release-lock: ok (live snapshot, artifact, cohort, and auth mutants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
