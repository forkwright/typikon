#!/usr/bin/env python3
"""Prove generated workflows background and later kill the server process itself."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "ci" / "github-workflow.yml.tmpl"
STEP = "      - name: Serve public-local/ for browser-based gates\n"
NEXT_STEP = "      - name: pa11y (WCAG 2.1 AA)\n"
DIRECT = "          python3 -m http.server --directory public-local 8080 &\n"
PID = "          echo $! > /tmp/server.pid\n"
TEARDOWN = "      - name: Tear down static server\n"


def server_step(source: str) -> str:
    if source.count(STEP) != 1 or source.count(NEXT_STEP) != 1:
        raise ValueError("workflow must carry exactly one named server and pa11y step")
    start = source.index(STEP)
    end = source.index(NEXT_STEP, start)
    return source[start:end]


def named_step(source: str, marker: str) -> str:
    if source.count(marker) != 1:
        raise ValueError(f"workflow must carry exactly one {marker.strip()!r} step")
    start = source.index(marker)
    next_step = source.find("\n      - name:", start + len(marker))
    return source[start:] if next_step == -1 else source[start : next_step + 1]


def run_block(step: str) -> str:
    marker = "        run: |\n"
    if step.count(marker) != 1:
        raise ValueError("workflow step must carry exactly one block run command")
    lines: list[str] = []
    for line in step.splitlines()[step.splitlines().index("        run: |") + 1 :]:
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line else "")
    if not lines:
        raise ValueError("workflow run block is empty")
    return "\n".join(lines) + "\n"


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def exercise_process_topology(source: str) -> None:
    """Run the extracted server and teardown blocks against a scratch tree."""
    server = run_block(server_step(source))
    teardown = run_block(named_step(source, TEARDOWN))
    port = unused_port()
    pid = 0
    process_group = 0
    with tempfile.TemporaryDirectory(prefix="typikon-static-server-") as tmp:
        root = Path(tmp)
        public = root / "public-local"
        public.mkdir()
        sentinel = "typikon-static-server-sentinel"
        (public / "index.html").write_text(sentinel, encoding="utf-8")
        pid_file = root / "server.pid"
        server = server.replace("8080", str(port)).replace("/tmp/server.pid", str(pid_file))
        teardown = teardown.replace("/tmp/server.pid", str(pid_file))
        try:
            shell = subprocess.Popen(
                ["bash", "-euo", "pipefail", "-c", server],
                cwd=root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            process_group = shell.pid
            result = shell.wait(timeout=10)
            if result:
                raise RuntimeError(
                    f"extracted server step exited {result}"
                )
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
            expected = f"python3 -m http.server --directory public-local {port}"
            if expected not in cmdline:
                raise RuntimeError(f"$! names {cmdline!r}, not the direct server process")
            body = ""
            for _ in range(20):
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=1
                    ) as response:
                        body = response.read().decode()
                    break
                except OSError:
                    time.sleep(0.1)
            if body != sentinel:
                raise RuntimeError("recorded server PID did not serve public-local")
            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c", teardown],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode:
                raise RuntimeError(f"extracted teardown step failed: {result.stderr}")
            for _ in range(30):
                if not Path(f"/proc/{pid}").exists():
                    break
                time.sleep(0.1)
            if Path(f"/proc/{pid}").exists():
                raise RuntimeError("teardown left the recorded server process alive")
        finally:
            if pid and Path(f"/proc/{pid}").exists():
                os.kill(pid, signal.SIGKILL)
            if process_group:
                try:
                    os.killpg(process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def validate(source: str) -> list[str]:
    errors: list[str] = []
    try:
        step = server_step(source)
    except ValueError as exc:
        return [str(exc)]
    if step.count(DIRECT) != 1:
        errors.append("server step must background the direct --directory invocation exactly once")
    if step.count(PID) != 1:
        errors.append("server step must persist the direct child PID exactly once")
    if "cd public-local &&" in step:
        errors.append("server step must not background a cd/python compound command")
    if step.find(DIRECT) > step.find(PID):
        errors.append("server must start before its PID is recorded")
    return errors


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) == 2 else DEFAULT
    if len(sys.argv) > 2:
        print(f"usage: {Path(sys.argv[0]).name} [workflow]", file=sys.stderr)
        return 2
    source = path.read_text(encoding="utf-8")
    errors = validate(source)
    if errors:
        for error in errors:
            print(f"check-static-server-template: FAIL: {error}", file=sys.stderr)
        return 1

    if path == DEFAULT:
        mutants = {
            "compound-command": source.replace(
                DIRECT,
                "          cd public-local && python3 -m http.server 8080 &\n",
                1,
            ),
            "subshell-child": source.replace(
                DIRECT,
                "          (python3 -m http.server --directory public-local 8080) &\n",
                1,
            ),
            "missing-pid": source.replace(PID, "", 1),
        }
        for label, mutant in mutants.items():
            if not validate(mutant):
                print(
                    f"check-static-server-template: FAIL: accepted {label} mutant",
                    file=sys.stderr,
                )
                return 1
    try:
        exercise_process_topology(source)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(
            f"check-static-server-template: FAIL: process topology: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"check-static-server-template: ok ({path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
