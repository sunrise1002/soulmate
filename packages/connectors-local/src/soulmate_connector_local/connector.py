"""Bounded, offline synchronization of UTF-8 text and Markdown files."""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from soulmate_connector_sdk import (
    ConnectorContext,
    ConnectorEvent,
    ConnectorManifest,
    ConnectorPermission,
    ConnectorSyncRequest,
    ConnectorSyncResult,
)

MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_FILES = 1_000
SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


class LocalNotesConnector:
    """Read an explicitly selected local directory without network access."""

    manifest = ConnectorManifest(
        connector_id="soulmate.local-notes",
        name="Local Notes",
        version="1.0.0",
        description="Import UTF-8 Markdown and text notes from an owner-selected directory.",
        permissions=(
            ConnectorPermission.DATA_READ,
            ConnectorPermission.LEARNING_INGEST,
        ),
        data_access=("UTF-8 .md, .markdown, and .txt files below the configured path",),
    )

    async def sync(
        self, request: ConnectorSyncRequest, context: ConnectorContext
    ) -> ConnectorSyncResult:
        del context
        configured_path = request.configuration.get("path")
        if not isinstance(configured_path, str) or not configured_path.strip():
            raise ValueError("Local Notes requires a non-empty 'path' setting.")
        return await asyncio.to_thread(self._read, Path(configured_path))

    def _read(self, configured_path: Path) -> ConnectorSyncResult:
        root = configured_path.expanduser().resolve()
        if not root.is_dir():
            raise ValueError("The configured Local Notes path is not a directory.")
        files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.lower() in SUPPORTED_SUFFIXES
        )
        if len(files) > MAX_FILES:
            raise ValueError("Local Notes supports at most 1,000 files per sync.")
        total_bytes = 0
        events: list[ConnectorEvent] = []
        for path in files:
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("A note resolved outside the configured directory.") from exc
            stat = resolved.stat()
            if stat.st_size > MAX_FILE_BYTES:
                raise ValueError("Each Local Notes file must not exceed 1 MiB.")
            total_bytes += stat.st_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("Local Notes supports at most 20 MiB per sync.")
            try:
                content = resolved.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Local Notes accepts only UTF-8 files.") from exc
            digest = hashlib.sha256(content.encode()).hexdigest()
            relative_name = relative.as_posix()
            events.append(
                ConnectorEvent(
                    external_id=f"{relative_name}:{digest}",
                    event_type="connector_note_document",
                    content={
                        "path": relative_name,
                        "content": content,
                        "sha256": digest,
                    },
                    created_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                    sensitivity="sensitive",
                )
            )
        return ConnectorSyncResult(
            events=tuple(events),
            cursor={"file_count": len(events), "content_bytes": total_bytes},
        )
