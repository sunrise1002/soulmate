"""Static chat import application service with source provenance."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from soulmate_core.domain import (
    Conversation,
    Message,
    RawEvent,
    Source,
    SourceDeletion,
    SourceRepository,
)
from soulmate_core.importing import ImportFormat, parse_chat_import


@dataclass(frozen=True, slots=True)
class ImportResult:
    source: Source
    detected_format: ImportFormat
    conversation_count: int
    message_count: int


class ChatImportService:
    """Normalize and atomically persist a bounded static chat history."""

    def __init__(self, sources: SourceRepository) -> None:
        self._sources = sources

    def import_content(
        self,
        profile_id: str,
        name: str,
        content: str,
        import_format: ImportFormat,
        now: datetime | None = None,
    ) -> ImportResult:
        imported_at = now if now is not None else datetime.now(UTC)
        parsed = parse_chat_import(content, import_format, imported_at=imported_at)
        source = Source(
            id=f"source_{uuid4().hex}",
            profile_id=profile_id,
            source_type=f"import:{parsed.detected_format.value}",
            name=name.strip(),
            created_at=imported_at,
        )
        conversations: list[Conversation] = []
        messages: list[Message] = []
        events: list[RawEvent] = []
        for parsed_conversation in parsed.conversations:
            conversation_id = f"conversation_{uuid4().hex}"
            conversation_messages: list[Message] = []
            for parsed_message in parsed_conversation.messages:
                message_id = f"message_{uuid4().hex}"
                message = Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role=parsed_message.role,
                    content=parsed_message.content,
                    created_at=parsed_message.created_at,
                )
                conversation_messages.append(message)
                events.append(
                    RawEvent(
                        id=f"event_{uuid4().hex}",
                        profile_id=profile_id,
                        source_id=source.id,
                        event_type="imported_chat_message",
                        content={
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "role": parsed_message.role.value,
                            "content": parsed_message.content,
                        },
                        created_at=parsed_message.created_at,
                        ingested_at=imported_at,
                    )
                )
            created_at = min(item.created_at for item in conversation_messages)
            updated_at = max(item.created_at for item in conversation_messages)
            conversations.append(
                Conversation(
                    conversation_id,
                    profile_id,
                    created_at,
                    updated_at,
                    source.id,
                )
            )
            messages.extend(conversation_messages)
        self._sources.add_import(source, tuple(conversations), tuple(messages), tuple(events))
        return ImportResult(
            source=source,
            detected_format=parsed.detected_format,
            conversation_count=len(conversations),
            message_count=len(messages),
        )

    def delete_import(self, profile_id: str, source_id: str) -> SourceDeletion | None:
        return self._sources.remove_import(profile_id, source_id)
