"""Test the offline evaluation command."""

import json

import pytest
from soulmate_daemon.cli import _evaluate


def test_evaluate_command_emits_machine_readable_metrics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _evaluate(None) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["evaluated"] is True
    assert result["dataset_version"] == "synthetic-owner-v1"
    assert result["metrics"]["decision_model"]["sample_count"] == 12
