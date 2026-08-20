#!/usr/bin/env python3
"""Causal fixture for the consumer receipt's PR-merge and gitlink binding."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "ci" / "write-consumer-receipt.py"
LOADER = importlib.machinery.SourceFileLoader("write_consumer_receipt", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
receipt = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(receipt)


def run(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def commit(root: Path, message: str) -> str:
    run(root, "add", "-A")
    run(root, "-c", "user.name=fixture", "-c", "user.email=fixture@example.test", "commit", "-m", message)
    return run(root, "rev-parse", "HEAD")


@contextmanager
def environment(values: dict[str, str]):
    before = os.environ.copy()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


def expect_failure(root: Path, fragment: str) -> None:
    try:
        receipt.build(root)
    except receipt.ReceiptError as exc:
        if fragment not in str(exc):
            raise AssertionError(f"expected {fragment!r}, got {exc!r}") from exc
    else:
        raise AssertionError(f"receipt unexpectedly accepted mutant: {fragment}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="typikon-consumer-receipt-") as tmp:
        scratch = Path(tmp)
        theme = scratch / "typikon"
        theme.mkdir()
        run(theme, "init", "-q", "-b", "main")
        (theme / "theme.toml").write_text('name = "fixture"\n', encoding="utf-8")
        theme_commit = commit(theme, "theme")

        consumer = scratch / "consumer"
        consumer.mkdir()
        run(consumer, "init", "-q", "-b", "main")
        (consumer / ".github" / "workflows").mkdir(parents=True)
        (consumer / ".github" / "workflows" / "deploy.yml").write_text(
            "name: fixture\n", encoding="utf-8"
        )
        run(
            consumer,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(theme),
            "themes/typikon",
        )
        base = commit(consumer, "base")
        run(consumer, "checkout", "-q", "-b", "feature")
        (consumer / "feature.txt").write_text("candidate\n", encoding="utf-8")
        head = commit(consumer, "candidate")
        run(consumer, "checkout", "-q", "main")
        run(
            consumer,
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.test",
            "merge",
            "--no-ff",
            "feature",
            "-m",
            "synthetic merge",
        )
        merge = run(consumer, "rev-parse", "HEAD")
        event = scratch / "event.json"
        event.write_text(
            json.dumps(
                {
                    "pull_request": {
                        "number": 37,
                        "base": {"sha": base},
                        "head": {"sha": head},
                    }
                }
            ),
            encoding="utf-8",
        )
        env = {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REPOSITORY": "forkwright/ardent-site",
            "GITHUB_EVENT_PATH": str(event),
            "GITHUB_WORKFLOW_REF": "forkwright/ardent-site/.github/workflows/deploy.yml@refs/pull/37/merge",
            "GITHUB_SHA": merge,
            "GITHUB_WORKFLOW_SHA": merge,
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "2",
        }
        with environment(env):
            value = receipt.build(consumer)
            assert value["consumer"]["checkout_commit"] == merge
            assert value["consumer"]["checkout_parents"] == [base, head]
            assert value["typikon"]["commit"] == theme_commit

            run(consumer, "checkout", "-q", "feature")
            os.environ["GITHUB_SHA"] = head
            expect_failure(consumer, "synthetic merge")
            run(consumer, "checkout", "-q", merge)
            os.environ["GITHUB_SHA"] = merge

            os.environ["GITHUB_SHA"] = head
            expect_failure(consumer, "differs from GITHUB_SHA")
            os.environ["GITHUB_SHA"] = merge

            (theme / "second.txt").write_text("drift\n", encoding="utf-8")
            second = commit(theme, "second")
            run(consumer / "themes" / "typikon", "fetch", "-q", str(theme), second)
            run(consumer / "themes" / "typikon", "checkout", "-q", second)
            expect_failure(consumer, "differs from the consumer gitlink")
            run(consumer / "themes" / "typikon", "checkout", "-q", theme_commit)

            os.environ["GITHUB_EVENT_NAME"] = "push"
            expect_failure(consumer, "only for pull_request")
            os.environ["GITHUB_EVENT_NAME"] = "pull_request"

            os.environ["GITHUB_WORKFLOW_SHA"] = base
            expect_failure(consumer, "differs from the pull request synthetic merge")
            os.environ["GITHUB_WORKFLOW_SHA"] = merge

            os.environ["GITHUB_WORKFLOW_REF"] = "forkwright/other/.github/workflows/deploy.yml@main"
            expect_failure(consumer, "does not name this repository")

    print("check-consumer-receipt: ok (merge, gitlink, and event mutants rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
