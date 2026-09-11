"""Keep tests independent of the developer's personal configuration."""

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in os.environ:
        if name.startswith("SOULMATE_") or name == "DATA_DIR":
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
