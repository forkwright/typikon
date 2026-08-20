#!/usr/bin/env python3
"""Idempotently publish one compatibility-locked Typikon release."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_archive import ArchiveError, verify_archive
from release_secret import SecretToken, require_secret

MAX_ASSET_BYTES = 64 * 1024 * 1024
ROOT = Path(__file__).resolve().parent.parent


class PublishError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_bytes(*args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise PublishError(
            result.stderr.decode(errors="replace").strip()
            or f"git {' '.join(args)} failed"
        )
    return result.stdout


def changelog_notes(candidate: str, version: str) -> str:
    text = git_bytes("show", f"{candidate}:CHANGELOG.md").decode()
    header = re.compile(rf"^## \[{re.escape(version)}\].*$", re.MULTILINE)
    matches = list(header.finditer(text))
    if len(matches) != 1:
        raise PublishError(
            f"candidate CHANGELOG must contain exactly one heading for {version}"
        )
    start = matches[0].end()
    following = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + following.start() if following else len(text)
    notes = text[start:end].strip()
    if not notes:
        raise PublishError("candidate CHANGELOG release notes are empty")
    return notes


def exact_tag_message(tag: str, lock_sha256: str) -> str:
    return f"Typikon {tag}\n\nCompatibility-Lock-SHA256: {lock_sha256}"


def api_download(url: str, token: SecretToken) -> bytes:
    token = require_secret(token)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {token.expose()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "typikon-release-publisher",
        },
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise PublishError(f"asset API returned HTTP {exc.code}") from exc
        location = exc.headers.get("Location", "")
    else:
        with response:
            payload = response.read(MAX_ASSET_BYTES + 1)
        if len(payload) > MAX_ASSET_BYTES:
            raise PublishError("release asset exceeds 64 MiB")
        return payload
    parsed = urllib.parse.urlsplit(location)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise PublishError("asset API returned an unsafe redirect URL")
    unsigned = urllib.request.Request(
        location, headers={"User-Agent": "typikon-release-publisher"}
    )
    with urllib.request.urlopen(unsigned, timeout=60) as response:
        payload = response.read(MAX_ASSET_BYTES + 1)
    if len(payload) > MAX_ASSET_BYTES:
        raise PublishError("release asset exceeds 64 MiB")
    return payload


class GitHubApi:
    def __init__(self, repository: str, token: SecretToken):
        self.repository = repository
        self.token = require_secret(token)
        self.api_root = f"https://api.github.com/repos/{repository}"

    def json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        missing_ok: bool = False,
    ) -> Any:
        data = None if payload is None else json.dumps(payload).encode()
        url = self.api_root if not endpoint else f"{self.api_root}/{endpoint}"
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token.expose()}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "typikon-release-publisher",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return None if not raw else json.loads(raw)
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            detail = exc.read().decode(errors="replace")
            raise PublishError(
                f"GitHub {method} {endpoint} returned {exc.code}: {detail}"
            ) from exc

    def get_ref(self, tag: str) -> dict[str, Any] | None:
        return self.json("GET", f"git/ref/tags/{tag}", missing_ok=True)

    def get_branch_head(self, branch: str) -> str:
        value = self.json("GET", f"git/ref/heads/{branch}")
        head = value.get("object", {}).get("sha")
        if not isinstance(head, str):
            raise PublishError(f"refs/heads/{branch} has no object id")
        return head

    def get_default_branch(self) -> str:
        value = self.json("GET", "")
        branch = value.get("default_branch")
        if not isinstance(branch, str):
            raise PublishError("repository has no default branch")
        return branch

    def create_tag(self, tag: str, message: str, candidate: str) -> dict[str, Any]:
        return self.json(
            "POST",
            "git/tags",
            {"tag": tag, "message": message, "object": candidate, "type": "commit"},
        )

    def create_ref(self, tag: str, tag_object: str) -> None:
        self.json(
            "POST", "git/refs", {"ref": f"refs/tags/{tag}", "sha": tag_object}
        )

    def get_tag(self, object_id: str) -> dict[str, Any]:
        return self.json("GET", f"git/tags/{object_id}")

    def get_release(self, tag: str) -> dict[str, Any] | None:
        # GitHub's release-by-tag endpoint returns published releases only.
        # Publication is deliberately staged through a draft, so use the
        # authenticated list endpoint and exact-match the tag across every
        # page. Treat duplicates as corruption instead of selecting one.
        matches: list[dict[str, Any]] = []
        for page in range(1, 101):
            value = self.json("GET", f"releases?per_page=100&page={page}")
            if not isinstance(value, list):
                raise PublishError("release list response is not a list")
            matches.extend(
                release for release in value if release.get("tag_name") == tag
            )
            if len(value) < 100:
                break
        else:
            raise PublishError("release list exceeded 10,000 records")
        if len(matches) > 1:
            raise PublishError(f"multiple releases name tag {tag}")
        return matches[0] if matches else None

    def create_release(
        self, tag: str, candidate: str, name: str, body: str
    ) -> dict[str, Any]:
        return self.json(
            "POST",
            "releases",
            {
                "tag_name": tag,
                "target_commitish": candidate,
                "name": name,
                "body": body,
                "draft": True,
                "prerelease": False,
            },
        )

    def list_assets(self, release_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for page in range(1, 101):
            value = self.json(
                "GET", f"releases/{release_id}/assets?per_page=100&page={page}"
            )
            if not isinstance(value, list):
                raise PublishError("release asset response is not a list")
            result.extend(value)
            if len(value) < 100:
                return result
        raise PublishError("release asset list exceeded 10,000 records")

    def download_asset(self, asset_id: int) -> bytes:
        return api_download(
            f"{self.api_root}/releases/assets/{asset_id}", self.token
        )

    def upload_asset(self, release_id: int, name: str, payload: bytes) -> dict[str, Any]:
        query = urllib.parse.urlencode({"name": name})
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        request = urllib.request.Request(
            f"https://uploads.github.com/repos/{self.repository}/releases/{release_id}/assets?{query}",
            data=payload,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token.expose()}",
                "Content-Type": content_type,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "typikon-release-publisher",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise PublishError(f"release asset upload returned {exc.code}: {detail}") from exc

    def delete_asset(self, asset_id: int) -> None:
        self.json("DELETE", f"releases/assets/{asset_id}")

    def publish_release(self, release_id: int) -> dict[str, Any]:
        return self.json("PATCH", f"releases/{release_id}", {"draft": False})


def expected_asset_names(tag: str) -> set[str]:
    return {
        "candidate.json",
        f"typikon-{tag}.tar.gz",
        f"typikon-{tag}.tar.gz.sha256",
        f"typikon-{tag}.tar.gz.cdx.json",
        f"typikon-{tag}.tar.gz.provenance.intoto.jsonl",
        f"typikon-{tag}.tar.gz.sbom.intoto.jsonl",
        f"typikon-{tag}-compatibility-lock.json",
        f"typikon-{tag}-tools-receipt.json",
        f"typikon-{tag}-leather-receipt.json",
    }


def expected_assets(directory: Path, tag: str) -> dict[str, bytes]:
    names = expected_asset_names(tag)
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    if actual != names:
        raise PublishError(
            f"release staging members must be {sorted(names)}, found {sorted(actual)}"
        )
    payloads = {name: (directory / name).read_bytes() for name in sorted(names)}
    if any(len(payload) > MAX_ASSET_BYTES for payload in payloads.values()):
        raise PublishError("release staging contains an asset over 64 MiB")
    return payloads


def validate_staged_evidence(
    payloads: dict[str, bytes],
    tag: str,
    candidate: str,
    lock_sha256: str,
    tracked_lock: Path,
) -> dict[str, Any]:
    resolved_lock = tracked_lock.resolve()
    compatibility_root = (ROOT / "release" / "compatibility").resolve()
    if (
        compatibility_root not in resolved_lock.parents
        or resolved_lock.suffix != ".json"
        or not resolved_lock.is_file()
    ):
        raise PublishError("tracked lock path is not a compatibility JSON")
    relative_lock = resolved_lock.relative_to(ROOT).as_posix()
    git_bytes("ls-files", "--error-unmatch", "--", relative_lock)
    lock_name = f"typikon-{tag}-compatibility-lock.json"
    lock_bytes = payloads[lock_name]
    tracked_lock_bytes = resolved_lock.read_bytes()
    if lock_bytes != tracked_lock_bytes:
        raise PublishError("sealed compatibility lock differs from the tracked lock")
    if digest_bytes(lock_bytes) != lock_sha256:
        raise PublishError("staged compatibility lock digest differs from the verifier")
    try:
        lock = json.loads(lock_bytes)
        manifest = json.loads(payloads["candidate.json"])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(f"staged evidence JSON is invalid: {exc}") from exc
    release = lock.get("release", {})
    if release.get("tag") != tag or release.get("candidate_commit") != candidate:
        raise PublishError("staged compatibility lock names another release subject")
    candidate_release = manifest.get("release", {})
    if candidate_release.get("tag") != tag or candidate_release.get(
        "candidate_commit"
    ) != candidate:
        raise PublishError("staged candidate manifest names another release subject")
    artifact = lock.get("candidate_artifact")
    if not isinstance(artifact, dict):
        raise PublishError("staged compatibility lock has no candidate artifact")
    for kind in ("archive", "checksum", "sbom"):
        item = manifest.get(kind, {})
        name = item.get("name")
        if not isinstance(name, str) or name not in payloads:
            raise PublishError(f"staged candidate {kind} member is missing")
        value = payloads[name]
        if item.get("sha256") != digest_bytes(value) or item.get("size") != len(value):
            raise PublishError(f"staged candidate {kind} bytes differ from the manifest")
        expected = {
            "name": artifact.get(f"{kind}_name"),
            "sha256": artifact.get(f"{kind}_sha256"),
            "size": artifact.get(f"{kind}_size"),
        }
        if item != expected:
            raise PublishError(f"staged candidate {kind} differs from the tracked lock")
    try:
        verify_archive(payloads[manifest["archive"]["name"]], ROOT, candidate)
    except ArchiveError as exc:
        raise PublishError(str(exc)) from exc
    checksum = manifest["checksum"]
    expected_checksum = (
        f"{manifest['archive']['sha256']}  {manifest['archive']['name']}\n".encode()
    )
    if payloads[checksum["name"]] != expected_checksum:
        raise PublishError("staged checksum is not the canonical sha256sum record")
    notes = manifest.get("notes")
    if not isinstance(notes, dict) or set(notes) != {"body", "sha256", "size"}:
        raise PublishError("staged candidate release notes are invalid")
    body = notes.get("body")
    if not isinstance(body, str) or not body:
        raise PublishError("staged candidate release notes are empty")
    body_bytes = body.encode("utf-8")
    if notes.get("sha256") != digest_bytes(body_bytes) or notes.get("size") != len(
        body_bytes
    ):
        raise PublishError("staged candidate release notes digest or size differs")
    if body != changelog_notes(candidate, str(release.get("version", ""))):
        raise PublishError("staged release notes differ from the candidate CHANGELOG")
    attestations = manifest.get("attestations")
    if not isinstance(attestations, dict) or set(attestations) != {"provenance", "sbom"}:
        raise PublishError("staged candidate attestation manifest is incomplete")
    for kind in ("provenance", "sbom"):
        item = attestations[kind]
        if not isinstance(item, dict) or set(item) != {"name", "sha256", "size"}:
            raise PublishError(f"staged candidate {kind} attestation manifest is invalid")
        name = item.get("name")
        if not isinstance(name, str) or name not in payloads:
            raise PublishError(f"staged candidate {kind} attestation bundle is missing")
        value = payloads[name]
        if item.get("sha256") != digest_bytes(value) or item.get("size") != len(value):
            raise PublishError(
                f"staged candidate {kind} attestation bytes differ from the manifest"
            )
        expected = {
            "name": artifact.get(f"{kind}_bundle_name"),
            "sha256": artifact.get(f"{kind}_bundle_sha256"),
            "size": artifact.get(f"{kind}_bundle_size"),
        }
        if item != expected:
            raise PublishError(
                f"staged candidate {kind} attestation differs from the tracked lock"
            )
    expected_receipts = {
        "tools": f"typikon-{tag}-tools-receipt.json",
        "leather": f"typikon-{tag}-leather-receipt.json",
    }
    consumers = lock.get("consumers")
    if not isinstance(consumers, list) or [item.get("id") for item in consumers] != [
        "tools",
        "leather",
    ]:
        raise PublishError("staged lock cohort is not Tools then Leather")
    for consumer in consumers:
        name = expected_receipts[consumer["id"]]
        receipt_path = (ROOT / str(consumer.get("receipt_path", ""))).resolve()
        if ROOT not in receipt_path.parents or not receipt_path.is_file():
            raise PublishError(f"tracked {consumer['id']} receipt path is unsafe or missing")
        git_bytes(
            "ls-files",
            "--error-unmatch",
            "--",
            receipt_path.relative_to(ROOT).as_posix(),
        )
        if payloads[name] != receipt_path.read_bytes():
            raise PublishError(f"sealed {consumer['id']} receipt differs from tracked bytes")
        if digest_bytes(payloads[name]) != consumer.get("receipt_sha256"):
            raise PublishError(f"staged {consumer['id']} receipt differs from the lock")
    return lock


def validate_tag(
    api: Any, ref: dict[str, Any], tag: str, candidate: str, message: str
) -> str:
    subject = ref.get("object", {})
    if subject.get("type") != "tag" or not isinstance(subject.get("sha"), str):
        raise PublishError(f"refs/tags/{tag} is not an annotated tag")
    object_id = subject["sha"]
    document = api.get_tag(object_id)
    expected = {
        "tag": tag,
        "message": message,
        "type": "commit",
        "candidate": candidate,
    }
    actual = {
        "tag": document.get("tag"),
        "message": document.get("message"),
        "type": document.get("object", {}).get("type"),
        "candidate": document.get("object", {}).get("sha"),
    }
    if actual != expected:
        raise PublishError(f"annotated tag identity drifted: {actual!r} != {expected!r}")
    return object_id


def require_main_head(api: Any, evidence_commit: str) -> None:
    if api.get_default_branch() != "main":
        raise PublishError("repository default branch is not main")
    if api.get_branch_head("main") != evidence_commit:
        raise PublishError("main moved away from the verified evidence commit")


def ensure_tag(
    api: Any,
    tag: str,
    candidate: str,
    message: str,
    evidence_commit: str,
) -> str:
    ref = api.get_ref(tag)
    if ref is None:
        # Every staged byte is exact before this boundary. These repeated
        # guards narrow the only unavoidable cross-ref race:
        # GitHub exposes tag-object and tag-ref creation as separate REST calls.
        require_main_head(api, evidence_commit)
        created = api.create_tag(tag, message, candidate)
        object_id = created.get("sha")
        if not isinstance(object_id, str):
            raise PublishError("tag-object creation returned no object id")
        require_main_head(api, evidence_commit)
        try:
            api.create_ref(tag, object_id)
        except PublishError:
            # A competing exact retry may have created the ref after our read.
            ref = api.get_ref(tag)
            if ref is None:
                raise
        else:
            ref = api.get_ref(tag)
    if ref is None:
        raise PublishError(f"refs/tags/{tag} was not created")
    object_id = validate_tag(api, ref, tag, candidate, message)
    # If main moved during the ref POST, leave only the exact provisional tag.
    # Do not try to restore an old main tip. Resolving that public residue is a
    # separate destructive recovery action with its own review boundary.
    require_main_head(api, evidence_commit)
    return object_id


def release_marker(candidate: str, lock_sha256: str) -> str:
    return (
        f"Candidate commit: `{candidate}`\n"
        f"Compatibility lock SHA-256: `{lock_sha256}`"
    )


def exact_release_body(
    payloads: dict[str, bytes], candidate: str, lock_sha256: str
) -> str:
    try:
        manifest = json.loads(payloads["candidate.json"])
        notes = manifest["notes"]["body"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PublishError(f"candidate release notes cannot be read: {exc}") from exc
    if not isinstance(notes, str) or not notes:
        raise PublishError("candidate release notes body is empty")
    return f"{notes}\n\n{release_marker(candidate, lock_sha256)}\n"


def validate_release(
    release: dict[str, Any],
    tag: str,
    expected_body: str,
) -> None:
    # The annotated tag ref/object is the release subject authority.
    # GitHub documents target_commitish as unused when tag_name already exists
    # and may report the default branch for such releases, so it is not an
    # identity field after ensure_tag() has established the exact commit.
    if (
        release.get("tag_name") != tag
        or release.get("name") != f"Typikon {tag}"
        or release.get("prerelease") is not False
        or release.get("body") != expected_body
    ):
        raise PublishError("release identity differs from the compatibility lock")


def reconcile_assets(
    api: Any,
    release: dict[str, Any],
    payloads: dict[str, bytes],
    *,
    allow_upload: bool,
) -> None:
    assets = api.list_assets(int(release["id"]))
    by_name: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        by_name.setdefault(str(asset.get("name")), []).append(asset)
    if set(by_name) - set(payloads):
        raise PublishError(
            f"release has unexpected assets: {sorted(set(by_name) - set(payloads))}"
        )
    for name, expected in payloads.items():
        matches = by_name.get(name, [])
        if len(matches) > 1:
            raise PublishError(f"release has duplicate asset {name}")
        if not matches:
            if not allow_upload:
                raise PublishError(f"published release is missing asset {name}")
            api.upload_asset(int(release["id"]), name, expected)
            continue
        asset = matches[0]
        if asset.get("state") == "starter" and allow_upload:
            # GitHub can leave a zero-byte starter record after an upstream
            # 502. Deleting only that exact draft residue makes retry safe.
            api.delete_asset(int(asset["id"]))
            api.upload_asset(int(release["id"]), name, expected)
            continue
        if asset.get("state") not in {None, "uploaded"}:
            raise PublishError(f"release asset {name} is not uploaded")
        actual = api.download_asset(int(asset["id"]))
        if actual != expected:
            raise PublishError(
                f"release asset {name} differs: {digest_bytes(actual)} != {digest_bytes(expected)}"
            )


def inspect(
    api: Any,
    tag: str,
    candidate: str,
    lock_sha256: str,
    payloads: dict[str, bytes],
) -> str:
    ref = api.get_ref(tag)
    if ref is None:
        if api.get_release(tag) is not None:
            raise PublishError("release exists without its annotated tag")
        return "absent"
    validate_tag(api, ref, tag, candidate, exact_tag_message(tag, lock_sha256))
    release = api.get_release(tag)
    if release is None:
        return "tagged"
    expected_body = exact_release_body(payloads, candidate, lock_sha256)
    validate_release(release, tag, expected_body)
    if release.get("draft") is False:
        reconcile_assets(api, release, payloads, allow_upload=False)
        return "published"
    if release.get("draft") is not True:
        raise PublishError("release draft state is neither true nor false")
    # Drafts may be partially populated after an interrupted upload. Existing
    # names must already be exact; missing names are repaired by publish().
    existing = api.list_assets(int(release["id"]))
    for asset in existing:
        name = str(asset.get("name"))
        if name not in payloads:
            raise PublishError(f"draft release has unexpected asset {name}")
        if asset.get("state") == "starter":
            continue
        actual = api.download_asset(int(asset["id"]))
        if actual != payloads[name]:
            raise PublishError(f"draft release asset {name} differs from staged bytes")
    return "draft"


def publish(
    api: Any,
    tag: str,
    candidate: str,
    lock_sha256: str,
    payloads: dict[str, bytes],
    evidence_commit: str,
) -> str:
    require_main_head(api, evidence_commit)
    state = inspect(api, tag, candidate, lock_sha256, payloads)
    if state == "published":
        require_main_head(api, evidence_commit)
        return state
    message = exact_tag_message(tag, lock_sha256)
    ensure_tag(api, tag, candidate, message, evidence_commit)
    expected_body = exact_release_body(payloads, candidate, lock_sha256)
    release = api.get_release(tag)
    if release is None:
        release = api.create_release(
            tag, candidate, f"Typikon {tag}", expected_body
        )
    validate_release(release, tag, expected_body)
    if release.get("draft") is False:
        reconcile_assets(api, release, payloads, allow_upload=False)
        require_main_head(api, evidence_commit)
        return "published"
    if release.get("draft") is not True:
        raise PublishError("release draft state is neither true nor false")
    reconcile_assets(api, release, payloads, allow_upload=True)
    # Re-read every byte after all uploads and before the irreversible publish.
    release = api.get_release(tag)
    if release is None:
        raise PublishError("draft release disappeared before publication")
    validate_release(release, tag, expected_body)
    reconcile_assets(api, release, payloads, allow_upload=False)
    require_main_head(api, evidence_commit)
    api.publish_release(int(release["id"]))
    final = api.get_release(tag)
    if final is None or final.get("draft") is not False:
        raise PublishError("release did not become public")
    validate_release(final, tag, expected_body)
    final_ref = api.get_ref(tag)
    if final_ref is None:
        raise PublishError("annotated tag disappeared after publication")
    validate_tag(
        api,
        final_ref,
        tag,
        candidate,
        message,
    )
    reconcile_assets(api, final, payloads, allow_upload=False)
    # Detection after the irreversible PATCH cannot make the two GitHub REST
    # writes atomic. It does ensure branch movement never returns a green
    # publication receipt; the exact public release becomes reviewed residue.
    require_main_head(api, evidence_commit)
    return "published"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inspect", "publish"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--lock-sha256", required=True)
    parser.add_argument("--evidence-commit", required=True)
    parser.add_argument("--assets-dir", required=True, type=Path)
    parser.add_argument("--tracked-lock", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        try:
            token = SecretToken.from_env("GITHUB_TOKEN")
        except ValueError:
            token = None
        if not args.repository or token is None:
            raise PublishError("GITHUB_REPOSITORY and GITHUB_TOKEN are required")
        payloads = expected_assets(args.assets_dir, args.tag)
        lock = validate_staged_evidence(
            payloads,
            args.tag,
            args.candidate,
            args.lock_sha256,
            args.tracked_lock,
        )
        api = GitHubApi(args.repository, token)
        if args.command == "inspect":
            state = inspect(api, args.tag, args.candidate, args.lock_sha256, payloads)
        else:
            state = publish(
                api,
                args.tag,
                args.candidate,
                args.lock_sha256,
                payloads,
                args.evidence_commit,
            )
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as handle:
                handle.write(f"state={state}\n")
                handle.write(f"candidate_commit={lock['release']['candidate_commit']}\n")
                handle.write(f"lock_sha256={digest_bytes(args.tracked_lock.read_bytes())}\n")
                handle.write(f"release_pr={lock['release']['release_pr']}\n")
                handle.write(f"tag={lock['release']['tag']}\n")
        print(json.dumps({"status": "pass", "publication_state": state}, sort_keys=True))
    except (PublishError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"publish-locked-release: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
