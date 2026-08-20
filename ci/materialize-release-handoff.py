#!/usr/bin/env python3
"""Download and fail-closed extract one sealed same-run release handoff."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_secret import SecretToken, require_secret

MAX_BYTES = 64 * 1024 * 1024


class HandoffError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def request_json(url: str, token: SecretToken) -> Any:
    token = require_secret(token)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token.expose()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "typikon-release-handoff",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise HandoffError(f"artifact metadata returned HTTP {exc.code}: {detail}") from exc


def download_zip(
    url: str, token: SecretToken, *, require_https: bool = True
) -> bytes:
    token = require_secret(token)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {token.expose()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "typikon-release-handoff",
        },
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise HandoffError(f"artifact download returned HTTP {exc.code}") from exc
        location = exc.headers.get("Location", "")
    else:
        with response:
            payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise HandoffError("sealed handoff exceeds 64 MiB")
        return payload
    parsed = urllib.parse.urlsplit(location)
    allowed_schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in allowed_schemes or not parsed.netloc or parsed.username:
        raise HandoffError("artifact API returned an unsafe redirect URL")
    unsigned = urllib.request.Request(
        location, headers={"User-Agent": "typikon-release-handoff"}
    )
    try:
        with urllib.request.urlopen(unsigned, timeout=60) as response:
            payload = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise HandoffError(f"signed artifact download returned HTTP {exc.code}") from exc
    if len(payload) > MAX_BYTES:
        raise HandoffError("sealed handoff exceeds 64 MiB")
    return payload


def expected_names(tag: str) -> set[str]:
    archive = f"typikon-{tag}.tar.gz"
    return {
        "candidate.json",
        archive,
        f"{archive}.sha256",
        f"{archive}.cdx.json",
        f"{archive}.provenance.intoto.jsonl",
        f"{archive}.sbom.intoto.jsonl",
        f"typikon-{tag}-compatibility-lock.json",
        f"typikon-{tag}-tools-receipt.json",
        f"typikon-{tag}-leather-receipt.json",
    }


def validate_metadata(
    metadata: Any,
    *,
    artifact_id: int,
    artifact_digest: str,
    run_id: int,
    run_attempt: int,
    tag: str,
) -> str:
    expected_name = (
        f"typikon-{tag}-verified-publication-{run_id}-{run_attempt}"
    )
    expected_digest = f"sha256:{artifact_digest.removeprefix('sha256:')}"
    workflow_run = metadata.get("workflow_run") if isinstance(metadata, dict) else None
    if (
        not isinstance(metadata, dict)
        or metadata.get("id") != artifact_id
        or metadata.get("name") != expected_name
        or metadata.get("expired") is not False
        or metadata.get("digest") != expected_digest
        or not isinstance(workflow_run, dict)
        or workflow_run.get("id") != run_id
    ):
        raise HandoffError("sealed handoff metadata differs from this run")
    return expected_digest


def materialize_zip(raw: bytes, digest: str, tag: str, output: Path) -> None:
    expected_digest = digest.removeprefix("sha256:")
    actual_digest = hashlib.sha256(raw).hexdigest()
    if expected_digest != actual_digest:
        raise HandoffError(
            f"sealed handoff digest differs: {actual_digest} != {expected_digest}"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            expected = expected_names(tag)
            if len(names) != len(set(names)) or set(names) != expected:
                raise HandoffError(
                    f"sealed handoff members must be {sorted(expected)}, found {sorted(names)}"
                )
            total = 0
            payloads: dict[str, bytes] = {}
            for info in infos:
                mode = stat.S_IFMT(info.external_attr >> 16)
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or mode not in {0, stat.S_IFREG}
                    or Path(info.filename).name != info.filename
                    or info.file_size > MAX_BYTES
                ):
                    raise HandoffError(f"sealed handoff member is unsafe: {info.filename!r}")
                total += info.file_size
                if total > MAX_BYTES:
                    raise HandoffError("sealed handoff expands beyond 64 MiB")
                payloads[info.filename] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise HandoffError("sealed handoff is not a valid ZIP") from exc
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        destination = output / name
        with destination.open("xb") as handle:
            handle.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", required=True, type=int)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        try:
            token = SecretToken.from_env("GITHUB_TOKEN")
        except ValueError:
            token = None
        if not args.repository or token is None:
            raise HandoffError("GITHUB_REPOSITORY and GITHUB_TOKEN are required")
        root = f"https://api.github.com/repos/{args.repository}"
        metadata = request_json(
            f"{root}/actions/artifacts/{args.artifact_id}", token
        )
        expected_digest = validate_metadata(
            metadata,
            artifact_id=args.artifact_id,
            artifact_digest=args.artifact_digest,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            tag=args.tag,
        )
        raw = download_zip(
            f"{root}/actions/artifacts/{args.artifact_id}/zip", token
        )
        materialize_zip(raw, expected_digest, args.tag, args.output)
        print(
            json.dumps(
                {
                    "status": "pass",
                    "artifact_id": args.artifact_id,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
                sort_keys=True,
            )
        )
    except (HandoffError, OSError, ValueError, TypeError) as exc:
        print(f"materialize-release-handoff: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
