#!/usr/bin/env python3
"""Detect and freeze an untagged Release Please merge commit."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toollock  # noqa: E402

LOCK_PATH = Path(__file__).resolve().parent / "tool-lock.toml"

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ".release-please-manifest.json"
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
RELEASE_COMMIT = re.compile(r"\(#(?P<pr>[1-9][0-9]*)\)\s*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ROOT_PURL = "pkg:github/forkwright/typikon"
ROOT_LICENSE = "LicenseRef-PolyForm-Noncommercial-1.0.0"
EMBEDDED_COMPONENT_GLOBS = ("static/fonts/*.woff2",)


class CandidateError(RuntimeError):
    pass


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise CandidateError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def git_succeeds(*args: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(ROOT), *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def manifest_at(revision: str) -> str:
    raw = json.loads(git("show", f"{revision}:{MANIFEST}"))
    if set(raw) != {"."} or not isinstance(raw["."], str):
        raise CandidateError(f"{MANIFEST} must contain exactly the root package version")
    version = raw["."]
    if not SEMVER.fullmatch(version):
        raise CandidateError(f"invalid release version {version!r}")
    return version


def release_identity() -> dict[str, object] | None:
    parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    if len(parents) != 1:
        changed_from_first_parent = (
            set(git("diff", "--name-only", parents[0], "HEAD").splitlines())
            if parents
            else set()
        )
        if MANIFEST in changed_from_first_parent:
            raise CandidateError("a release candidate must be a one-parent squash commit")
        return None
    try:
        parent = parents[0]
    except CandidateError:
        return None
    changed = set(git("diff", "--name-only", "HEAD^", "HEAD").splitlines())
    if MANIFEST not in changed:
        return None
    if changed != {MANIFEST, "CHANGELOG.md"}:
        raise CandidateError(
            "a release-candidate commit may change only CHANGELOG.md and "
            f"{MANIFEST}; found {sorted(changed)}"
        )
    previous = manifest_at("HEAD^")
    version = manifest_at("HEAD")
    if tuple(map(int, version.split("."))) <= tuple(map(int, previous.split("."))):
        raise CandidateError(f"release version {version} does not advance {previous}")
    tag = f"v{version}"
    if git_succeeds("show-ref", "--verify", "--quiet", f"refs/tags/{tag}"):
        raise CandidateError(f"release candidate {tag} is already tagged")
    subject = git("show", "-s", "--format=%s", "HEAD")
    match = RELEASE_COMMIT.search(subject)
    if match is None:
        raise CandidateError("release-candidate commit subject must end in '(#PR)' provenance")
    return {
        "version": version,
        "tag": tag,
        "release_pr": int(match.group("pr")),
        "candidate_commit": git("rev-parse", "HEAD"),
        "candidate_tree": git("rev-parse", "HEAD^{tree}"),
        "parent_commit": parent,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def release_notes(version: str) -> str:
    try:
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    except OSError as exc:
        raise CandidateError(f"cannot read CHANGELOG.md: {exc}") from exc
    header = re.compile(rf"^## \[{re.escape(version)}\].*$", re.MULTILINE)
    matches = list(header.finditer(text))
    if len(matches) != 1:
        raise CandidateError(
            f"CHANGELOG.md must contain exactly one release heading for {version}"
        )
    start = matches[0].end()
    following = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + following.start() if following else len(text)
    notes = text[start:end].strip()
    if not notes:
        raise CandidateError(f"CHANGELOG.md release section {version} is empty")
    return notes


def validated_component_inventory() -> list[dict[str, object]]:
    inventory_path = ROOT / "release" / "components.json"
    try:
        value = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateError(f"cannot read release component inventory: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "components"}:
        raise CandidateError("release component inventory has unexpected fields")
    if value["schema_version"] != 1:
        raise CandidateError("release component inventory schema_version must be 1")
    raw_components = value["components"]
    if not isinstance(raw_components, list) or not raw_components:
        raise CandidateError("release component inventory is empty")

    embedded: set[str] = set()
    for pattern in EMBEDDED_COMPONENT_GLOBS:
        embedded.update(
            path.relative_to(ROOT).as_posix()
            for path in ROOT.glob(pattern)
            if path.is_file()
        )

    repository_files: set[str] = set()
    external_distributions = 0
    purls: set[str] = set()
    result: list[dict[str, object]] = []
    for index, raw in enumerate(raw_components):
        label = f"release component {index}"
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "version",
            "purl",
            "scope",
            "license",
            "hash",
        }:
            raise CandidateError(f"{label} has unexpected fields")
        for field in ("name", "version", "purl", "scope", "license"):
            if not isinstance(raw[field], str) or not raw[field]:
                raise CandidateError(f"{label} has invalid {field}")
        if raw["scope"] not in {"required", "optional", "excluded"}:
            raise CandidateError(f"{label} has invalid scope")
        purl = str(raw["purl"])
        if purl in purls:
            raise CandidateError(f"duplicate release component purl: {purl}")
        purls.add(purl)
        hash_source = raw["hash"]
        if not isinstance(hash_source, dict) or "kind" not in hash_source:
            raise CandidateError(f"{label} has invalid hash source")
        kind = hash_source["kind"]
        if kind == "repository-file":
            if set(hash_source) != {"kind", "path"}:
                raise CandidateError(f"{label} repository hash source is invalid")
            relative = hash_source["path"]
            if not isinstance(relative, str) or not relative:
                raise CandidateError(f"{label} repository path is invalid")
            path = (ROOT / relative).resolve()
            if ROOT not in path.parents or not path.is_file():
                raise CandidateError(f"{label} repository path is unsafe or missing")
            normalized = path.relative_to(ROOT).as_posix()
            if normalized != relative:
                raise CandidateError(f"{label} repository path is not normalized")
            repository_files.add(relative)
            digest = sha256(path)
            component_type = "file"
        elif kind == "external-distribution":
            if set(hash_source) != {"kind", "sha256", "url"}:
                raise CandidateError(f"{label} external hash source is invalid")
            digest = hash_source["sha256"]
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                raise CandidateError(f"{label} external SHA-256 is invalid")
            distribution_url = hash_source["url"]
            if not isinstance(distribution_url, str) or not distribution_url.startswith(
                "https://"
            ):
                raise CandidateError(f"{label} external distribution URL is invalid")
            component_type = "application"
            external_distributions += 1
        elif kind == "registry-version-pin":
            # WHY a kind with no digest rather than a placeholder hash: npm and
            # PyPI expose no per-install integrity value a global install can be
            # pinned to the way an archive checksum pins a download. Recording a
            # zero or a re-hash of whatever arrived would be a hash in name only,
            # and an SBOM that cannot be told apart from one carrying a real
            # digest is worse than one that says plainly which is which.
            if set(hash_source) != {"kind", "registry"}:
                raise CandidateError(f"{label} registry pin source is invalid")
            if hash_source["registry"] not in {"npm", "pypi", "actions-toolcache"}:
                raise CandidateError(f"{label} has unknown registry {hash_source['registry']!r}")
            digest = None
            component_type = "library"
        else:
            raise CandidateError(f"{label} has unknown hash source {kind!r}")
        component = {
                "type": component_type,
                "bom-ref": purl,
                "name": raw["name"],
                "version": raw["version"],
                "scope": raw["scope"],
                "purl": purl,
                "licenses": [{"expression": raw["license"]}],
            }
        if digest is not None:
            component["hashes"] = [{"alg": "SHA-256", "content": digest}]
        if kind == "external-distribution":
            component["externalReferences"] = [
                {
                    "type": "distribution",
                    "url": distribution_url,
                    "hashes": [{"alg": "SHA-256", "content": digest}],
                }
            ]
        result.append(component)
    if repository_files != embedded:
        raise CandidateError(
            "release component inventory does not exactly cover embedded files: "
            f"inventory={sorted(repository_files)}, discovered={sorted(embedded)}"
        )
    if external_distributions == 0:
        raise CandidateError("release component inventory has no external distribution")
    return result


def component_inventory() -> list[dict[str, object]]:
    """The validated inventory, refused unless it covers every locked tool.

    This used to raise unconditionally, citing forkwright/typikon#58: the SBOM
    listed Zola and the fonts while wrangler, lychee, pa11y-ci, playwright,
    Python and Node were absent, and a release must not claim a dependency
    graph it does not have. The block is now conditional on the thing it was
    standing in for -- ci/tool-lock.toml is the list of what must appear, so a
    tool added there and forgotten here fails the candidate build rather than
    shipping an inventory that is quietly short.
    """
    inventory = validated_component_inventory()
    listed = {str(component["name"]) for component in inventory}
    missing = [tool.name for tool in toollock.load(LOCK_PATH) if tool.name not in listed]
    if missing:
        raise CandidateError(
            "release SBOM does not cover every locked tool; ci/tool-lock.toml "
            f"declares {', '.join(sorted(missing))} and release/components.json omits "
            "them. Every shipped CLI, gate, and deploy dependency must appear."
        )
    return inventory


def iter_components(items: object):
    if not isinstance(items, list):
        return
    for component in items:
        if not isinstance(component, dict):
            raise CandidateError("CycloneDX components must be objects")
        yield component
        yield from iter_components(component.get("components", []))


def component_has_license(component: dict[str, object]) -> bool:
    licenses = component.get("licenses")
    if not isinstance(licenses, list) or not licenses:
        return False
    for item in licenses:
        if not isinstance(item, dict):
            return False
        expression = item.get("expression")
        license_value = item.get("license")
        if isinstance(expression, str) and expression:
            continue
        if isinstance(license_value, dict) and any(
            isinstance(license_value.get(key), str) and license_value.get(key)
            for key in ("id", "name")
        ):
            continue
        return False
    return True


def component_has_sha256(component: dict[str, object]) -> bool:
    hashes = component.get("hashes")
    return isinstance(hashes, list) and any(
        isinstance(item, dict)
        and item.get("alg") == "SHA-256"
        and isinstance(item.get("content"), str)
        and SHA256.fullmatch(item["content"]) is not None
        for item in hashes
    )


def normalize_and_validate_sbom(
    document: dict[str, object], identity: dict[str, object], archive: Path
) -> None:
    if document.get("bomFormat") != "CycloneDX":
        raise CandidateError("SBOM is not a CycloneDX document")
    spec = document.get("specVersion")
    try:
        major, minor = (int(part) for part in str(spec).split(".", 1))
    except (TypeError, ValueError) as exc:
        raise CandidateError("CycloneDX specVersion is not numeric") from exc
    if (major, minor) < (1, 5):
        raise CandidateError("CycloneDX specVersion must be 1.5 or newer")

    version = str(identity["version"])
    archive_digest = sha256(archive)
    purl = f"{ROOT_PURL}@{version}"
    expected_serial = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"https://github.com/forkwright/typikon/commit/{identity['candidate_commit']}",
        )
    )
    if document.get("serialNumber") != f"urn:uuid:{expected_serial}":
        raise CandidateError("CycloneDX serialNumber does not bind the candidate commit")
    metadata = document.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise CandidateError("CycloneDX metadata must be an object")
    metadata["component"] = {
        "type": "library",
        "bom-ref": purl,
        "name": "typikon",
        "version": version,
        "scope": "required",
        "purl": purl,
        "licenses": [{"expression": ROOT_LICENSE}],
        "hashes": [{"alg": "SHA-256", "content": archive_digest}],
    }

    inventory = component_inventory()
    inventory_purls = {str(item["purl"]) for item in inventory}
    existing = document.get("components", [])
    if not isinstance(existing, list):
        raise CandidateError("CycloneDX components must be an array")
    if any(
        component.get("purl") in inventory_purls
        for component in iter_components(existing)
    ):
        raise CandidateError("generated SBOM duplicates an authoritative component purl")
    document["components"] = [*existing, *inventory]
    document["dependencies"] = [
        {"ref": purl, "dependsOn": sorted(inventory_purls)},
        *[
            {"ref": item["purl"], "dependsOn": []}
            for item in sorted(inventory, key=lambda value: str(value["purl"]))
        ],
    ]

    for component in iter_components(document.get("components", [])):
        missing = [
            field
            for field in ("name", "version", "purl", "scope")
            if not isinstance(component.get(field), str) or not component.get(field)
        ]
        if missing:
            raise CandidateError(
                f"CycloneDX component lacks required fields {missing}: {component.get('name')!r}"
            )
        if component["scope"] not in {"required", "optional", "excluded"}:
            raise CandidateError(
                f"CycloneDX component has invalid scope: {component.get('name')!r}"
            )
        if not component_has_license(component):
            raise CandidateError(
                f"CycloneDX component lacks a license: {component.get('name')!r}"
            )
        if not component_has_sha256(component):
            raise CandidateError(
                f"CycloneDX component lacks a SHA-256 hash: {component.get('name')!r}"
            )

    expected_dependency_refs = {purl, *inventory_purls}
    dependency_rows = document.get("dependencies")
    if not isinstance(dependency_rows, list) or {
        row.get("ref") for row in dependency_rows if isinstance(row, dict)
    } != expected_dependency_refs:
        raise CandidateError("CycloneDX dependency graph does not cover every component")


def read_bundle(
    path: Path,
    label: str,
    archive_name: str,
    archive_sha256: str,
) -> bytes:
    payload = path.read_bytes()
    lines = [line for line in payload.splitlines() if line.strip()]
    if len(lines) != 1:
        raise CandidateError(f"{label} attestation bundle must contain exactly one JSONL record")
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise CandidateError(f"{label} attestation bundle is invalid JSONL: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateError(f"{label} attestation bundle record must be an object")
    media_type = value.get("mediaType")
    if not isinstance(media_type, str) or not media_type.startswith(
        "application/vnd.dev.sigstore.bundle"
    ):
        raise CandidateError(f"{label} attestation bundle has no Sigstore media type")
    verification = value.get("verificationMaterial")
    envelope = value.get("dsseEnvelope")
    if not isinstance(verification, dict) or not verification:
        raise CandidateError(f"{label} attestation bundle has no verification material")
    if not isinstance(envelope, dict):
        raise CandidateError(f"{label} attestation bundle has no DSSE envelope")
    if envelope.get("payloadType") != "application/vnd.in-toto+json":
        raise CandidateError(f"{label} attestation bundle has the wrong payload type")
    signatures = envelope.get("signatures")
    if not isinstance(signatures, list) or not signatures:
        raise CandidateError(f"{label} attestation bundle has no signature")
    try:
        statement = json.loads(
            base64.b64decode(envelope.get("payload", ""), validate=True)
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise CandidateError(f"{label} attestation payload is invalid") from exc
    expected_predicate = {
        "provenance": "https://slsa.dev/provenance/v1",
        "sbom": "https://cyclonedx.org/bom",
    }[label]
    if (
        not isinstance(statement, dict)
        or statement.get("_type") != "https://in-toto.io/Statement/v1"
        or statement.get("predicateType") != expected_predicate
    ):
        raise CandidateError(f"{label} attestation statement type is wrong")
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise CandidateError(f"{label} attestation must name exactly one subject")
    subject = subjects[0]
    if (
        not isinstance(subject, dict)
        or Path(str(subject.get("name", ""))).name != archive_name
        or subject.get("digest", {}).get("sha256") != archive_sha256
    ):
        raise CandidateError(f"{label} attestation subject differs from the archive")
    return payload


def attach_attestations(output_dir: Path, provenance: Path, sbom_bundle: Path) -> Path:
    manifest_path = output_dir / "candidate.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateError(f"candidate manifest cannot be read: {exc}") from exc
    if set(manifest) != {
        "schema_version",
        "release",
        "workflow",
        "archive",
        "checksum",
        "sbom",
        "notes",
    }:
        raise CandidateError("candidate manifest is not awaiting attestation finalization")
    archive_name = manifest.get("archive", {}).get("name")
    if not isinstance(archive_name, str):
        raise CandidateError("candidate manifest has no archive name")
    archive_sha256 = manifest.get("archive", {}).get("sha256")
    if not isinstance(archive_sha256, str) or SHA256.fullmatch(archive_sha256) is None:
        raise CandidateError("candidate manifest has no archive SHA-256")
    sources = {"provenance": provenance, "sbom": sbom_bundle}
    attestations: dict[str, dict[str, object]] = {}
    for kind, source in sources.items():
        payload = read_bundle(source, kind, archive_name, archive_sha256)
        destination = output_dir / f"{archive_name}.{kind}.intoto.jsonl"
        destination.unlink(missing_ok=True)
        with source.open("rb") as input_handle, destination.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle)
        attestations[kind] = {
            "name": destination.name,
            "sha256": sha256(destination),
            "size": destination.stat().st_size,
        }
        if destination.read_bytes() != payload:
            raise CandidateError(f"{kind} attestation bundle copy changed bytes")
    manifest["attestations"] = attestations
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def write_github_output(identity: dict[str, object] | None, output: Path) -> None:
    lines = [f"candidate={'true' if identity else 'false'}"]
    if identity:
        for key in (
            "version",
            "tag",
            "release_pr",
            "candidate_commit",
            "candidate_tree",
        ):
            lines.append(f"{key}={identity[key]}")
    with output.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def seed_sbom(output_dir: Path) -> Path:
    identity = release_identity()
    if identity is None:
        raise CandidateError("HEAD is not a release-candidate commit")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"typikon-{identity['tag']}.tar.gz"
    destination = output_dir / f"{archive_name}.cdx.json"
    destination.unlink(missing_ok=True)
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://github.com/forkwright/typikon/commit/{identity['candidate_commit']}",
    )
    document = {
        "bomFormat": "CycloneDX",
        "serialNumber": f"urn:uuid:{serial}",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": git("show", "-s", "--format=%cI", "HEAD"),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "typikon release candidate builder",
                        "version": str(identity["candidate_commit"]),
                    }
                ]
            },
        },
        "components": [],
        "dependencies": [],
    }
    destination.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def freeze(output_dir: Path) -> Path:
    identity = release_identity()
    if identity is None:
        raise CandidateError("HEAD is not a release-candidate commit")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"typikon-{identity['tag']}.tar.gz"
    archive = output_dir / archive_name
    checksum = output_dir / f"{archive_name}.sha256"
    sbom = output_dir / f"{archive_name}.cdx.json"
    # The freezer owns the archive bytes. Never bless a stale caller-supplied
    # file merely because its name is plausible.
    archive.unlink(missing_ok=True)
    result = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar.gz", "--output", str(archive), "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise CandidateError(result.stderr.strip() or "git archive failed")
    if not sbom.is_file():
        raise CandidateError(f"pinned SBOM step produced no {sbom}")
    try:
        sbom_doc = json.loads(sbom.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CandidateError(f"{sbom} is not JSON: {exc}") from exc
    if not isinstance(sbom_doc, dict):
        raise CandidateError(f"{sbom} is not a JSON object")
    normalize_and_validate_sbom(sbom_doc, identity, archive)
    sbom.write_text(json.dumps(sbom_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    checksum.write_text(
        f"{sha256(archive)}  {archive.name}\n",
        encoding="utf-8",
    )
    notes = release_notes(str(identity["version"]))
    notes_bytes = notes.encode("utf-8")
    manifest = {
        "schema_version": 1,
        "release": identity,
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "run_id": int(os.environ.get("GITHUB_RUN_ID", "0")),
            "run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "0")),
        },
        "archive": {
            "name": archive.name,
            "sha256": sha256(archive),
            "size": archive.stat().st_size,
        },
        "checksum": {
            "name": checksum.name,
            "sha256": sha256(checksum),
            "size": checksum.stat().st_size,
        },
        "sbom": {
            "name": sbom.name,
            "sha256": sha256(sbom),
            "size": sbom.stat().st_size,
        },
        "notes": {
            "body": notes,
            "sha256": sha256_bytes(notes_bytes),
            "size": len(notes_bytes),
        },
    }
    destination = output_dir / "candidate.json"
    destination.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    detect = sub.add_parser("detect")
    detect.add_argument("--github-output", type=Path)
    seed = sub.add_parser("seed-sbom")
    seed.add_argument("--output-dir", required=True, type=Path)
    finish = sub.add_parser("freeze")
    finish.add_argument("--output-dir", required=True, type=Path)
    attest = sub.add_parser("attach-attestations")
    attest.add_argument("--output-dir", required=True, type=Path)
    attest.add_argument("--provenance-bundle", required=True, type=Path)
    attest.add_argument("--sbom-bundle", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "detect":
            identity = release_identity()
            if args.github_output:
                write_github_output(identity, args.github_output)
            print(json.dumps({"candidate": identity is not None, "release": identity}))
        elif args.command == "seed-sbom":
            print(seed_sbom(args.output_dir))
        elif args.command == "freeze":
            print(freeze(args.output_dir))
        else:
            print(
                attach_attestations(
                    args.output_dir, args.provenance_bundle, args.sbom_bundle
                )
            )
    except (CandidateError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"build-release-candidate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
