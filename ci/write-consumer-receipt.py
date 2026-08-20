#!/usr/bin/env python3
"""Write a deterministic receipt for a consumer's hosted PR checkout."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


class ReceiptError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ReceiptError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ReceiptError(f"{name} is required")
    return value


def workflow_path(workflow_ref: str, repository: str) -> str:
    prefix = f"{repository}/"
    if not workflow_ref.startswith(prefix) or "@" not in workflow_ref:
        raise ReceiptError("GITHUB_WORKFLOW_REF does not name this repository")
    path = workflow_ref[len(prefix) :].rsplit("@", 1)[0]
    if not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml")):
        raise ReceiptError(f"invalid workflow path {path!r}")
    return path


def build(root: Path) -> dict[str, object]:
    if required_env("GITHUB_EVENT_NAME") != "pull_request":
        raise ReceiptError("consumer receipts are created only for pull_request runs")
    repository = required_env("GITHUB_REPOSITORY")
    event_path = Path(required_env("GITHUB_EVENT_PATH"))
    event = json.loads(event_path.read_text(encoding="utf-8"))
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        raise ReceiptError("event has no pull_request object")

    checkout_commit = git(root, "rev-parse", "HEAD")
    checkout_tree = git(root, "rev-parse", "HEAD^{tree}")
    if checkout_commit != required_env("GITHUB_SHA"):
        raise ReceiptError("checked-out commit differs from GITHUB_SHA")
    parents = git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    expected_parents = [pr["base"]["sha"], pr["head"]["sha"]]
    if parents != expected_parents:
        raise ReceiptError(
            "checkout is not the pull request synthetic merge: "
            f"parents={parents}, expected={expected_parents}"
        )
    gitlink_fields = git(root, "ls-tree", "HEAD", "themes/typikon").split()
    if len(gitlink_fields) < 3 or gitlink_fields[0] != "160000" or gitlink_fields[1] != "commit":
        raise ReceiptError("themes/typikon is not a gitlink in the checked-out tree")
    gitlink_commit = gitlink_fields[2]
    submodule_commit = git(root / "themes" / "typikon", "rev-parse", "HEAD")
    if submodule_commit != gitlink_commit:
        raise ReceiptError("checked-out Typikon commit differs from the consumer gitlink")
    gitlink_tree = git(root / "themes" / "typikon", "rev-parse", "HEAD^{tree}")

    path = workflow_path(required_env("GITHUB_WORKFLOW_REF"), repository)
    workflow_commit = required_env("GITHUB_WORKFLOW_SHA")
    if not SHA.fullmatch(workflow_commit):
        raise ReceiptError("GITHUB_WORKFLOW_SHA is not a commit object id")
    if workflow_commit != checkout_commit:
        raise ReceiptError(
            "GITHUB_WORKFLOW_SHA differs from the pull request synthetic merge"
        )
    receipt = {
        "schema_version": 1,
        "consumer": {
            "repository": repository,
            "pull_request": int(pr["number"]),
            "base_commit": pr["base"]["sha"],
            "head_commit": pr["head"]["sha"],
            "checkout_commit": checkout_commit,
            "checkout_tree": checkout_tree,
            "checkout_parents": parents,
        },
        "typikon": {
            "path": "themes/typikon",
            "mode": "160000",
            "commit": gitlink_commit,
            "tree": gitlink_tree,
        },
        "workflow": {
            "path": path,
            "commit": workflow_commit,
            "blob": git(root, "rev-parse", f"{workflow_commit}:{path}"),
            "run_id": int(required_env("GITHUB_RUN_ID")),
            "run_attempt": int(required_env("GITHUB_RUN_ATTEMPT")),
            "event": "pull_request",
        },
    }
    for value in (
        receipt["consumer"]["base_commit"],
        receipt["consumer"]["head_commit"],
        checkout_commit,
        checkout_tree,
        gitlink_commit,
        gitlink_tree,
        receipt["workflow"]["blob"],
        workflow_commit,
    ):
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise ReceiptError(f"receipt contains an invalid object id: {value!r}")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build(args.root.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (ReceiptError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"write-consumer-receipt: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
