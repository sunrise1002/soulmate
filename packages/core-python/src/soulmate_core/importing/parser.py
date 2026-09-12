"""Normalize static chat exports without provider SDKs or network access."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from soulmate_core.domain import MessageRole

MAX_IMPORT_MESSAGES = 100_000
SPEAKER_LINE = re.compile(
    r"^(?:#{1,6}\s*)?(?P<speaker>user|human|assistant|ai|chatgpt|claude)\s*:\s*(?P<text>.*)$",
    re.IGNORECASE,
)


class ImportFormat(StrEnum):
    AUTO = "auto"
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"
    CHATGPT = "chatgpt"
    CLAUDE = "claude"


@dataclass(frozen=True, slots=True)
class ImportedMessage:
    role: MessageRole
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ImportedConversation:
    messages: tuple[ImportedMessage, ...]


@dataclass(frozen=True, slots=True)
class ParsedChatImport:
    detected_format: ImportFormat
    conversations: tuple[ImportedConversation, ...]

    @property
    def message_count(self) -> int:
        return sum(len(item.messages) for item in self.conversations)


def _timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except (OverflowError, OSError, ValueError):
            return fallback
    if isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return fallback
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return fallback


def _role(value: object) -> MessageRole | None:
    if not isinstance(value, str):
        return None
    normalized = value.casefold()
    if normalized in {"user", "human"}:
        return MessageRole.USER
    if normalized in {"assistant", "ai", "chatgpt", "claude"}:
        return MessageRole.ASSISTANT
    return None


def _content(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts: list[str] = []
        for item in cast(list[object], value):
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        joined = "\n".join(parts).strip()
        return joined or None
    if isinstance(value, dict):
        for key in ("text", "content", "parts"):
            content = _content(value.get(key))
            if content is not None:
                return content
    return None


def _generic_messages(value: object, imported_at: datetime) -> tuple[ImportedMessage, ...]:
    if not isinstance(value, list):
        raise ValueError("JSON conversations must contain a messages array.")
    messages: list[ImportedMessage] = []
    for index, item in enumerate(cast(list[object], value)):
        if not isinstance(item, dict):
            continue
        role = _role(item.get("role") or item.get("sender") or item.get("author"))
        content = _content(item.get("content") or item.get("text") or item.get("message"))
        if role is None or content is None:
            continue
        created_at = _timestamp(
            item.get("created_at") or item.get("create_time") or item.get("timestamp"),
            imported_at + timedelta(microseconds=index),
        )
        messages.append(ImportedMessage(role, content, created_at))
    return tuple(messages)


def _parse_generic_json(value: object, imported_at: datetime) -> tuple[ImportedConversation, ...]:
    if isinstance(value, dict):
        messages = _generic_messages(value.get("messages"), imported_at)
        return (ImportedConversation(messages),) if messages else ()
    if not isinstance(value, list):
        raise ValueError("Chat JSON must be an object or array.")
    items = cast(list[object], value)
    if all(isinstance(item, dict) and "role" in item for item in items):
        messages = _generic_messages(items, imported_at)
        return (ImportedConversation(messages),) if messages else ()
    conversations: list[ImportedConversation] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict) or "messages" not in item:
            continue
        messages = _generic_messages(item["messages"], imported_at + timedelta(seconds=index))
        if messages:
            conversations.append(ImportedConversation(messages))
    return tuple(conversations)


def _parse_chatgpt(value: object, imported_at: datetime) -> tuple[ImportedConversation, ...]:
    if not isinstance(value, list):
        raise ValueError("ChatGPT export must be a conversations array.")
    conversations: list[ImportedConversation] = []
    for conversation_index, conversation in enumerate(cast(list[object], value)):
        if not isinstance(conversation, dict) or not isinstance(conversation.get("mapping"), dict):
            continue
        messages: list[ImportedMessage] = []
        mapping = cast(dict[object, object], conversation["mapping"])
        for node_index, node in enumerate(mapping.values()):
            if not isinstance(node, dict) or not isinstance(node.get("message"), dict):
                continue
            message = cast(dict[object, object], node["message"])
            author = message.get("author")
            role = _role(author.get("role") if isinstance(author, dict) else None)
            content = _content(message.get("content"))
            if role is None or content is None:
                continue
            fallback = imported_at + timedelta(seconds=conversation_index, microseconds=node_index)
            messages.append(
                ImportedMessage(role, content, _timestamp(message.get("create_time"), fallback))
            )
        messages.sort(key=lambda item: item.created_at)
        if messages:
            conversations.append(ImportedConversation(tuple(messages)))
    return tuple(conversations)


def _parse_claude(value: object, imported_at: datetime) -> tuple[ImportedConversation, ...]:
    if not isinstance(value, list):
        raise ValueError("Claude export must be a conversations array.")
    conversations: list[ImportedConversation] = []
    for index, conversation in enumerate(cast(list[object], value)):
        if not isinstance(conversation, dict) or "chat_messages" not in conversation:
            continue
        messages = _generic_messages(
            conversation["chat_messages"], imported_at + timedelta(seconds=index)
        )
        if messages:
            conversations.append(ImportedConversation(messages))
    return tuple(conversations)


def _parse_text(content: str, imported_at: datetime) -> tuple[ImportedConversation, ...]:
    messages: list[ImportedMessage] = []
    role: MessageRole | None = None
    lines: list[str] = []

    def append_message() -> None:
        nonlocal lines
        text = "\n".join(lines).strip()
        if role is not None and text:
            messages.append(
                ImportedMessage(role, text, imported_at + timedelta(microseconds=len(messages)))
            )
        lines = []

    for line in content.splitlines():
        match = SPEAKER_LINE.match(line.strip())
        if match is None:
            lines.append(line)
            continue
        append_message()
        role = _role(match.group("speaker"))
        lines.append(match.group("text"))
    append_message()
    if not messages and content.strip():
        messages.append(ImportedMessage(MessageRole.USER, content.strip(), imported_at))
    return (ImportedConversation(tuple(messages)),) if messages else ()


def _detect_json_format(value: object) -> ImportFormat:
    if isinstance(value, list) and any(
        isinstance(item, dict) and "mapping" in item for item in cast(list[object], value)
    ):
        return ImportFormat.CHATGPT
    if isinstance(value, list) and any(
        isinstance(item, dict) and "chat_messages" in item for item in cast(list[object], value)
    ):
        return ImportFormat.CLAUDE
    return ImportFormat.JSON


def parse_chat_import(
    content: str,
    import_format: ImportFormat = ImportFormat.AUTO,
    *,
    imported_at: datetime | None = None,
) -> ParsedChatImport:
    """Parse generic or common assistant exports into a bounded neutral form."""
    if not content.strip():
        raise ValueError("Import content must not be empty.")
    now = imported_at if imported_at is not None else datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Import time must be timezone-aware.")
    selected = import_format
    decoded: object | None = None
    json_formats = {
        ImportFormat.AUTO,
        ImportFormat.JSON,
        ImportFormat.CHATGPT,
        ImportFormat.CLAUDE,
    }
    if selected in json_formats:
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as exc:
            if selected is not ImportFormat.AUTO:
                raise ValueError("Import content is not valid JSON.") from exc
        else:
            if selected is ImportFormat.AUTO:
                selected = _detect_json_format(decoded)
    if selected is ImportFormat.AUTO:
        selected = (
            ImportFormat.MARKDOWN
            if re.search(r"^#{1,6}\s", content, re.MULTILINE)
            else ImportFormat.TEXT
        )
    if selected is ImportFormat.CHATGPT:
        conversations = _parse_chatgpt(decoded, now)
    elif selected is ImportFormat.CLAUDE:
        conversations = _parse_claude(decoded, now)
    elif selected is ImportFormat.JSON:
        conversations = _parse_generic_json(decoded, now)
    else:
        conversations = _parse_text(content, now)
    result = ParsedChatImport(selected, conversations)
    if result.message_count == 0:
        raise ValueError("Import did not contain any supported user or assistant messages.")
    if result.message_count > MAX_IMPORT_MESSAGES:
        raise ValueError(f"Import exceeds the {MAX_IMPORT_MESSAGES} message limit.")
    return result
