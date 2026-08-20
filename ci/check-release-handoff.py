#!/usr/bin/env python3
"""Causal fixture for the raw, digest-bound release handoff extractor."""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import io
import tempfile
import threading
import warnings
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "materialize-release-handoff.py"
LOADER = importlib.machinery.SourceFileLoader("release_handoff", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
handoff = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(handoff)


def make_zip(tag: str, *, extra: str | None = None, duplicate: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(handoff.expected_names(tag)):
            archive.writestr(name, f"fixture:{name}\n")
        if extra:
            archive.writestr(extra, b"unexpected")
        if duplicate:
            archive.writestr("candidate.json", b"duplicate")
    return stream.getvalue()


def rejected(raw: bytes, digest: str, tag: str, label: str) -> None:
    with tempfile.TemporaryDirectory(prefix="typikon-handoff-reject-") as tmp:
        try:
            handoff.materialize_zip(raw, digest, tag, Path(tmp) / "out")
        except handoff.HandoffError:
            return
    raise AssertionError(f"handoff accepted {label}")


class RedirectSource(BaseHTTPRequestHandler):
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
    payload = b""

    def do_GET(self):  # noqa: N802
        type(self).authorization = self.headers.get("Authorization")
        self.send_response(200)
        self.send_header("Content-Length", str(len(type(self).payload)))
        self.end_headers()
        self.wfile.write(type(self).payload)

    def log_message(self, *args):
        pass


def redirect_probe(raw: bytes) -> None:
    RedirectTarget.payload = raw
    target = ThreadingHTTPServer(("127.0.0.1", 0), RedirectTarget)
    source = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSource)
    RedirectSource.target = f"http://127.0.0.1:{target.server_port}/signed"
    threads = [
        threading.Thread(target=target.serve_forever, daemon=True),
        threading.Thread(target=source.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        token = handoff.SecretToken("fixture-token")
        try:
            handoff.download_zip(
                f"http://127.0.0.1:{source.server_port}/artifact",
                "fixture-token",
                require_https=False,
            )
        except TypeError:
            pass
        else:
            raise AssertionError("handoff downloader accepted a bare token string")
        actual = handoff.download_zip(
            f"http://127.0.0.1:{source.server_port}/artifact",
            token,
            require_https=False,
        )
        assert actual == raw
        assert RedirectSource.authorization == "Bearer fixture-token"
        assert RedirectTarget.authorization is None
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()


def main() -> int:
    tag = "v0.6.0"
    raw = make_zip(tag)
    digest = hashlib.sha256(raw).hexdigest()
    redirect_probe(raw)
    metadata = {
        "id": 91,
        "name": f"typikon-{tag}-verified-publication-123-1",
        "expired": False,
        "digest": f"sha256:{digest}",
        "workflow_run": {"id": 123},
    }
    assert handoff.validate_metadata(
        metadata,
        artifact_id=91,
        artifact_digest=digest,
        run_id=123,
        run_attempt=1,
        tag=tag,
    ) == f"sha256:{digest}"
    for label, mutate in (
        ("artifact id", lambda value: value.__setitem__("id", 92)),
        ("artifact name/attempt", lambda value: value.__setitem__("name", f"typikon-{tag}-verified-publication-123-2")),
        ("expired artifact", lambda value: value.__setitem__("expired", True)),
        ("artifact digest", lambda value: value.__setitem__("digest", "sha256:" + "0" * 64)),
        ("workflow run", lambda value: value.__setitem__("workflow_run", {"id": 124})),
    ):
        mutant = dict(metadata)
        mutant["workflow_run"] = dict(metadata["workflow_run"])
        mutate(mutant)
        try:
            handoff.validate_metadata(
                mutant,
                artifact_id=91,
                artifact_digest=digest,
                run_id=123,
                run_attempt=1,
                tag=tag,
            )
        except handoff.HandoffError:
            pass
        else:
            raise AssertionError(f"handoff accepted wrong {label}")
    with tempfile.TemporaryDirectory(prefix="typikon-handoff-") as tmp:
        output = Path(tmp) / "out"
        handoff.materialize_zip(raw, digest, tag, output)
        assert {path.name for path in output.iterdir()} == handoff.expected_names(tag)
    corrupted = bytearray(raw)
    corrupted[-1] ^= 1
    rejected(bytes(corrupted), digest, tag, "bytes with the upload digest")
    rejected(raw, "0" * 64, tag, "a false digest")
    extra = make_zip(tag, extra="unexpected")
    rejected(extra, hashlib.sha256(extra).hexdigest(), tag, "an extra member")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        duplicate = make_zip(tag, duplicate=True)
    rejected(duplicate, hashlib.sha256(duplicate).hexdigest(), tag, "a duplicate member")
    traversal = make_zip(tag, extra="../escape")
    rejected(traversal, hashlib.sha256(traversal).hexdigest(), tag, "path traversal")
    print("check-release-handoff: ok (raw digest and exact members enforced)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
