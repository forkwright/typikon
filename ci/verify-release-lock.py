#!/usr/bin/env python3
"""Verify the v0.6 release candidate, two consumer receipts, and live GitHub state."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_archive import ArchiveError, verify_archive
from release_secret import SecretToken, require_secret

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_COHORT = {
    "tools": "ardent-tools/ardent-tools-site",
    "leather": "forkwright/ardent-site",
}
TYPIKON_REPOSITORY = "forkwright/typikon"
TOKEN_BY_REPOSITORY = {
    TYPIKON_REPOSITORY: "GITHUB_TOKEN",
    EXPECTED_COHORT["tools"]: "TOOLS_RECEIPT_TOKEN",
    EXPECTED_COHORT["leather"]: "LEATHER_RECEIPT_TOKEN",
}
SHA = re.compile(r"^[0-9a-f]{40}$")
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class LockError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Expose GitHub's signed artifact URL without forwarding credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def download_signed_redirect(
    api_url: str, token: SecretToken, *, require_https: bool = True
) -> bytes:
    token = require_secret(token)
    authenticated = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token.expose()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "typikon-release-lock-verifier",
        },
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(authenticated, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise LockError(f"artifact API returned HTTP {exc.code}") from exc
        location = exc.headers.get("Location", "")
    else:
        raise LockError("artifact API did not return a signed redirect")
    parsed = urllib.parse.urlsplit(location)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.netloc or parsed.username:
        raise LockError("artifact API returned an unsafe redirect URL")
    # Fresh request by design: no GitHub Authorization or API-version header
    # may cross the origin boundary to the signed object-store URL.
    unsigned = urllib.request.Request(
        location, headers={"User-Agent": "typikon-release-lock-verifier"}
    )
    try:
        with urllib.request.urlopen(unsigned, timeout=60) as response:
            data = response.read(64 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise LockError(f"signed artifact download returned HTTP {exc.code}") from exc
    if len(data) > 64 * 1024 * 1024:
        raise LockError("artifact exceeds 64 MiB")
    return data


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise LockError(f"{label} fields must be {sorted(expected)}, found {actual}")
    return value


def validate_lock_shape(lock: Any) -> dict[str, Any]:
    document = exact_keys(
        lock,
        {"schema_version", "release", "candidate_artifact", "consumers"},
        "compatibility lock",
    )
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise LockError("compatibility lock schema_version must be 1")
    release = exact_keys(
        document["release"],
        {"version", "tag", "release_pr", "candidate_commit", "candidate_tree"},
        "release",
    )
    if not isinstance(release["version"], str) or SEMVER.fullmatch(
        release["version"]
    ) is None:
        raise LockError("release version is not SemVer")
    if release["tag"] != f"v{release['version']}":
        raise LockError("release tag does not match version")
    if type(release["release_pr"]) is not int or release["release_pr"] < 1:
        raise LockError("release PR number is invalid")
    for field in ("candidate_commit", "candidate_tree"):
        if not isinstance(release[field], str) or SHA.fullmatch(release[field]) is None:
            raise LockError(f"release {field} is not a full object id")

    artifact_fields = {
        "workflow_run_id",
        "run_attempt",
        "artifact_id",
        "artifact_name",
        "artifact_digest",
        "archive_name",
        "archive_sha256",
        "archive_size",
        "checksum_name",
        "checksum_sha256",
        "checksum_size",
        "sbom_name",
        "sbom_sha256",
        "sbom_size",
        "provenance_bundle_name",
        "provenance_bundle_sha256",
        "provenance_bundle_size",
        "sbom_bundle_name",
        "sbom_bundle_sha256",
        "sbom_bundle_size",
    }
    artifact = exact_keys(document["candidate_artifact"], artifact_fields, "candidate artifact")
    for field in (
        "workflow_run_id",
        "run_attempt",
        "artifact_id",
        "archive_size",
        "checksum_size",
        "sbom_size",
        "provenance_bundle_size",
        "sbom_bundle_size",
    ):
        if type(artifact[field]) is not int or artifact[field] < 1:
            raise LockError(f"candidate artifact {field} is invalid")
    if not isinstance(artifact["artifact_digest"], str) or ARTIFACT_DIGEST.fullmatch(
        artifact["artifact_digest"]
    ) is None:
        raise LockError("candidate artifact digest is invalid")
    for field in (
        "archive_sha256",
        "checksum_sha256",
        "sbom_sha256",
        "provenance_bundle_sha256",
        "sbom_bundle_sha256",
    ):
        if not isinstance(artifact[field], str) or HEX_DIGEST.fullmatch(
            artifact[field]
        ) is None:
            raise LockError(f"candidate artifact {field} is invalid")
    tag = release["tag"]
    archive_name = f"typikon-{tag}.tar.gz"
    exact_names = {
        "artifact_name": f"typikon-{tag}-candidate",
        "archive_name": archive_name,
        "checksum_name": f"{archive_name}.sha256",
        "sbom_name": f"{archive_name}.cdx.json",
        "provenance_bundle_name": f"{archive_name}.provenance.intoto.jsonl",
        "sbom_bundle_name": f"{archive_name}.sbom.intoto.jsonl",
    }
    for field, expected in exact_names.items():
        if artifact[field] != expected:
            raise LockError(f"candidate artifact {field} differs: {artifact[field]!r}")

    consumers = document["consumers"]
    if not isinstance(consumers, list) or len(consumers) != 2:
        raise LockError("compatibility cohort must contain exactly two consumers")
    expected_consumers = [
        (
            "tools",
            "ardent-tools/ardent-tools-site",
            "release/compatibility/receipts/tools.json",
        ),
        (
            "leather",
            "forkwright/ardent-site",
            "release/compatibility/receipts/leather.json",
        ),
    ]
    consumer_fields = {
        "id",
        "repository",
        "pull_request",
        "base_commit",
        "head_commit",
        "head_tree",
        "merge_commit",
        "merge_tree",
        "gitlink_path",
        "previous_gitlink_commit",
        "previous_gitlink_tree",
        "gitlink_commit",
        "gitlink_tree",
        "workflow_path",
        "workflow_commit",
        "workflow_blob",
        "workflow_run_id",
        "run_attempt",
        "required_job",
        "receipt_path",
        "receipt_sha256",
        "artifact_id",
        "artifact_name",
        "artifact_digest",
    }
    for consumer, expected in zip(consumers, expected_consumers, strict=True):
        item = exact_keys(consumer, consumer_fields, f"{expected[0]} consumer")
        if (item["id"], item["repository"], item["receipt_path"]) != expected:
            raise LockError(f"consumer cohort tuple differs from {expected!r}")
        if item["gitlink_path"] != "themes/typikon" or item["required_job"] != "gate-and-deploy":
            raise LockError(f"{item['id']} consumer contract constants drifted")
        if item["workflow_commit"] != item["merge_commit"]:
            raise LockError(
                f"{item['id']} workflow commit is not its synthetic merge commit"
            )
        if type(item["pull_request"]) is not int or item["pull_request"] < 1:
            raise LockError(f"{item['id']} pull request is invalid")
        for field in (
            "base_commit",
            "head_commit",
            "head_tree",
            "merge_commit",
            "merge_tree",
            "previous_gitlink_commit",
            "previous_gitlink_tree",
            "gitlink_commit",
            "gitlink_tree",
            "workflow_commit",
            "workflow_blob",
        ):
            if not isinstance(item[field], str) or SHA.fullmatch(item[field]) is None:
                raise LockError(f"{item['id']} {field} is not a full object id")
        if not isinstance(item["workflow_path"], str) or re.fullmatch(
            r"\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml", item["workflow_path"]
        ) is None:
            raise LockError(f"{item['id']} workflow path is invalid")
        for field in ("workflow_run_id", "run_attempt", "artifact_id"):
            if type(item[field]) is not int or item[field] < 1:
                raise LockError(f"{item['id']} {field} is invalid")
        if not isinstance(item["receipt_sha256"], str) or HEX_DIGEST.fullmatch(
            item["receipt_sha256"]
        ) is None:
            raise LockError(f"{item['id']} receipt SHA-256 is invalid")
        if not isinstance(item["artifact_digest"], str) or ARTIFACT_DIGEST.fullmatch(
            item["artifact_digest"]
        ) is None:
            raise LockError(f"{item['id']} artifact digest is invalid")
        expected_artifact = (
            f"typikon-consumer-receipt-{item['workflow_run_id']}-{item['run_attempt']}"
        )
        if item["artifact_name"] != expected_artifact:
            raise LockError(f"{item['id']} artifact name differs from its run")
    return document


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LockError(f"cannot read JSON {path}: {exc}") from exc


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise LockError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def changelog_notes(revision: str, version: str) -> str:
    text = git("show", f"{revision}:CHANGELOG.md")
    header = re.compile(rf"^## \[{re.escape(version)}\].*$", re.MULTILINE)
    matches = list(header.finditer(text))
    if len(matches) != 1:
        raise LockError(
            f"candidate CHANGELOG must contain exactly one release heading for {version}"
        )
    start = matches[0].end()
    following = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + following.start() if following else len(text)
    notes = text[start:end].strip()
    if not notes:
        raise LockError("candidate CHANGELOG release notes are empty")
    return notes


class GitHub:
    def __init__(self, snapshot: dict[str, Any] | None = None):
        self.snapshot = snapshot

    def get(self, repo: str, endpoint: str, *, missing_ok: bool = False) -> Any:
        key = f"{repo}|{endpoint}"
        if self.snapshot is not None:
            if key not in self.snapshot:
                if missing_ok:
                    return None
                raise LockError(f"snapshot has no response for {key}")
            return self.snapshot[key]
        token_name = TOKEN_BY_REPOSITORY.get(repo)
        if token_name is None:
            raise LockError(f"no credential route is defined for {repo}")
        try:
            token = SecretToken.from_env(token_name)
        except ValueError:
            raise LockError(f"{token_name} is required to verify {repo}")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/{endpoint}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token.expose()}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "typikon-release-lock-verifier",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            detail = exc.read().decode(errors="replace")
            raise LockError(f"GitHub {repo}/{endpoint} returned {exc.code}: {detail}") from exc

    def artifact_zip(self, repo: str, artifact_id: int) -> bytes:
        key = f"{repo}|artifact_zip/{artifact_id}"
        if self.snapshot is not None:
            encoded = self.snapshot.get(key)
            if not isinstance(encoded, str):
                raise LockError(f"snapshot has no artifact bytes for {key}")
            return base64.b64decode(encoded, validate=True)
        token_name = TOKEN_BY_REPOSITORY.get(repo)
        if token_name is None:
            raise LockError(f"no credential route is defined for {repo}")
        try:
            token = SecretToken.from_env(token_name)
        except ValueError:
            raise LockError(f"{token_name} is required to download {repo} evidence")
        return download_signed_redirect(
            f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip",
            token,
        )


def validate_receipt(receipt: Any, consumer: dict[str, Any], candidate: dict[str, Any]) -> None:
    exact_keys(receipt, {"schema_version", "consumer", "typikon", "workflow"}, "receipt")
    if receipt["schema_version"] != 1:
        raise LockError("receipt.schema_version must be 1")
    subject = exact_keys(
        receipt["consumer"],
        {
            "repository",
            "pull_request",
            "base_commit",
            "head_commit",
            "checkout_commit",
            "checkout_tree",
            "checkout_parents",
        },
        "receipt.consumer",
    )
    theme = exact_keys(receipt["typikon"], {"path", "mode", "commit", "tree"}, "receipt.typikon")
    workflow = exact_keys(
        receipt["workflow"],
        {"path", "commit", "blob", "run_id", "run_attempt", "event"},
        "receipt.workflow",
    )
    pairs = {
        "repository": (subject["repository"], consumer["repository"]),
        "pull request": (subject["pull_request"], consumer["pull_request"]),
        "base commit": (subject["base_commit"], consumer["base_commit"]),
        "head commit": (subject["head_commit"], consumer["head_commit"]),
        "checkout commit": (subject["checkout_commit"], consumer["merge_commit"]),
        "checkout tree": (subject["checkout_tree"], consumer["merge_tree"]),
        "checkout parents": (
            subject["checkout_parents"],
            [consumer["base_commit"], consumer["head_commit"]],
        ),
        "gitlink path": (theme["path"], consumer["gitlink_path"]),
        "gitlink mode": (theme["mode"], "160000"),
        "gitlink commit": (theme["commit"], consumer["gitlink_commit"]),
        "gitlink tree": (theme["tree"], consumer["gitlink_tree"]),
        "workflow path": (workflow["path"], consumer["workflow_path"]),
        "workflow commit": (workflow["commit"], consumer["workflow_commit"]),
        "workflow blob": (workflow["blob"], consumer["workflow_blob"]),
        "run id": (workflow["run_id"], consumer["workflow_run_id"]),
        "run attempt": (workflow["run_attempt"], consumer["run_attempt"]),
        "event": (workflow["event"], "pull_request"),
    }
    for label, (actual, expected) in pairs.items():
        if actual != expected:
            raise LockError(f"receipt {label} mismatch: {actual!r} != {expected!r}")
    if consumer["gitlink_commit"] != candidate["candidate_commit"]:
        raise LockError("locked consumer gitlink commit differs from the candidate")
    if consumer["gitlink_tree"] != candidate["candidate_tree"]:
        raise LockError("locked consumer gitlink tree differs from the candidate")


def validate_bundle(lock: dict[str, Any], bundles: dict[str, dict[str, bytes]]) -> None:
    release = lock["release"]
    artifact = lock["candidate_artifact"]
    if release["tag"] != f"v{release['version']}":
        raise LockError("release tag does not match version")
    candidate_files = bundles["candidate"]
    candidate = json.loads(candidate_files["candidate.json"].decode())
    exact_keys(
        candidate,
        {
            "schema_version",
            "release",
            "workflow",
            "archive",
            "checksum",
            "sbom",
            "notes",
            "attestations",
        },
        "candidate",
    )
    if candidate["schema_version"] != 1:
        raise LockError("candidate.schema_version must be 1")
    for key in ("version", "tag", "release_pr", "candidate_commit", "candidate_tree"):
        if candidate["release"].get(key) != release[key]:
            raise LockError(f"candidate release {key} differs from the lock")
    if candidate["workflow"] != {
        "repository": "forkwright/typikon",
        "run_id": artifact["workflow_run_id"],
        "run_attempt": artifact["run_attempt"],
    }:
        raise LockError("candidate workflow identity differs from the lock")
    for kind, lock_prefix in (
        ("archive", "archive"),
        ("checksum", "checksum"),
        ("sbom", "sbom"),
    ):
        item = candidate[kind]
        payload = candidate_files[item["name"]]
        expected = {
            "name": artifact[f"{lock_prefix}_name"],
            "sha256": artifact[f"{lock_prefix}_sha256"],
            "size": artifact[f"{lock_prefix}_size"],
        }
        if item != expected:
            raise LockError(f"candidate {kind} manifest differs from the lock")
        if hashlib.sha256(payload).hexdigest() != item["sha256"] or len(payload) != item["size"]:
            raise LockError(f"candidate {kind} bytes differ from their manifest")
        if kind == "archive":
            try:
                verify_archive(payload, ROOT, release["candidate_commit"])
            except ArchiveError as exc:
                raise LockError(str(exc)) from exc
    expected_checksum = (
        f"{candidate['archive']['sha256']}  {candidate['archive']['name']}\n".encode()
    )
    if candidate_files[candidate["checksum"]["name"]] != expected_checksum:
        raise LockError("candidate checksum is not the canonical sha256sum record")
    notes = exact_keys(candidate["notes"], {"body", "sha256", "size"}, "candidate.notes")
    notes_body = notes.get("body")
    if not isinstance(notes_body, str):
        raise LockError("candidate release notes body is not text")
    notes_bytes = notes_body.encode("utf-8")
    if (
        notes.get("sha256") != hashlib.sha256(notes_bytes).hexdigest()
        or notes.get("size") != len(notes_bytes)
        or notes_body != changelog_notes(release["candidate_commit"], release["version"])
    ):
        raise LockError("candidate release notes differ from the exact CHANGELOG section")
    attestations = exact_keys(
        candidate["attestations"], {"provenance", "sbom"}, "candidate.attestations"
    )
    for kind in ("provenance", "sbom"):
        item = exact_keys(
            attestations[kind], {"name", "sha256", "size"}, f"candidate.attestations.{kind}"
        )
        expected = {
            "name": artifact[f"{kind}_bundle_name"],
            "sha256": artifact[f"{kind}_bundle_sha256"],
            "size": artifact[f"{kind}_bundle_size"],
        }
        if item != expected:
            raise LockError(f"candidate {kind} attestation manifest differs from the lock")
        payload = candidate_files[item["name"]]
        if hashlib.sha256(payload).hexdigest() != item["sha256"] or len(payload) != item["size"]:
            raise LockError(f"candidate {kind} attestation bytes differ from their manifest")

    for consumer in lock["consumers"]:
        tracked = (ROOT / consumer["receipt_path"]).resolve()
        if ROOT not in tracked.parents:
            raise LockError(f"receipt path escapes the repository: {tracked}")
        if sha256(tracked) != consumer["receipt_sha256"]:
            raise LockError(f"tracked {consumer['id']} receipt digest differs from the lock")
        downloaded = bundles[consumer["id"]]["typikon-consumer-receipt.json"]
        if downloaded != tracked.read_bytes():
            raise LockError(f"downloaded {consumer['id']} receipt differs from tracked bytes")
        validate_receipt(read_json(tracked), consumer, release)


def require_tree_entry(
    api: GitHub,
    repo: str,
    tree: str,
    path: str,
    *,
    mode: str,
    sha: str,
    label: str,
) -> None:
    tree_doc = api.get(repo, f"git/trees/{tree}?recursive=1")
    entries = [entry for entry in tree_doc.get("tree", []) if entry.get("path") == path]
    if len(entries) != 1:
        raise LockError(f"{repo} {label} has {len(entries)} entries for {path}")
    entry = entries[0]
    if entry.get("mode") != mode or entry.get("sha") != sha:
        raise LockError(f"{repo} {label} {path} differs from the lock")


def verify_artifact(api: GitHub, repo: str, fields: dict[str, Any], *, candidate: bool = False) -> dict[str, bytes]:
    artifact = api.get(repo, f"actions/artifacts/{fields['artifact_id']}")
    expected_run = fields["workflow_run_id"]
    if artifact.get("expired"):
        raise LockError(f"{repo} artifact {fields['artifact_id']} is expired")
    if artifact.get("name") != fields["artifact_name"]:
        raise LockError(f"{repo} artifact name drifted")
    if artifact.get("digest") != fields["artifact_digest"]:
        raise LockError(f"{repo} artifact digest drifted")
    if artifact.get("workflow_run", {}).get("id") != expected_run:
        raise LockError(f"{repo} artifact belongs to another workflow run")
    raw = api.artifact_zip(repo, fields["artifact_id"])
    digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    if digest != fields["artifact_digest"]:
        raise LockError(f"{repo} downloaded artifact digest differs from the lock")
    expected_names = (
        {
            "candidate.json",
            fields["archive_name"],
            fields["checksum_name"],
            fields["sbom_name"],
            fields["provenance_bundle_name"],
            fields["sbom_bundle_name"],
        }
        if candidate
        else {"typikon-consumer-receipt.json"}
    )
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != expected_names:
                raise LockError(
                    f"{repo} artifact members must be {sorted(expected_names)}, found {sorted(names)}"
                )
            files: dict[str, bytes] = {}
            for info in archive.infolist():
                if info.is_dir() or info.file_size > 48 * 1024 * 1024:
                    raise LockError(f"{repo} artifact has an invalid member {info.filename!r}")
                files[info.filename] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise LockError(f"{repo} artifact is not a valid ZIP") from exc
    return files


def verify_run(
    api: GitHub,
    repo: str,
    fields: dict[str, Any],
    expected_head: str,
    path: str,
    *,
    pull_request: int | None = None,
) -> None:
    run_id = fields["workflow_run_id"]
    attempt = fields["run_attempt"]
    run = api.get(repo, f"actions/runs/{run_id}")
    expected = {
        "status": "completed",
        "conclusion": "success",
        "event": fields.get("event", "pull_request"),
        "head_sha": expected_head,
        "run_attempt": attempt,
        "path": path,
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise LockError(f"{repo} run {run_id} {key} drifted: {run.get(key)!r} != {value!r}")
    associations = run.get("pull_requests", [])
    if pull_request is None:
        if associations:
            raise LockError(f"{repo} push run is associated with a pull request")
    else:
        if len(associations) != 1:
            raise LockError(f"{repo} run is not bound to exactly one pull request")
        association = associations[0]
        if (
            association.get("number") != pull_request
            or association.get("head", {}).get("sha") != fields["head_commit"]
            or association.get("base", {}).get("sha") != fields["base_commit"]
        ):
            raise LockError(f"{repo} run pull-request association drifted")
    first_endpoint = f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"
    first = api.get(repo, first_endpoint)
    jobs = first.get("jobs", [])
    if not isinstance(jobs, list):
        raise LockError(f"{repo} jobs response is not a list")
    all_jobs = list(jobs)
    page = 2
    while len(jobs) == 100:
        if page > 100:
            raise LockError(f"{repo} run has more than 10,000 jobs")
        page_doc = api.get(repo, f"{first_endpoint}&page={page}")
        jobs = page_doc.get("jobs", [])
        if not isinstance(jobs, list):
            raise LockError(f"{repo} jobs page {page} is not a list")
        all_jobs.extend(jobs)
        page += 1
    matches = [
        job
        for job in all_jobs
        if job.get("name") == fields.get("required_job", "gate")
    ]
    if len(matches) != 1 or matches[0].get("conclusion") != "success":
        raise LockError(f"{repo} required job is not exactly one success")


def verify_evidence_delta(lock: dict[str, Any], lock_path: Path) -> None:
    candidate = lock["release"]["candidate_commit"]
    try:
        lock_relative = lock_path.resolve().relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise LockError("compatibility lock is outside the repository") from exc
    allowed = {lock_relative, *(consumer["receipt_path"] for consumer in lock["consumers"])}
    changed = set(git("diff", "--name-only", candidate, "HEAD").splitlines())
    if changed != allowed:
        raise LockError(
            "post-candidate evidence delta must contain exactly "
            f"{sorted(allowed)}, found {sorted(changed)}"
        )
    for path in sorted(allowed):
        git("ls-files", "--error-unmatch", "--", path)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        github_sha = os.environ.get("GITHUB_SHA", "")
        if github_sha != git("rev-parse", "HEAD"):
            raise LockError("checked-out evidence commit differs from GITHUB_SHA")


def verify_live(
    lock: dict[str, Any], api: GitHub, lock_path: Path
) -> dict[str, dict[str, bytes]]:
    release = lock["release"]
    candidate = release["candidate_commit"]
    tree = release["candidate_tree"]
    manifest = json.loads(git("show", f"{candidate}:.release-please-manifest.json"))
    if manifest != {".": release["version"]}:
        raise LockError("candidate manifest version differs from the lock")
    if git("rev-parse", f"{candidate}^{{tree}}") != tree:
        raise LockError("candidate tree differs from local Git object")
    result = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", candidate, "HEAD"]
    )
    if result.returncode:
        raise LockError("candidate is not an ancestor of the evidence commit")
    verify_evidence_delta(lock, lock_path)

    pr = api.get(TYPIKON_REPOSITORY, f"pulls/{release['release_pr']}")
    if not pr.get("merged") or pr.get("merge_commit_sha") != candidate:
        raise LockError("release PR is not merged at the candidate commit")
    parent_ids = git("rev-list", "--parents", "-n", "1", candidate).split()[1:]
    if len(parent_ids) != 1:
        raise LockError("release candidate is not a one-parent squash commit")
    parent = parent_ids[0]
    expected_title = f"chore(main): release {release['version']}"
    expected_pr_identity = {
        "title": expected_title,
        "author_login": "github-actions[bot]",
        "author_type": "Bot",
        "base_ref": "main",
        "base_repo": TYPIKON_REPOSITORY,
        "base_sha": parent,
        "head_ref": "release-please--branches--main",
        "head_repo": TYPIKON_REPOSITORY,
    }
    actual_pr_identity = {
        "title": pr.get("title"),
        "author_login": pr.get("user", {}).get("login"),
        "author_type": pr.get("user", {}).get("type"),
        "base_ref": pr.get("base", {}).get("ref"),
        "base_repo": pr.get("base", {}).get("repo", {}).get("full_name"),
        "base_sha": pr.get("base", {}).get("sha"),
        "head_ref": pr.get("head", {}).get("ref"),
        "head_repo": pr.get("head", {}).get("repo", {}).get("full_name"),
    }
    if actual_pr_identity != expected_pr_identity:
        raise LockError(
            "release PR is not the exact Release Please main-branch proposal: "
            f"{actual_pr_identity!r} != {expected_pr_identity!r}"
        )
    labels = {
        item.get("name") for item in pr.get("labels", []) if isinstance(item, dict)
    }
    if not labels.intersection({"autorelease: pending", "autorelease: tagged"}):
        raise LockError("release PR has no Release Please lifecycle label")
    if "autorelease: tagged" in labels:
        published = api.get(
            TYPIKON_REPOSITORY,
            f"releases/tags/{release['tag']}",
            missing_ok=True,
        )
        tag_ref = api.get(
            TYPIKON_REPOSITORY,
            f"git/ref/tags/{release['tag']}",
            missing_ok=True,
        )
        if (
            published is None
            or published.get("draft") is not False
            or published.get("tag_name") != release["tag"]
            or tag_ref is None
        ):
            raise LockError(
                "autorelease: tagged is present without an exact published release"
            )
    release_head = pr.get("head", {}).get("sha")
    if not isinstance(release_head, str):
        raise LockError("release PR has no head commit")
    release_head_commit = api.get(
        TYPIKON_REPOSITORY, f"git/commits/{release_head}"
    )
    if release_head_commit.get("tree", {}).get("sha") != tree:
        raise LockError("Release Please head tree differs from the candidate tree")
    commit = api.get(TYPIKON_REPOSITORY, f"git/commits/{candidate}")
    if commit.get("tree", {}).get("sha") != tree:
        raise LockError("GitHub candidate tree differs from the lock")
    remote_parents = [item.get("sha") for item in commit.get("parents", [])]
    if remote_parents != [parent]:
        raise LockError("GitHub candidate parent differs from the release PR base")
    candidate_fields = dict(lock["candidate_artifact"])
    candidate_fields["event"] = "push"
    candidate_fields["required_job"] = "freeze-candidate"
    verify_run(
        api,
        TYPIKON_REPOSITORY,
        candidate_fields,
        candidate,
        ".github/workflows/release-candidate.yml",
    )
    bundles = {
        "candidate": verify_artifact(
            api, TYPIKON_REPOSITORY, candidate_fields, candidate=True
        )
    }

    for consumer in lock["consumers"]:
        repo = consumer["repository"]
        if consumer["previous_gitlink_commit"] == consumer["gitlink_commit"]:
            raise LockError(f"{repo} rollback and promotion gitlinks are identical")
        pr = api.get(repo, f"pulls/{consumer['pull_request']}")
        if pr.get("state") != "open":
            raise LockError(f"{repo} receipt PR is not open")
        if (
            pr.get("base", {}).get("ref") != "main"
            or pr.get("base", {}).get("repo", {}).get("full_name") != repo
            or pr.get("head", {}).get("repo", {}).get("full_name") != repo
        ):
            raise LockError(f"{repo} receipt PR does not target owned main")
        current = {
            "base_commit": pr.get("base", {}).get("sha"),
            "head_commit": pr.get("head", {}).get("sha"),
            "merge_commit": pr.get("merge_commit_sha"),
        }
        for key, actual in current.items():
            if actual != consumer[key]:
                raise LockError(f"{repo} PR {key} drifted")
        head = api.get(repo, f"git/commits/{consumer['head_commit']}")
        merge = api.get(repo, f"git/commits/{consumer['merge_commit']}")
        if head.get("tree", {}).get("sha") != consumer["head_tree"]:
            raise LockError(f"{repo} head tree drifted")
        if merge.get("tree", {}).get("sha") != consumer["merge_tree"]:
            raise LockError(f"{repo} merge tree drifted")
        parents = [parent.get("sha") for parent in merge.get("parents", [])]
        if parents != [consumer["base_commit"], consumer["head_commit"]]:
            raise LockError(f"{repo} merge parents drifted")
        base = api.get(repo, f"git/commits/{consumer['base_commit']}")
        base_tree = base.get("tree", {}).get("sha")
        if not isinstance(base_tree, str):
            raise LockError(f"{repo} base commit has no tree")
        require_tree_entry(
            api,
            repo,
            base_tree,
            consumer["gitlink_path"],
            mode="160000",
            sha=consumer["previous_gitlink_commit"],
            label="rollback tree",
        )
        previous = api.get(
            TYPIKON_REPOSITORY,
            f"git/commits/{consumer['previous_gitlink_commit']}",
        )
        if previous.get("tree", {}).get("sha") != consumer["previous_gitlink_tree"]:
            raise LockError(f"{repo} rollback Typikon tree drifted")
        require_tree_entry(
            api,
            repo,
            consumer["merge_tree"],
            consumer["gitlink_path"],
            mode="160000",
            sha=consumer["gitlink_commit"],
            label="promotion tree",
        )
        promoted = api.get(
            TYPIKON_REPOSITORY,
            f"git/commits/{consumer['gitlink_commit']}",
        )
        if promoted.get("tree", {}).get("sha") != consumer["gitlink_tree"]:
            raise LockError(f"{repo} promoted Typikon tree drifted")
        workflow_commit = api.get(repo, f"git/commits/{consumer['workflow_commit']}")
        workflow_tree = workflow_commit.get("tree", {}).get("sha")
        workflow_doc = api.get(repo, f"git/trees/{workflow_tree}?recursive=1")
        workflow_entries = [entry for entry in workflow_doc.get("tree", []) if entry.get("path") == consumer["workflow_path"]]
        if len(workflow_entries) != 1 or workflow_entries[0].get("mode") != "100644" or workflow_entries[0].get("sha") != consumer["workflow_blob"]:
            raise LockError(f"{repo} workflow blob drifted")
        verify_run(
            api,
            repo,
            consumer,
            consumer["head_commit"],
            consumer["workflow_path"],
            pull_request=consumer["pull_request"],
        )
        bundles[consumer["id"]] = verify_artifact(api, repo, consumer)
    return bundles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--emit-github-output", type=Path)
    parser.add_argument("--materialize-candidate", type=Path)
    args = parser.parse_args()
    try:
        lock = validate_lock_shape(read_json(args.lock))
        snapshot = read_json(args.snapshot) if args.snapshot else None
        bundles = verify_live(lock, GitHub(snapshot), args.lock)
        validate_bundle(lock, bundles)
        if args.materialize_candidate:
            args.materialize_candidate.mkdir(parents=True, exist_ok=False)
            for name, payload in bundles["candidate"].items():
                (args.materialize_candidate / name).write_bytes(payload)
        lock_digest = sha256(args.lock)
        if args.emit_github_output:
            with args.emit_github_output.open("a", encoding="utf-8") as handle:
                handle.write(f"candidate_commit={lock['release']['candidate_commit']}\n")
                handle.write(f"candidate_tree={lock['release']['candidate_tree']}\n")
                handle.write(f"tag={lock['release']['tag']}\n")
                handle.write(f"version={lock['release']['version']}\n")
                handle.write(f"release_pr={lock['release']['release_pr']}\n")
                handle.write(f"lock_sha256={lock_digest}\n")
        print(json.dumps({"status": "pass", "lock_sha256": lock_digest}, sort_keys=True))
    except (LockError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify-release-lock: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
