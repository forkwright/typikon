#!/usr/bin/env python3
"""csp-scan's three input paths: argv, piped stdin, and a bare invocation at a terminal."""

# WHY a pty is allocated rather than passing an empty stdin: the defect this pins only exists
# when stdin is a LIVE terminal. Iterating one blocks forever, so csp-scan hung instead of
# printing its usage. Every cheap way to test it -- closed stdin, /dev/null, an empty pipe --
# reaches EOF immediately and passes against the broken code, which is why the regression
# survived a green CI: nothing in CI ever invokes this script from a terminal.

import os
import pty
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "ci/csp-scan.py"
TIMEOUT = 10

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"FAIL: {msg}", file=sys.stderr)


def bare_at_a_terminal() -> None:
    """No argv, stdin is a real tty: must print usage and exit 2, not block."""
    primary, secondary = pty.openpty()
    try:
        proc = subprocess.Popen(
            [sys.executable, str(SCAN)],
            stdin=secondary,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(secondary)
        secondary = -1
        try:
            _, err = proc.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            fail(
                f"csp-scan.py with no argv at a tty did not exit within {TIMEOUT}s -- it is "
                "blocking on a stdin read instead of printing usage"
            )
            return
        if proc.returncode != 2:
            fail(f"expected exit 2 at a tty with no argv, got {proc.returncode}")
        if "usage:" not in err:
            fail(f"expected a usage message on stderr at a tty, got: {err!r}")
    finally:
        os.close(primary)
        if secondary != -1:
            os.close(secondary)


def piped_stdin_still_reads() -> None:
    """A piped path list must still be consumed -- the E2BIG path this gate must not break."""
    sample = ROOT / "ci/csp-scan.py"
    proc = subprocess.run(
        [sys.executable, str(SCAN)],
        input=f"{sample}\n",
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    if proc.returncode == 2 and "usage:" in proc.stderr:
        fail("a piped path list was ignored -- the isatty gate swallowed the stdin path")


def empty_pipe_is_still_a_usage_error() -> None:
    """Closed/empty stdin must keep reaching the usage error rather than scanning nothing."""
    proc = subprocess.run(
        [sys.executable, str(SCAN)], input="", capture_output=True, text=True, timeout=TIMEOUT
    )
    if proc.returncode != 2:
        fail(f"expected exit 2 for an empty pipe, got {proc.returncode}")


def main() -> int:
    if not SCAN.exists():
        print(f"FAIL: {SCAN} not found", file=sys.stderr)
        return 1
    bare_at_a_terminal()
    piped_stdin_still_reads()
    empty_pipe_is_still_a_usage_error()
    if failures:
        return 1
    print("check-csp-scan-selftest: ok (tty exits 2, piped stdin reads, empty pipe errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
