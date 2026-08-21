#!/usr/bin/env python3
"""render-template — render a ci/*.tmpl from ci/tool-lock.toml (forkwright/typikon#58).

Replaces the two hand-maintained `sed -e` blocks in bin/typikon-init and
bin/typikon-refresh. Those listed every substitution twice, identically, so
adding a placeholder meant editing two scripts in step — the same duplication
this issue is about, one level up. Here the substitution set IS the lock: a
tool gains a placeholder by being declared, not by anyone remembering.

Two behaviours are load-bearing and neither is an optimisation.

**An unresolved placeholder is a failure, not a passthrough.** `sed` leaves an
unmatched `{{ FOO }}` in the output, so a typo shipped a literal brace sequence
into a consumer's workflow, where it surfaces much later as a shell or YAML
error naming nothing useful. Refusing to write the file puts the error at the
edit.

**--verify-upstream proves the pair rather than the copies.** Every other check
in this repository proves the N copies of a checksum agree with each other,
which stays true when all N are wrong for a freshly bumped version. This one
fetches the locked URL and hashes the bytes. It is network-bound and belongs to
the act of bumping a tool, not to every gate run.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import toollock  # noqa: E402

# WHY the negative lookbehind: `${{ github.run_id }}` is a GitHub Actions
# expression that belongs to the rendered workflow, not a typikon placeholder.
# Dotted forms already fail the name pattern, but a single-word one --
# `${{ inputs }}` -- would otherwise be read as an undeclared placeholder and
# refuse to render a file that was perfectly correct. The `$` is the whole
# distinction, so it is matched rather than inferred.
PLACEHOLDER = re.compile(r"(?<!\$)\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
DOWNLOAD_TIMEOUT_SECONDS = 120


def render(text: str, values: dict[str, str], source: str) -> str:
    unknown: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            unknown.add(key)
            return match.group(0)
        return values[key]

    out = PLACEHOLDER.sub(replace, text)
    if unknown:
        known = ", ".join(sorted(values))
        raise SystemExit(
            f"render-template: {source} uses placeholder(s) "
            f"{', '.join(sorted(unknown))} that ci/tool-lock.toml does not define.\n"
            f"  declared: {known}\n"
            "  Refusing to write a file carrying an unresolved placeholder."
        )
    return out


def verify_upstream(tools: list[toollock.Tool]) -> int:
    """Download each locked archive and confirm its bytes hash to the locked value."""
    failures: list[str] = []
    checked = 0
    for tool in tools:
        url = tool.resolved_url()
        if not url or not tool.sha256:
            continue
        checked += 1
        print(f"render-template: fetching {tool.name} {tool.version} …", file=sys.stderr)
        try:
            with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                digest = hashlib.sha256(response.read()).hexdigest()
        except Exception as exc:  # noqa: BLE001 — any failure to fetch is a failure to prove
            failures.append(f"{tool.name} {tool.version}: could not fetch {url}: {exc}")
            continue
        if digest != tool.sha256:
            failures.append(
                f"{tool.name} {tool.version}: locked sha256 {tool.sha256} but {url} "
                f"hashes to {digest} — the version and the checksum name different releases"
            )
    if failures:
        for failure in failures:
            print(f"render-template: {failure}", file=sys.stderr)
        return 1
    if not checked:
        print("render-template: no archive entries to verify", file=sys.stderr)
        return 1
    print(f"render-template: ok ({checked} archive(s) hash to their locked value)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", type=Path, default=toollock.LOCK_PATH)
    parser.add_argument("--project-name", default=None,
                        help="value for {{ PROJECT_NAME }}")
    parser.add_argument("--verify-upstream", action="store_true",
                        help="fetch each locked archive and confirm its hash; network-bound")
    parser.add_argument("template", type=Path, nargs="?", help="the .tmpl to render")
    parser.add_argument("--output", type=Path, help="write here instead of stdout")
    args = parser.parse_args(argv)

    try:
        tools = toollock.load(args.lock)
    except toollock.LockError as exc:
        print(f"render-template: {exc}", file=sys.stderr)
        return 1

    if args.verify_upstream:
        return verify_upstream(tools)

    if args.template is None:
        parser.error("a template path is required unless --verify-upstream is given")

    values = toollock.substitutions(tools)
    if args.project_name is not None:
        values["PROJECT_NAME"] = args.project_name

    text = args.template.read_text(encoding="utf-8")
    out = render(text, values, str(args.template))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
