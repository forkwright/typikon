#!/usr/bin/env python3
"""Verify a frozen Git source archive by content, independent of gzip bytes."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 64 * 1024 * 1024


class ArchiveError(RuntimeError):
    pass


def git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ArchiveError(
            result.stderr.decode(errors="replace").strip()
            or f"git {' '.join(args)} failed"
        )
    return result.stdout


def tree_entries(root: Path, revision: str) -> dict[str, tuple[str, bytes]]:
    raw = git_bytes(root, "ls-tree", "-rz", "--full-tree", "-r", revision)
    entries: dict[str, tuple[str, bytes]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8", errors="surrogateescape")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ArchiveError("git tree contains an unparseable entry") from exc
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ArchiveError(
                f"release tree entry {path!r} has unsupported mode/type {mode} {kind}"
            )
        if path in entries:
            raise ArchiveError(f"release tree contains duplicate path {path!r}")
        entries[path] = (mode, git_bytes(root, "cat-file", "blob", object_id))
    return entries


def verify_archive(payload: bytes, root: Path, revision: str) -> None:
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ArchiveError("source archive exceeds 64 MiB")
    expected = tree_entries(root, revision)
    observed: dict[str, tuple[str, int, bytes | str]] = {}
    expected_directories = {
        parent.as_posix()
        for path in expected
        for parent in Path(path).parents
        if parent != Path(".")
    }
    observed_directories: set[str] = set()
    total_content_bytes = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            if archive.pax_headers.get("comment") != revision:
                raise ArchiveError("source archive does not bind the candidate commit")
            for member in archive.getmembers():
                path = member.name.rstrip("/") if member.isdir() else member.name
                parts = Path(path).parts
                if (
                    not path
                    or Path(path).is_absolute()
                    or ".." in parts
                    or path in observed
                    or path in observed_directories
                ):
                    raise ArchiveError(f"source archive member is unsafe: {member.name!r}")
                if member.isdir():
                    if member.mode & 0o7777 != 0o775:
                        raise ArchiveError(
                            f"source archive directory mode differs at {path}"
                        )
                    observed_directories.add(path)
                    continue
                if member.isfile():
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise ArchiveError(f"source archive cannot read {path!r}")
                    value: bytes | str = handle.read(MAX_ARCHIVE_BYTES + 1)
                    if len(value) > MAX_ARCHIVE_BYTES:
                        raise ArchiveError(f"source archive member is too large: {path!r}")
                    total_content_bytes += len(value)
                    kind = "file"
                elif member.issym():
                    value = member.linkname
                    total_content_bytes += len(value.encode("utf-8", errors="surrogateescape"))
                    kind = "symlink"
                else:
                    raise ArchiveError(
                        f"source archive contains a special member: {member.name!r}"
                    )
                if total_content_bytes > MAX_ARCHIVE_CONTENT_BYTES:
                    raise ArchiveError("source archive expands beyond 64 MiB")
                observed[path] = (kind, member.mode & 0o7777, value)
    except (tarfile.TarError, OSError) as exc:
        raise ArchiveError(f"source archive is invalid: {exc}") from exc

    if observed_directories != expected_directories:
        raise ArchiveError(
            "source archive directories differ from the candidate tree: "
            f"missing={sorted(expected_directories - observed_directories)}, "
            f"extra={sorted(observed_directories - expected_directories)}"
        )
    if set(observed) != set(expected):
        raise ArchiveError(
            "source archive paths differ from the candidate tree: "
            f"missing={sorted(set(expected) - set(observed))}, "
            f"extra={sorted(set(observed) - set(expected))}"
        )
    for path, (mode, blob) in expected.items():
        kind, archived_mode, value = observed[path]
        if mode == "120000":
            target = blob.decode("utf-8", errors="surrogateescape")
            if kind != "symlink" or archived_mode != 0o777 or value != target:
                raise ArchiveError(f"source archive symlink differs at {path}")
            continue
        expected_mode = 0o775 if mode == "100755" else 0o664
        if (
            kind != "file"
            or archived_mode != expected_mode
            or value != blob
        ):
            raise ArchiveError(f"source archive file differs at {path}")
