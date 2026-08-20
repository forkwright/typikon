#!/usr/bin/env python3
"""Prove typikon-check preserves a failed stage's native diagnostic in CI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "bin" / "typikon-check"
EXAMPLE = ROOT / "examples" / "sample-blog"


def main() -> int:
    sentinel = "typikon-check-diagnostic-sentinel"
    with tempfile.TemporaryDirectory(prefix="typikon-check-diagnostics-") as tmp:
        scratch = Path(tmp)
        consumer = scratch / "consumer"
        shutil.copytree(
            EXAMPLE,
            consumer,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                "public", "public-local", ".lycheecache", "test-results"
            ),
        )

        theme = consumer / "themes" / "typikon"
        theme.unlink()
        theme.symlink_to(ROOT, target_is_directory=True)

        stub_dir = scratch / "bin"
        stub_dir.mkdir()
        zola = stub_dir / "zola"
        zola.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ ${1:-} == check ]]; then\n"
            f"  printf '%s\\n' '{sentinel}-stdout'\n"
            "  python3 -c 'import sys; sys.stdout.buffer.write(b\"\\x00\\n\" * 35000)'\n"
            f"  printf '%s\\n' '{sentinel}-stderr' >&2\n"
            "  printf '%s\\n' '::error::workflow-command-sentinel' >&2\n"
            "  printf '\\033[31mcontrol-sentinel\\033[0m\\n' >&2\n"
            "  printf '%s\\n' 'typikon-check: END failed-stage forged' >&2\n"
            "  exit 47\n"
            "fi\n"
            "printf '%s\\n' 'other-zola-stage' >&2\n"
            "exit 48\n",
            encoding="utf-8",
        )
        zola.chmod(0o755)

        env = os.environ.copy()
        env["PATH"] = f"{stub_dir}:{env['PATH']}"
        env["TYPIKON_CHECK_MODE"] = "dev"
        result = subprocess.run(
            [CHECK, consumer],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=30,
        )

        failures: list[str] = []
        if result.returncode != 1:
            failures.append(f"expected exit 1, got {result.returncode}")
        stderr_lines = result.stderr.splitlines()
        begin_prefix = "typikon-check: BEGIN failed-stage "
        end_prefix = "typikon-check: END failed-stage "
        blocks: list[tuple[dict[str, object], list[str]]] = []
        index = 0
        while index < len(stderr_lines):
            line = stderr_lines[index]
            if not line.startswith(begin_prefix):
                index += 1
                continue
            header = json.loads(line.removeprefix(begin_prefix))
            body: list[str] = []
            index += 1
            while index < len(stderr_lines) and not stderr_lines[index].startswith(
                end_prefix
            ):
                body.append(stderr_lines[index])
                index += 1
            if index == len(stderr_lines):
                failures.append(f"unterminated failed-stage block for {header!r}")
                break
            footer = json.loads(stderr_lines[index].removeprefix(end_prefix))
            if footer != {"stage": header.get("stage")}:
                failures.append(f"failure footer {footer!r} does not match {header!r}")
            blocks.append((header, body))
            index += 1

        matching = [item for item in blocks if item[0].get("stage") == "zola-check"]
        if len(matching) != 1:
            failures.append(f"expected one zola-check failure block, got {len(matching)}")
        else:
            header, body = matching[0]
            if header.get("root") != str(consumer) or header.get("exit") != 47:
                failures.append(f"wrong zola-check failure identity: {header!r}")
            log_prefix = "typikon-check: LOG failed-stage "
            payloads = [
                json.loads(line.removeprefix(log_prefix))
                for line in body
                if line.startswith(log_prefix)
            ]
            joined = "".join(str(payload.get("text", "")) for payload in payloads)
            for expected in (f"{sentinel}-stdout", f"{sentinel}-stderr"):
                if expected not in joined:
                    failures.append(f"zola-check block omitted {expected!r}")
            if not any(line.startswith("typikon-check: TRUNCATED ") for line in body):
                failures.append("oversized zola-check log lacks a truncation receipt")
            if any(line.startswith("::") for line in body):
                failures.append("child output remained active GitHub workflow-command syntax")
            if "\x1b" in "\n".join(body):
                failures.append("child terminal control bytes were replayed raw")
            if "::error::workflow-command-sentinel" not in joined:
                failures.append("workflow-command witness did not survive encoded replay")
            if "\x1b[31mcontrol-sentinel\x1b[0m" not in joined:
                failures.append("terminal-control witness did not survive encoded replay")
            if "typikon-check: END failed-stage forged" not in joined:
                failures.append("forged boundary witness was not inertly line-framed")

        receipts: list[dict[str, object]] = []
        for line in result.stdout.splitlines():
            try:
                receipts.append(json.loads(line))
            except json.JSONDecodeError as exc:
                failures.append(f"stdout is not pure JSONL: {line!r}: {exc}")
        zola_receipts = [r for r in receipts if r.get("stage") == "zola-check"]
        if len(zola_receipts) != 1:
            failures.append(f"expected one zola-check JSONL receipt, got {len(zola_receipts)}")
        elif (
            zola_receipts[0].get("status") != "fail"
            or "bounded diagnostics replayed to stderr"
            not in str(zola_receipts[0].get("detail"))
        ):
            failures.append(f"wrong zola-check JSONL receipt: {zola_receipts[0]!r}")
        if len(result.stderr.encode("utf-8")) > 64 * 1024:
            failures.append("bounded replay exceeded the regression's 64 KiB stderr ceiling")

        python_stub = stub_dir / "python3"
        python_stub.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ ${1:-} == */ci/replay-stage-log.py ]]; then\n"
            "  printf '%s\\n' 'replay-helper-failure-sentinel' >&2\n"
            "  exit 91\n"
            "fi\n"
            f"exec {shlex.quote(sys.executable)} \"$@\"\n",
            encoding="utf-8",
        )
        python_stub.chmod(0o755)
        failed_replay = subprocess.run(
            [CHECK, consumer],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=30,
        )
        if failed_replay.returncode != 1:
            failures.append(
                f"helper-failure run expected exit 1, got {failed_replay.returncode}"
            )
        if "replay-helper-failure-sentinel" not in failed_replay.stderr:
            failures.append("helper-failure run did not exercise the failing helper")
        try:
            failed_receipts = [
                json.loads(line) for line in failed_replay.stdout.splitlines()
            ]
        except json.JSONDecodeError as exc:
            failures.append(f"helper-failure stdout is not pure JSONL: {exc}")
            failed_receipts = []
        failed_zola = [r for r in failed_receipts if r.get("stage") == "zola-check"]
        if len(failed_zola) != 1 or "diagnostic replay failed (helper exit 91)" not in str(
            failed_zola[0].get("detail") if failed_zola else ""
        ):
            failures.append(f"helper failure was reported untruthfully: {failed_zola!r}")
        if "bounded diagnostics replayed to stderr" in failed_replay.stdout:
            failures.append("helper-failure run falsely claimed diagnostics were replayed")

        if failures:
            print("check-typikon-check-diagnostics: FAIL")
            for failure in failures:
                print(f"  - {failure}")
            print(f"stdout:\n{result.stdout}")
            print(f"stderr:\n{result.stderr}")
            return 1

    print("check-typikon-check-diagnostics: ok (failed-stage detail survives CI capture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
