from pathlib import Path

import pytest

from scripts.validate_contribution import (
    PolicyError,
    read_commit_message,
    validate_branch_name,
    validate_commit_message,
    validate_header,
)


@pytest.mark.parametrize(
    "header",
    [
        "feat: add preference import",
        "fix(api): reject invalid profile",
        "refactor(core)!: remove legacy port",
    ],
)
def test_conventional_headers_are_accepted(header: str) -> None:
    validate_header(header, label="Test header")


@pytest.mark.parametrize(
    "header",
    [
        "Add preference import",
        "feature: add preference import",
        "feat: Add preference import",
        "feat: add preference import.",
        f"feat: {'a' * 95}",
    ],
)
def test_nonconforming_headers_are_rejected(header: str) -> None:
    with pytest.raises(PolicyError):
        validate_header(header, label="Test header")


def test_commit_body_requires_a_blank_separator() -> None:
    with pytest.raises(PolicyError, match="blank line"):
        validate_commit_message("fix: handle empty input\nBody without separator")


@pytest.mark.parametrize(
    "branch_name",
    ["main", "feat/model-summary", "docs/contributor_guide", "dependabot/pip/ruff-1.0"],
)
def test_supported_branch_names_are_accepted(branch_name: str) -> None:
    validate_branch_name(branch_name)


@pytest.mark.parametrize("branch_name", ["feature/model", "feat/Model", "feat/model/topic"])
def test_unsupported_branch_names_are_rejected(branch_name: str) -> None:
    with pytest.raises(PolicyError):
        validate_branch_name(branch_name)


def test_commit_message_file_is_read_as_utf8(tmp_path: Path) -> None:
    message_path = tmp_path / "COMMIT_EDITMSG"
    message_path.write_text("docs: clarify privacy policy\n", encoding="utf-8")

    assert read_commit_message(message_path) == "docs: clarify privacy policy\n"
