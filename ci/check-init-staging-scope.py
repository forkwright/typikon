#!/usr/bin/env python3
"""check-init-staging-scope — regression test for bin/typikon-init's staging scope.

WHY: forkwright/typikon#54 — re-running bin/typikon-init in an existing
repository staged every unrelated change in that repository. bin/typikon-init
used to `git add -A` unconditionally whenever anything in the working tree
was dirty, which is a repository-wide sweep with no way to distinguish
typikon's own scaffold outputs from an operator's pre-existing, unrelated
work. The fix stages ONLY the paths this invocation itself created
(bin/typikon-init's OWN_OUTPUTS array), plus the submodule gitlink when it
actually moved, via NAMED `git add -f -- <path>` calls — the same mechanism
bin/typikon-refresh (Step 4) already used for its narrower surface. The
scaffold commit itself is likewise pathspec-scoped (`git commit -- <paths>`),
a second, independent gap the re-run scenario below cannot exercise (see
`check_first_commit_excludes_pre_staged_file`).

Harness pattern shared with ci/check-init-favicon-path.py: runs the REAL
bin/typikon-init against a throwaway destination, theme submodule pointed at
this checkout over the local-path transport (GIT_ALLOW_PROTOCOL=file — git
blocks that transport for submodules by default, CVE-2022-39253), fully
isolated HOME/env so this needs neither network nor a running local forge nor
the caller's ambient git config.

Two independent scenarios, each guarding a different code path:

`check_rerun_preserves_unrelated_state` — the re-run scope guard.
Fixture matrix (forkwright/typikon#54's Desired correction, verbatim: "Add
dirty-repository fixtures covering modified, deleted, staged, and untracked
unrelated files and assert their states remain exact"):
    - modified:   an already-tracked file edited in the working tree, left unstaged
    - deleted:    an already-tracked file removed from the working tree, left unstaged
    - staged:     a file with staged content PLUS a further, unstaged edit on top
                  (git-status "AM") — see the WHY beside `staged_path` below for
                  why a fully-staged-and-untouched file cannot discriminate this bug
    - untracked:  a brand-new file left untouched (no `git add` at all)

Sequence: bin/typikon-init runs ONCE (creates the scaffold + initial commit),
the four fixtures above are introduced by hand against that already-committed
repo, `git status --porcelain` is snapshotted, bin/typikon-init runs a SECOND
time — "re-running ... in an existing repository", the exact scenario the
issue names — and the snapshot is retaken.

Each fixture's status LINE must be byte-identical before/after, not merely
"the file still looks dirty in some form": the defect is a STATUS-CODE
change (an unstaged " M"/" D"/"??" flipping to a staged "M "/"D "/"A ", or an
"AM" collapsing to "A "), which `git add -A` produces without necessarily
touching file content at all — a content-only or existence-only check would
pass against the pre-fix script just as easily as the post-fix one. HEAD is
also asserted unmoved: even the pre-fix script does not commit on a refresh
(git log already non-empty), so an unmoved HEAD alone would not have caught
this defect — it is checked here only to guard the commit path specifically,
not as the fixture's proof.

`check_first_commit_excludes_pre_staged_file` — the FIRST-commit pathspec
guard. The re-run scenario above can never reach bin/typikon-init's
`git log --oneline` empty branch (the harness's own first `_run_init` call
already created a commit before any fixture exists), so it cannot exercise
whether the scaffold commit itself is pathspec-scoped. This scenario
constructs the one situation where that matters: a destination with an
already-initialized `.git` but ZERO commits, where the operator has already
`git add`ed a file of their own before typikon-init ever runs. A plain
`git commit` (no pathspec) commits the WHOLE index, sweeping that file into
typikon-init's own scaffold commit; `git commit -- "${COMMIT_PATHS[@]}"`
commits only the scaffold's own paths and leaves the operator's file staged,
untouched, and absent from HEAD.

NOTE: runs standalone (no examples/ site needed) as part of ci/run-fixtures.sh.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

THEME_ROOT = Path(__file__).resolve().parent.parent
INIT_SCRIPT = THEME_ROOT / "bin" / "typikon-init"

# WHY: passed through, never inherited wholesale — matches
# ci/check-init-favicon-path.py's isolation, for the same reason.
_PASSTHROUGH_KEYS = ("PATH", "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR")

FIXTURE_PATHS = (
    "content/about.md",
    "content/contact.md",
    "operator-staged.txt",
    "operator-scratch.txt",
)


def _isolated_env(isolated_home: Path) -> dict[str, str]:
    env = {key: os.environ[key] for key in _PASSTHROUGH_KEYS if key in os.environ}
    env["HOME"] = str(isolated_home)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_ALLOW_PROTOCOL"] = "file"
    env["TYPIKON_THEME_REPO"] = str(THEME_ROOT)
    env["TYPIKON_THEME_REPO_GH"] = str(THEME_ROOT)
    (isolated_home / ".gitconfig").write_text(
        "[user]\n\tname = Isolated Test\n\temail = isolated-test@example.invalid\n",
        encoding="utf-8",
    )
    return env


def _run_init(env: dict[str, str], dest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INIT_SCRIPT), "probe-site", str(dest)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _rev_parse_head(dest: Path, env: dict[str, str]) -> str:
    return subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    ).stdout.strip()


def _porcelain(dest: Path, env: dict[str, str]) -> dict[str, str]:
    """Map path -> its exact `git status --porcelain` 2-char status code."""
    result = subprocess.run(
        ["git", "-C", str(dest), "status", "--porcelain"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    codes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        # Porcelain v1 format: 2-char status code, one space, then the
        # path. None of this fixture set renames anything, so a fixed
        # split at index 3 is exact — no "old -> new" arrow to parse.
        codes[line[3:]] = line[:2]
    return codes


def check_rerun_preserves_unrelated_state() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="typikon-init-staging-home-") as home_tmp, \
         tempfile.TemporaryDirectory(prefix="typikon-init-staging-dest-") as dest_tmp:
        env = _isolated_env(Path(home_tmp))
        dest = Path(dest_tmp) / "probe-site"

        first = _run_init(env, dest)
        if first.returncode != 0:
            print(f"FAIL: initial bin/typikon-init exited {first.returncode}:\n{first.stderr}", file=sys.stderr)
            return 1
        head_before = _rev_parse_head(dest, env)

        # Introduce the four unrelated dirty-repository fixtures against
        # the already-scaffolded, already-committed repo.
        about_path = dest / "content" / "about.md"
        about_before = about_path.read_text(encoding="utf-8")
        about_dirty = about_before + "\nOperator's own unrelated edit.\n"
        about_path.write_text(about_dirty, encoding="utf-8")

        contact_path = dest / "content" / "contact.md"
        contact_path.unlink()

        staged_path = dest / "operator-staged.txt"
        staged_path.write_text("staged before re-run\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(dest), "add", "operator-staged.txt"], env=env, check=True,
        )
        # WHY a SECOND, unstaged edit on top of the staged content, not just
        # staged-and-left-alone: a file that is fully staged with nothing
        # further changed in the working tree has git-status code 'A ' both
        # BEFORE and AFTER a `git add -A` re-run, because `git add` is a
        # no-op on a path whose index content already matches the worktree.
        # That shape cannot discriminate the bug from the fix — repo-wide
        # `git add -A` and the fixed scoped add produce the identical
        # 'A ' -> 'A ' transition (verified: this was the shipped fixture,
        # and it was silent against a reverted, unscoped `git add -A`).
        # Layering a further unstaged edit yields 'AM': the scoped add never
        # touches this path (untouched -> stays 'AM'), while a repo-wide
        # `git add -A` stages the further edit too, collapsing it to 'A ' —
        # a status-code change the comparison below can actually catch.
        staged_dirty = "staged before re-run\nunstaged edit on top of the staged content\n"
        staged_path.write_text(staged_dirty, encoding="utf-8")

        scratch_path = dest / "operator-scratch.txt"
        scratch_path.write_text("untracked before re-run\n", encoding="utf-8")

        status_before = _porcelain(dest, env)
        missing = [p for p in FIXTURE_PATHS if p not in status_before]
        if missing:
            print(
                f"FAIL: fixture setup did not produce dirty status for {missing}: {status_before}",
                file=sys.stderr,
            )
            return 1

        # The re-run: "re-running typikon-init in an existing repository" —
        # the exact scenario forkwright/typikon#54 names.
        second = _run_init(env, dest)
        if second.returncode != 0:
            failures.append(f"re-run bin/typikon-init exited {second.returncode}:\n{second.stderr}")

        status_after = _porcelain(dest, env)
        for path in FIXTURE_PATHS:
            before = status_before.get(path)
            after = status_after.get(path)
            if before != after:
                failures.append(
                    f"{path}: git status changed from {before!r} to {after!r} across the "
                    "re-run (forkwright/typikon#54 — typikon-init must stage only its own "
                    "outputs, never a repository-wide sweep)"
                )

        head_after = _rev_parse_head(dest, env)
        if head_after != head_before:
            failures.append(
                f"HEAD moved from {head_before} to {head_after} across a refresh re-run — "
                "typikon-init must not create a commit that could sweep an operator's own "
                "staged file into it"
            )

        if about_path.read_text(encoding="utf-8") != about_dirty:
            failures.append("content/about.md's working-tree content changed across the re-run")
        if contact_path.exists():
            failures.append("content/contact.md was recreated by the re-run (it was deleted beforehand)")
        if staged_path.read_text(encoding="utf-8") != staged_dirty:
            failures.append(
                "operator-staged.txt's working-tree content changed across the re-run — its "
                "unstaged top edit must survive untouched, not just its status code"
            )

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(
        "OK: re-running bin/typikon-init against an existing, dirty repository leaves "
        "modified/deleted/staged/untracked unrelated files' git status exactly unchanged "
        "(forkwright/typikon#54)"
    )
    return 0


def check_first_commit_excludes_pre_staged_file() -> int:
    """Guard bin/typikon-init's pathspec-scoped FIRST commit specifically.

    Constructs the one scenario where `git commit -- "${COMMIT_PATHS[@]}"`
    (versus a plain `git commit`) actually matters: a destination whose
    `.git` already exists but carries zero commits, with a file the
    operator already `git add`ed before typikon-init ever ran. Neither
    `check_rerun_preserves_unrelated_state`'s first nor second
    `_run_init` call can reach this — its first call starts from no
    `.git` at all (so its own commit is the repo's first and nothing
    else is staged yet to sweep), and its second call runs against a
    repo whose `git log` is already non-empty, which takes
    bin/typikon-init's echo-only refresh branch and never calls
    `git commit` at all, scoped or not.
    """
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="typikon-init-firstcommit-home-") as home_tmp, \
         tempfile.TemporaryDirectory(prefix="typikon-init-firstcommit-dest-") as dest_tmp:
        env = _isolated_env(Path(home_tmp))
        dest = Path(dest_tmp) / "probe-site"
        dest.mkdir(parents=True)

        # An operator-initialized, commit-less repo — NOT typikon-init's own
        # `git init` branch (that only fires when `.git` is absent).
        subprocess.run(["git", "init", "-q", "-b", "main", str(dest)], env=env, check=True)
        pre_staged_path = dest / "operator-pre-staged.txt"
        pre_staged_path.write_text("operator content, staged before typikon-init ever ran\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(dest), "add", "--", "operator-pre-staged.txt"], env=env, check=True,
        )
        status_before = _porcelain(dest, env)
        if status_before.get("operator-pre-staged.txt") != "A ":
            print(
                f"FAIL: fixture setup did not stage operator-pre-staged.txt as expected: {status_before}",
                file=sys.stderr,
            )
            return 1

        result = _run_init(env, dest)
        if result.returncode != 0:
            print(f"FAIL: bin/typikon-init exited {result.returncode}:\n{result.stderr}", file=sys.stderr)
            return 1

        head = _rev_parse_head(dest, env)
        in_head = subprocess.run(
            ["git", "-C", str(dest), "cat-file", "-e", f"{head}:operator-pre-staged.txt"],
            capture_output=True,
            env=env,
            check=False,
        )
        if in_head.returncode == 0:
            failures.append(
                "operator-pre-staged.txt was committed into typikon-init's own scaffold commit — "
                "the scaffold commit must be pathspec-scoped to its own outputs "
                "(forkwright/typikon#54's second-order gap: a not-yet-committed destination with "
                "the operator's own pre-staged file must not have that file swept into typikon-init's commit)"
            )

        status_after = _porcelain(dest, env)
        after_code = status_after.get("operator-pre-staged.txt")
        if after_code != "A ":
            failures.append(
                f"operator-pre-staged.txt's status changed from 'A ' to {after_code!r} across "
                "typikon-init's first run — it must remain staged and untouched, only excluded "
                "from the scaffold commit itself"
            )

        own_output_probe = "content/about.md"
        own_in_head = subprocess.run(
            ["git", "-C", str(dest), "cat-file", "-e", f"{head}:{own_output_probe}"],
            capture_output=True,
            env=env,
            check=False,
        )
        if own_in_head.returncode != 0:
            failures.append(
                f"{own_output_probe} (typikon-init's own scaffold output) is absent from the "
                "scaffold commit — the pathspec scoping must include typikon-init's own "
                "OWN_OUTPUTS, not exclude everything"
            )

    if failures:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1

    print(
        "OK: bin/typikon-init's first scaffold commit is pathspec-scoped — an operator's own "
        "pre-staged file survives staged-but-uncommitted rather than being swept into the "
        "commit (forkwright/typikon#54)"
    )
    return 0


def main() -> int:
    return max(
        check_rerun_preserves_unrelated_state(),
        check_first_commit_excludes_pre_staged_file(),
    )


if __name__ == "__main__":
    sys.exit(main())
