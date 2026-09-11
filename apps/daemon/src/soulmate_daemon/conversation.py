"""Conversation application service and evidence extraction workflow."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from soulmate_core.context import ContextCompiler
from soulmate_core.domain import (
    Conversation,
    ConversationRepository,
    Evidence,
    EvidenceRepository,
    Message,
    MessageRepository,
    MessageRole,
    PersonalModelRepository,
    RawEvent,
    RawEventRepository,
)
from soulmate_core.preferences import ModelRebuilder
from soulmate_llm_providers import LLMMessage, LLMProvider, ProviderError

from soulmate_daemon.extraction import (
    EvidenceProposals,
    extraction_schema,
    review_proposals,
)

CHAT_SYSTEM_PROMPT = """You are Soulmate, a personal assistant.
Answer the owner directly and briefly. Use only relevant Personal Model context supplied below.
Do not claim unsupported personal facts."""
EXTRACTION_SYSTEM_PROMPT = """Extract only information explicitly stated by the user.
Use the supplied schema and stable dotted target keys. Preserve the user's meaning and return empty
lists when nothing is stated. Preference values range from -1 (strong dislike) to 1 (strong
preference). Do not infer sensitive claims."""


@dataclass(frozen=True, slots=True)
class ChatResult:
    conversation_id: str
    user_message_id: str
    assistant_message: Message
    accepted_evidence: tuple[Evidence, ...]
    rejected_evidence_count: int
    snapshot_version: int | None


class ConversationService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        raw_events: RawEventRepository,
        evidence: EvidenceRepository,
        models: PersonalModelRepository,
        provider: LLMProvider,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._raw_events = raw_events
        self._evidence = evidence
        self._models = models
        self._provider = provider

    async def chat(
        self, profile_id: str, content: str, conversation_id: str | None = None
    ) -> ChatResult:
        now = datetime.now(UTC)
        conversation = None
        if conversation_id is not None:
            conversation = self._conversations.get(conversation_id)
            if conversation is None or conversation.profile_id != profile_id:
                raise KeyError(conversation_id)
        resolved_id = conversation_id or f"conversation_{uuid4().hex}"
        user_message_id = f"message_{uuid4().hex}"
        context = ContextCompiler(self._models).compile(profile_id, content)
        history = () if conversation is None else self._messages.list_for_conversation(resolved_id)
        prompt = [
            LLMMessage(
                "system",
                f"{CHAT_SYSTEM_PROMPT}\nPersonal Model context: "
                f"{json.dumps(context.as_dict(), ensure_ascii=False, sort_keys=True)}",
            ),
            *(LLMMessage(item.role.value, item.content) for item in history[-20:]),
            LLMMessage("user", content),
        ]
        assistant_content = await self._provider.generate(prompt)
        if not assistant_content.strip():
            raise ProviderError("Model provider returned an empty response.")
        raw_proposals = await self._provider.generate_structured(
            [LLMMessage("system", EXTRACTION_SYSTEM_PROMPT), LLMMessage("user", content)],
            extraction_schema(),
        )
        proposals = EvidenceProposals.model_validate(raw_proposals)
        event = RawEvent(
            id=f"event_{uuid4().hex}",
            profile_id=profile_id,
            source_id=None,
            event_type="conversation_message",
            content={
                "conversation_id": resolved_id,
                "message_id": user_message_id,
                "content": content,
            },
            created_at=now,
            ingested_at=now,
        )
        reviewed = review_proposals(
            proposals,
            profile_id=profile_id,
            source_event_id=event.id,
            source_message_id=user_message_id,
            extractor_model=self._provider.model_name,
            created_at=now,
        )
        if conversation is None:
            self._conversations.add(Conversation(resolved_id, profile_id, now, now))
        user_message = Message(user_message_id, resolved_id, MessageRole.USER, content, now)
        assistant_created_at = now + timedelta(microseconds=1)
        assistant_message = Message(
            f"message_{uuid4().hex}",
            resolved_id,
            MessageRole.ASSISTANT,
            assistant_content,
            assistant_created_at,
            self._provider.model_name,
        )
        self._messages.add(user_message)
        self._raw_events.add(event)
        self._messages.add(assistant_message)
        for item in reviewed.accepted:
            self._evidence.add(item)
        self._conversations.touch(resolved_id, assistant_created_at)
        snapshot_version = None
        if reviewed.accepted:
            snapshot = ModelRebuilder(self._evidence, self._models).rebuild(profile_id, now)
            snapshot_version = snapshot.version
        return ChatResult(
            resolved_id,
            user_message_id,
            assistant_message,
            reviewed.accepted,
            reviewed.rejected_count,
            snapshot_version,
        )
