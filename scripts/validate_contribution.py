"""Validate contribution metadata shared by local hooks and CI."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_BRANCHES = frozenset({"main"})
BRANCH_PATTERN = re.compile(
    r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|release|revert|test)/"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*$"
)
AUTOMATION_BRANCH_PATTERN = re.compile(r"^(?:dependabot|renovate)/.+$")
CONVENTIONAL_HEADER_PATTERN = re.compile(
    r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?:\([a-z0-9][a-z0-9._/-]*\))?!?: [a-z0-9].+$"
)
MAX_HEADER_LENGTH = 100
REVISION_RANGE_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}\.\.[0-9a-fA-F]{7,64}$")


class PolicyError(ValueError):
    """Raised when contribution metadata does not follow repository policy."""


def validate_header(header: str, *, label: str) -> None:
    """Validate a Conventional Commits header or pull-request title."""
    if len(header) > MAX_HEADER_LENGTH:
        raise PolicyError(
            f"{label} must be at most {MAX_HEADER_LENGTH} characters; got {len(header)}."
        )
    if not CONVENTIONAL_HEADER_PATTERN.fullmatch(header):
        raise PolicyError(
            f"{label} must follow '<type>(<scope>): <lowercase summary>'; "
            "allowed types: build, chore, ci, docs, feat, fix, perf, refactor, "
            "revert, style, test."
        )
    if header.endswith("."):
        raise PolicyError(f"{label} must not end with a period.")


def validate_commit_message(message: str) -> None:
    """Validate a complete commit message."""
    lines = message.rstrip().splitlines()
    if not lines:
        raise PolicyError("Commit message must not be empty.")
    validate_header(lines[0], label="Commit header")
    if len(lines) > 1 and lines[1].strip():
        raise PolicyError("Commit body must be separated from the header by a blank line.")


def validate_branch_name(branch_name: str) -> None:
    """Validate a local or pull-request branch name."""
    if branch_name in ALLOWED_BRANCHES:
        return
    if BRANCH_PATTERN.fullmatch(branch_name):
        return
    if AUTOMATION_BRANCH_PATTERN.fullmatch(branch_name):
        return
    raise PolicyError(
        "Branch name must be 'main', an automation branch, or follow "
        "'<type>/<kebab-case-topic>' with an allowed workflow type."
    )


def read_commit_message(path: Path) -> str:
    """Read the commit message supplied by Git."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"Cannot read commit message file '{path}': {exc}") from exc


def current_branch() -> str | None:
    """Return the current branch, or None for a detached HEAD."""
    result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],  # noqa: S607 - trusted tool.
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = result.stderr.strip() or "git symbolic-ref failed"
        raise PolicyError(f"Cannot determine current branch: {detail}")
    return result.stdout.strip()


def commit_messages_in_range(revision_range: str) -> list[str]:
    """Return commit messages in a Git revision range."""
    if not REVISION_RANGE_PATTERN.fullmatch(revision_range):
        raise PolicyError("Commit range must contain two full or abbreviated commit hashes.")
    result = subprocess.run(  # noqa: S603 - validated revision is passed without a shell.
        ["git", "log", "--format=%B%x00", revision_range],  # noqa: S607 - trusted tool.
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "git log failed"
        raise PolicyError(f"Cannot inspect commit range '{revision_range}': {detail}")
    return [message.strip() for message in result.stdout.split("\0") if message.strip()]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    commit_message = subparsers.add_parser("commit-message")
    commit_message.add_argument("path", type=Path)

    branch_name = subparsers.add_parser("branch-name")
    branch_name.add_argument("name", nargs="?")

    pull_request_title = subparsers.add_parser("pr-title")
    pull_request_title.add_argument("title")

    commit_range = subparsers.add_parser("commit-range")
    commit_range.add_argument("revision_range")

    return parser


def run(argv: list[str] | None = None) -> int:
    """Run the requested policy check."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "commit-message":
            validate_commit_message(read_commit_message(args.path))
        elif args.command == "branch-name":
            branch = args.name or current_branch()
            if branch is not None:
                validate_branch_name(branch)
        elif args.command == "pr-title":
            validate_header(args.title, label="Pull-request title")
        elif args.command == "commit-range":
            messages = commit_messages_in_range(args.revision_range)
            if not messages:
                raise PolicyError(f"Commit range '{args.revision_range}' is empty.")
            for message in messages:
                validate_commit_message(message)
    except PolicyError as exc:
        print(f"Contribution policy failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
