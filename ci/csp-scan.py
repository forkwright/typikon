#!/usr/bin/env python3
"""csp-scan — HTML-aware CSP violation scanner for csp-enforce.sh.

Parses each file with html.parser (stdlib) instead of matching lines with
regex, so a violation split across lines, spelled with single/unquoted
attribute values, written in uppercase, or hidden behind an HTML entity is
still caught. External references (`<script src>`, `<link rel=stylesheet>`)
are never flagged — only inline bodies and inline attribute values are.

Usage:
    ci/csp-scan.py <file> [<file> ...]
    ci/csp-scan.py < <(printf '%s\n' <file> ...)   # newline-delimited paths on stdin

WHY stdin too: a caller with a large discovered file list (csp-enforce.sh
scanning an entire built site) risks E2BIG passing that list as argv to an
execve() — a limit stdin has no equivalent of. argv still works for direct/
small invocations; it takes precedence when non-empty.

Exit:
    0  no violations
    1  violations found (each printed to stderr as "<path>:<line>: <detail>")
    2  invocation error (no paths given on argv or stdin)
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser

# INVARIANT: mirrors the boundary condition the original grep encoded —
# an attribute literally named on<letters> ("onclick", "onmouseover", ...),
# not any attribute whose value merely contains the substring "on".
_HANDLER_PREFIX = "on"

# WHY: browsers strip TAB/CR/LF from a URL scheme before parsing it, which
# is a known javascript: filter bypass ("java\tscript:"). Stripped before
# the scheme check so that evasion doesn't slip through unflagged.
_CONTROL_CHARS = str.maketrans("", "", "\t\r\n")

# WHY: a <script> element's `type` decides whether the browser ever hands
# its body to the JS engine at all. Per the HTML living standard, a type
# that isn't empty/a JavaScript MIME type/"module"/"importmap" makes the
# element an inert data block — the parser never executes it, so CSP's
# script-src has nothing to block. typikon's own JSON-LD partials
# (templates/partials/ld-*.html) rely on exactly this: structured-data
# <script type="application/ld+json"> under strict script-src 'self'
# with no 'unsafe-inline'. Anything not in this list is treated as
# executable and flagged — fail-closed on an unrecognized type.
_INERT_SCRIPT_TYPES = frozenset({"application/json", "application/ld+json"})


class CSPScanner(HTMLParser):
    def __init__(self, path: str):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.violations: list[tuple[int, str]] = []
        self._body_tag: str | None = None
        self._body_start_line = 0
        self._body_chunks: list[str] = []
        self._body_inert = False

    def _flag(self, detail: str) -> None:
        line, _ = self.getpos()
        self.violations.append((line, detail))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._body_tag = tag
            self._body_start_line, _ = self.getpos()
            self._body_chunks = []
            script_type = next((v for n, v in attrs if n == "type"), None)
            self._body_inert = (
                tag == "script"
                and script_type is not None
                and script_type.strip().lower() in _INERT_SCRIPT_TYPES
            )

        for name, value in attrs:
            if value is None:
                continue
            if name == "style" and value != "":
                self._flag(f'inline style="..." attribute on <{tag}>')
            elif name.startswith(_HANDLER_PREFIX) and name[len(_HANDLER_PREFIX):].isalpha():
                self._flag(f'{name}="..." event handler on <{tag}>')

            scheme_probe = value.translate(_CONTROL_CHARS).strip().lower()
            if scheme_probe.startswith("javascript:"):
                self._flag(f'{name}="javascript:..." URL on <{tag}>')

    def handle_data(self, data: str) -> None:
        if self._body_tag is not None:
            self._body_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._body_tag:
            body = "".join(self._body_chunks)
            if body.strip() and not self._body_inert:
                self._flag(f"inline <{tag}>...content...</{tag}> body")
            self._body_tag = None
            self._body_chunks = []
            self._body_inert = False


def scan(path: str) -> list[tuple[int, str]]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        html = fh.read()
    scanner = CSPScanner(path)
    scanner.feed(html)
    scanner.close()
    return scanner.violations


def main(argv: list[str]) -> int:
    if argv:
        paths = argv
    elif sys.stdin.isatty():
        # WHY this gate is load-bearing rather than redundant: iterating a LIVE tty blocks
        # forever, waiting for input no interactive caller knows to send, so a bare
        # invocation hangs instead of printing the usage below. Only a closed or piped
        # stdin reaches EOF and falls through to an empty paths list; a terminal never
        # does. The stdin path itself stays, because it is what keeps a large file set
        # from hitting the argv size limit.
        paths = []
    else:
        paths = [line.rstrip("\n") for line in sys.stdin if line.strip()]

    if not paths:
        print("usage: ci/csp-scan.py <file> [<file> ...] (or newline-delimited paths on stdin)", file=sys.stderr)
        return 2

    total = 0
    for path in paths:
        for line, detail in scan(path):
            print(f"{path}:{line}: {detail}", file=sys.stderr)
            total += 1

    return 1 if total > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
