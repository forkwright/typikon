#!/usr/bin/env python3
"""Replay a failed typikon-check stage without trusting its output as CI syntax.

Child output is arbitrary consumer/tool text. Framing retained head/tail chunks
as JSON strings prevents GitHub workflow commands, terminal controls, and
forged boundaries from becoming active protocol. Both input reads and encoded
output are bounded; the complete native log remains on disk for local runs.
This helper cannot identify credentials, so callers must not give gate stages
secrets to print.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


OUTPUT_LIMIT_BYTES = 60 * 1024
HEAD_BYTES = 4 * 1024
TAIL_BYTES = 4 * 1024
READ_LIMIT_BYTES = HEAD_BYTES + TAIL_BYTES


def frame(prefix: str, payload: object) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    return f"{prefix}{encoded}\n".encode("utf-8")


def read_chunks(path: Path) -> tuple[int, list[tuple[str, bytes]]]:
    with path.open("rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        if size <= READ_LIMIT_BYTES:
            return size, [("full", handle.read(READ_LIMIT_BYTES))]

        head = handle.read(HEAD_BYTES)
        handle.seek(max(size - TAIL_BYTES, 0))
        tail = handle.read(TAIL_BYTES)
        return size, [("head", head), ("tail", tail)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()

    log_bytes, chunks = read_chunks(args.log)
    retained_bytes = sum(len(data) for _, data in chunks)
    header = {
        "stage": args.stage,
        "root": args.root,
        "exit": args.exit_code,
        "log_bytes": log_bytes,
        "retained_bytes": retained_bytes,
        "output_limit_bytes": OUTPUT_LIMIT_BYTES,
    }
    output = [frame("typikon-check: BEGIN failed-stage ", header)]
    for label, data in chunks:
        output.append(
            frame(
                "typikon-check: LOG failed-stage ",
                {
                    "label": label,
                    "text": data.decode("utf-8", errors="backslashreplace"),
                },
            )
        )
    if log_bytes > retained_bytes:
        truncation = {
            "omitted_bytes": log_bytes - retained_bytes,
            "retained_head_bytes": len(chunks[0][1]),
            "retained_tail_bytes": len(chunks[-1][1]),
        }
        output.append(frame("typikon-check: TRUNCATED ", truncation))
    output.append(
        frame("typikon-check: END failed-stage ", {"stage": args.stage})
    )

    encoded = b"".join(output)
    if len(encoded) > OUTPUT_LIMIT_BYTES:
        print(
            "replay-stage-log: encoded failure record exceeds "
            f"{OUTPUT_LIMIT_BYTES}-byte output limit ({len(encoded)} bytes)",
            file=sys.stderr,
        )
        return 2
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
