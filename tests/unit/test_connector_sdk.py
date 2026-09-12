"""Exercise connector declarations, output validation, and local reference behavior."""

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from soulmate_connector_local import LocalNotesConnector
from soulmate_connector_sdk import (
    ConnectorContext,
    ConnectorEvent,
    ConnectorManifest,
    ConnectorPermission,
    ConnectorSyncRequest,
    ConnectorSyncResult,
    NetworkResponse,
)
from soulmate_daemon.cli import _list_connectors


class UnusedNetwork:
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> NetworkResponse:
        del method, url, headers, body
        raise AssertionError("The Local Notes connector must remain offline.")


def test_manifest_requires_exact_capability_permissions() -> None:
    with pytest.raises(ValueError, match="exactly match"):
        ConnectorManifest(
            connector_id="example.remote",
            name="Remote example",
            version="1.0.0",
            description="Synthetic remote connector.",
            permissions=(
                ConnectorPermission.DATA_READ,
                ConnectorPermission.LEARNING_INGEST,
            ),
            data_access=("Synthetic records",),
            network_hosts=("example.test",),
        )


def test_events_require_utc_and_bounded_json() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ConnectorEvent("item", "synthetic", {}, datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="2 MiB"):
        ConnectorEvent(
            "item",
            "synthetic",
            {"content": "x" * (2 * 1024 * 1024)},
            datetime(2026, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="JSON serializable"):
        ConnectorEvent(
            "item",
            "synthetic",
            {"invalid": object()},
            datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_sync_output_bounds_batch_and_cursor() -> None:
    event = ConnectorEvent(
        "item",
        "synthetic",
        {},
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="10,000"):
        ConnectorSyncResult((event,) * 10_001, None)
    with pytest.raises(ValueError, match="64 KiB"):
        ConnectorSyncResult((), {"cursor": "x" * (64 * 1024)})


def test_local_notes_emits_stable_sensitive_events_without_following_symlinks(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "plan.md").write_text("# Synthetic plan", encoding="utf-8")
    (notes / "ignored.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (notes / "link.txt").symlink_to(outside)
    connector = LocalNotesConnector()
    context = ConnectorContext(credentials={}, network=UnusedNetwork())

    first = asyncio.run(connector.sync(ConnectorSyncRequest({"path": str(notes)}, None), context))
    second = asyncio.run(
        connector.sync(ConnectorSyncRequest({"path": str(notes)}, first.cursor), context)
    )

    assert first == second
    assert len(first.events) == 1
    assert first.events[0].content["path"] == "plan.md"
    assert first.events[0].content["content"] == "# Synthetic plan"
    assert first.events[0].sensitivity == "sensitive"


def test_local_notes_rejects_missing_and_oversized_input(tmp_path: Path) -> None:
    connector = LocalNotesConnector()
    context = ConnectorContext(credentials={}, network=UnusedNetwork())
    with pytest.raises(ValueError, match="path"):
        asyncio.run(connector.sync(ConnectorSyncRequest({}, None), context))
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "large.txt").write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
    with pytest.raises(ValueError, match="1 MiB"):
        asyncio.run(connector.sync(ConnectorSyncRequest({"path": str(notes)}, None), context))

    invalid_notes = tmp_path / "invalid-notes"
    invalid_notes.mkdir()
    (invalid_notes / "invalid.txt").write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="UTF-8"):
        asyncio.run(
            connector.sync(ConnectorSyncRequest({"path": str(invalid_notes)}, None), context)
        )


def test_connector_cli_lists_installed_entry_points(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _list_connectors() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["load_failures"] == []
    assert payload["connectors"][0]["connector_id"] == "soulmate.local-notes"
