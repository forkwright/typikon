#!/usr/bin/env python3
"""Causal fixture for detecting and freezing an exact untagged release commit."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "build-release-candidate.py"
LOADER = importlib.machinery.SourceFileLoader("build_release_candidate", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
candidate = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(candidate)


def bundle(kind: str, archive_name: str, digest: str) -> str:
    predicate = {
        "provenance": "https://slsa.dev/provenance/v1",
        "sbom": "https://cyclonedx.org/bom",
    }[kind]
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": archive_name, "digest": {"sha256": digest}}],
        "predicateType": predicate,
        "predicate": {},
    }
    record = {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {"certificate": {"rawBytes": "fixture"}},
        "dsseEnvelope": {
            "payloadType": "application/vnd.in-toto+json",
            "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
            "signatures": [{"sig": "fixture"}],
        },
    }
    return json.dumps(record) + "\n"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


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


def main() -> int:
    blocked_inventory = candidate.component_inventory
    candidate.component_inventory = candidate.validated_component_inventory
    with tempfile.TemporaryDirectory(prefix="typikon-release-candidate-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / ".release-please-manifest.json").write_text(
            '{".": "0.5.0"}\n', encoding="utf-8"
        )
        (repo / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        (repo / "static" / "fonts").mkdir(parents=True)
        (repo / "static" / "fonts" / "fixture.woff2").write_bytes(b"font fixture")
        (repo / "release").mkdir()
        (repo / "release" / "components.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "components": [
                        {
                            "name": "Fixture WOFF2",
                            "version": "1.0.0",
                            "purl": "pkg:generic/fixture-font@1.0.0?file_name=fixture.woff2",
                            "scope": "required",
                            "license": "OFL-1.1",
                            "hash": {
                                "kind": "repository-file",
                                "path": "static/fonts/fixture.woff2",
                            },
                        },
                        {
                            "name": "Fixture renderer",
                            "version": "2.0.0",
                            "purl": "pkg:generic/fixture-renderer@2.0.0?arch=x86_64&os=linux",
                            "scope": "required",
                            "license": "MIT",
                            "hash": {
                                "kind": "external-distribution",
                                "url": "https://example.test/fixture-renderer.tar.gz",
                                "sha256": "1" * 64,
                            },
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        commit(repo, "initial")
        (repo / ".release-please-manifest.json").write_text(
            '{".": "0.6.0"}\n', encoding="utf-8"
        )
        (repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [0.6.0](https://example.test/v0.6.0) (2026-08-20)\n\n"
            "### Features\n\n* exact fixture release\n",
            encoding="utf-8",
        )
        release_commit = commit(repo, "chore(main): release 0.6.0 (#182)")

        candidate.ROOT = repo
        identity = candidate.release_identity()
        assert identity is not None
        assert identity["candidate_commit"] == release_commit
        assert identity["version"] == "0.6.0"
        assert identity["release_pr"] == 182

        git(repo, "tag", "v0.6.0", release_commit)
        try:
            candidate.release_identity()
        except candidate.CandidateError as exc:
            assert "already tagged" in str(exc)
        else:
            raise AssertionError("candidate accepted an already-published tag subject")
        git(repo, "tag", "-d", "v0.6.0")

        output = Path(tmp) / "candidate"
        output.mkdir()
        archive = output / "typikon-v0.6.0.tar.gz"
        archive.write_bytes(b"stale archive must be overwritten")
        sbom = output / "typikon-v0.6.0.tar.gz.cdx.json"
        candidate.seed_sbom(output)
        before = archive.read_bytes()
        os.environ.update(
            {
                "GITHUB_REPOSITORY": "forkwright/typikon",
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
            }
        )
        manifest_path = candidate.freeze(output)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert archive.read_bytes() != before
        assert manifest["release"]["candidate_commit"] == release_commit
        assert manifest["archive"]["size"] == archive.stat().st_size
        assert manifest["checksum"]["name"] == "typikon-v0.6.0.tar.gz.sha256"
        checksum = output / manifest["checksum"]["name"]
        assert checksum.read_text() == f"{candidate.sha256(archive)}  {archive.name}\n"
        assert manifest["notes"]["body"] == "### Features\n\n* exact fixture release"
        assert manifest["notes"]["sha256"] == candidate.sha256_bytes(
            manifest["notes"]["body"].encode()
        )
        sbom_doc = json.loads(sbom.read_text())
        root_component = sbom_doc["metadata"]["component"]
        assert root_component["name"] == "typikon"
        assert root_component["version"] == "0.6.0"
        assert root_component["purl"] == "pkg:github/forkwright/typikon@0.6.0"
        assert root_component["hashes"][0]["content"] == candidate.sha256(archive)
        assert sbom_doc["serialNumber"].startswith("urn:uuid:")
        assert {component["purl"] for component in sbom_doc["components"]} == {
            "pkg:generic/fixture-font@1.0.0?file_name=fixture.woff2",
            "pkg:generic/fixture-renderer@2.0.0?arch=x86_64&os=linux",
        }
        dependency_rows = {
            row["ref"]: row["dependsOn"] for row in sbom_doc["dependencies"]
        }
        assert dependency_rows[root_component["purl"]] == sorted(
            component["purl"] for component in sbom_doc["components"]
        )
        assert all(
            dependency_rows[component["purl"]] == []
            for component in sbom_doc["components"]
        )

        provenance = Path(tmp) / "provenance.jsonl"
        sbom_bundle = Path(tmp) / "sbom.jsonl"
        archive_digest = candidate.sha256(archive)
        provenance.write_text(bundle("provenance", archive.name, archive_digest))
        sbom_bundle.write_text(bundle("sbom", archive.name, archive_digest))
        candidate.attach_attestations(output, provenance, sbom_bundle)
        finalized = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert set(finalized["attestations"]) == {"provenance", "sbom"}
        for item in finalized["attestations"].values():
            assert (output / item["name"]).is_file()
            assert item["sha256"] == candidate.sha256(output / item["name"])

        malformed_bundle = Path(tmp) / "malformed.jsonl"
        malformed_bundle.write_text("not json\n")
        try:
            candidate.read_bundle(
                malformed_bundle, "provenance", archive.name, archive_digest
            )
        except candidate.CandidateError as exc:
            assert "invalid JSONL" in str(exc)
        else:
            raise AssertionError("candidate accepted a malformed attestation bundle")

        empty_bundle = Path(tmp) / "empty.jsonl"
        empty_bundle.write_text("{}\n")
        try:
            candidate.read_bundle(
                empty_bundle, "provenance", archive.name, archive_digest
            )
        except candidate.CandidateError as exc:
            assert "Sigstore media type" in str(exc)
        else:
            raise AssertionError("candidate accepted an unbound attestation object")

        wrong_subject = Path(tmp) / "wrong-subject.jsonl"
        wrong_subject.write_text(bundle("provenance", archive.name, "0" * 64))
        try:
            candidate.read_bundle(
                wrong_subject, "provenance", archive.name, archive_digest
            )
        except candidate.CandidateError as exc:
            assert "subject differs" in str(exc)
        else:
            raise AssertionError("candidate accepted an attestation for other bytes")

        complete_component = {
            "type": "library",
            "name": "fixture dependency",
            "version": "1.0.0",
            "purl": "pkg:generic/fixture-dependency@1.0.0",
            "scope": "required",
            "licenses": [{"expression": "MIT"}],
            "hashes": [{"alg": "SHA-256", "content": "0" * 64}],
        }

        def reject_sbom(mutator, fragment: str) -> None:
            document = {
                "bomFormat": "CycloneDX",
                "serialNumber": sbom_doc["serialNumber"],
                "specVersion": "1.6",
                "components": [json.loads(json.dumps(complete_component))],
                "dependencies": [],
            }
            mutator(document)
            try:
                candidate.normalize_and_validate_sbom(document, identity, archive)
            except candidate.CandidateError:
                return
            raise AssertionError(f"SBOM validator accepted {fragment}")

        reject_sbom(lambda value: value.update(specVersion="1.4"), "CycloneDX 1.4")
        reject_sbom(
            lambda value: value.pop("serialNumber"),
            "SBOM without a candidate-bound serial number",
        )
        for field in ("purl", "scope"):
            reject_sbom(
                lambda value, field=field: value["components"][0].pop(field),
                f"component missing {field}",
            )
        reject_sbom(
            lambda value: value["components"][0].update(scope="runtime-ish"),
            "component with invalid scope",
        )
        reject_sbom(
            lambda value: value["components"][0].pop("licenses"),
            "component missing license",
        )
        reject_sbom(
            lambda value: value["components"][0].pop("hashes"),
            "component missing SHA-256",
        )
        reject_sbom(
            lambda value: value["components"][0].update(
                components=[{"type": "library", "name": "nested incomplete"}]
            ),
            "nested incomplete component",
        )

        inventory = repo / "release" / "components.json"
        inventory_doc = json.loads(inventory.read_text())
        inventory_doc["components"] = inventory_doc["components"][1:]
        inventory.write_text(json.dumps(inventory_doc), encoding="utf-8")
        try:
            candidate.component_inventory()
        except candidate.CandidateError as exc:
            assert "does not exactly cover embedded files" in str(exc)
        else:
            raise AssertionError("inventory accepted an unowned embedded font")
        git(repo, "checkout", "--", "release/components.json")

        inventory_doc = json.loads(inventory.read_text())
        inventory_doc["components"] = inventory_doc["components"][:1]
        inventory.write_text(json.dumps(inventory_doc), encoding="utf-8")
        try:
            candidate.component_inventory()
        except candidate.CandidateError as exc:
            assert "no external distribution" in str(exc)
        else:
            raise AssertionError("inventory accepted no external runtime distribution")
        git(repo, "checkout", "--", "release/components.json")

        # A release-shaped commit with an unrelated file is not a pure,
        # untagged candidate and must fail rather than silently absorb it.
        git(repo, "reset", "--hard", "HEAD^")
        (repo / ".release-please-manifest.json").write_text(
            '{".": "0.6.0"}\n', encoding="utf-8"
        )
        (repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [0.6.0](https://example.test/v0.6.0)\n\n* release\n"
        )
        (repo / "unrelated.txt").write_text("not release material\n")
        commit(repo, "chore(main): release 0.6.0 (#182)")
        try:
            candidate.release_identity()
        except candidate.CandidateError as exc:
            assert "may change only" in str(exc)
        else:
            raise AssertionError("candidate accepted an unrelated changed file")

        # A normal merge can present the same final two-file diff, but it is
        # not the squash subject whose commit/archive consumers must test.
        initial = git(repo, "rev-parse", f"{release_commit}^")
        git(repo, "reset", "--hard", initial)
        git(repo, "checkout", "-q", "-b", "release-fixture")
        (repo / ".release-please-manifest.json").write_text(
            '{".": "0.6.0"}\n', encoding="utf-8"
        )
        (repo / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [0.6.0](https://example.test/v0.6.0)\n\n* release\n",
            encoding="utf-8",
        )
        commit(repo, "release side")
        git(repo, "checkout", "-q", "main")
        (repo / "side.txt").write_text("side history\n", encoding="utf-8")
        commit(repo, "main side")
        git(
            repo,
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.test",
            "merge",
            "--no-ff",
            "release-fixture",
            "-m",
            "chore(main): release 0.6.0 (#182)",
        )
        try:
            candidate.release_identity()
        except candidate.CandidateError as exc:
            assert "one-parent squash" in str(exc)
        else:
            raise AssertionError("candidate accepted a two-parent merge")

    candidate.ROOT = SCRIPT.parent.parent
    candidate.component_inventory = blocked_inventory
    try:
        candidate.component_inventory()
    except candidate.CandidateError as exc:
        if "forkwright/typikon#58" not in str(exc):
            raise
    else:
        raise AssertionError("current incomplete release dependency graph did not block")

    real_inventory = candidate.validated_component_inventory()
    if len(real_inventory) != 9:
        raise AssertionError(
            f"real release inventory must contain Zola plus eight fonts, found {len(real_inventory)}"
        )
    if [item["name"] for item in real_inventory].count("Zola") != 1:
        raise AssertionError("real release inventory does not contain exactly one Zola")

    print("check-release-candidate: ok (stale bytes and impure commit rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
