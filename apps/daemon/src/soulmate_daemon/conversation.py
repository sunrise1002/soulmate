"""Conversation application service and evidence extraction workflow."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from soulmate_core.context import ContextCompiler, select_known_keys
from soulmate_core.decision_io import OWNER_LOCAL_EVENT
from soulmate_core.domain import (
    Conversation,
    ConversationRepository,
    Evidence,
    EvidenceRepository,
    Job,
    JobRepository,
    JobStatus,
    Message,
    MessageRepository,
    MessageRole,
    PersonalModelRepository,
    RawEvent,
    RawEventRepository,
    TargetKeyAliasRepository,
    TargetKeyCatalogRepository,
)
from soulmate_core.preferences import ModelRebuilder
from soulmate_llm_providers import LLMMessage, LLMProvider, ProviderError

from soulmate_daemon.extraction import (
    KEY_LABEL_RULES,
    KEY_REUSE_RULES,
    ReviewedEvidence,
    extraction_schema,
    review_proposals,
    validate_proposals,
)
from soulmate_daemon.key_aliases import register_normalized_aliases
from soulmate_daemon.key_semantics import KeySemanticsService

CONVERSATION_EXTRACTION_JOB = "conversation_evidence_extract"
EXTRACTION_INITIAL_DELAY = timedelta(seconds=1)
# With the worker's doubling 30 s backoff capped at 15 min, eight attempts ride
# out roughly 45 minutes of provider overload before learning gives up.
EXTRACTION_MAX_ATTEMPTS = 8
EXTRACTION_RETRY_DELAY = timedelta(seconds=30)
RECENT_USER_TURNS = 2

CHAT_SYSTEM_PROMPT = """You are Soulmate, a personal assistant.
Answer the owner directly and briefly. Use only relevant Personal Model context supplied below.
Do not claim unsupported personal facts."""
EXTRACTION_SYSTEM_PROMPT = f"""Extract only information explicitly stated by the user.
Use the supplied schema and stable dotted English target keys. Preserve the user's meaning and
return empty lists when nothing is stated. Preference values range from -1 (strong dislike) to 1
(strong preference). Do not infer sensitive claims.
{KEY_REUSE_RULES}
{KEY_LABEL_RULES}"""


def extraction_job_id(message_id: str) -> str:
    """Return the durable job identity that learns from one user message."""
    return f"job_extract_{message_id}"


@dataclass(frozen=True, slots=True)
class ChatResult:
    conversation_id: str
    user_message_id: str
    assistant_message: Message
    accepted_evidence: tuple[Evidence, ...]
    rejected_evidence_count: int
    snapshot_version: int | None
    learning_status: Literal["learned", "no_evidence", "pending"]
    learning_error: str | None


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
        jobs: JobRepository | None = None,
        aliases: TargetKeyAliasRepository | None,
        catalog: TargetKeyCatalogRepository | None = None,
        semantics: KeySemanticsService | None = None,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._raw_events = raw_events
        self._evidence = evidence
        self._models = models
        self._provider = provider
        self._jobs = jobs
        self._aliases = aliases
        self._catalog = catalog
        self._semantics = semantics
        self._rebuilder = ModelRebuilder(evidence, models, aliases)

    async def _extract(
        self,
        profile_id: str,
        content: str,
        source_event_id: str,
        source_message_id: str,
        created_at: datetime,
    ) -> ReviewedEvidence:
        known_keys = json.dumps(
            self._known_keys(profile_id, content, source_message_id), ensure_ascii=False
        )
        system_prompt = f"{EXTRACTION_SYSTEM_PROMPT}\n\nKnown keys by type: {known_keys}"
        raw_proposals = await self._provider.generate_structured(
            [LLMMessage("system", system_prompt), LLMMessage("user", content)],
            extraction_schema(),
        )
        proposals = validate_proposals(raw_proposals)
        return review_proposals(
            proposals,
            profile_id=profile_id,
            source_event_id=source_event_id,
            source_message_id=source_message_id,
            extractor_model=self._provider.model_name,
            created_at=created_at,
        )

    def _known_keys(
        self, profile_id: str, content: str, source_message_id: str
    ) -> dict[str, list[str]]:
        """Select known keys using the message and earlier turns of its conversation."""
        message = self._messages.get(source_message_id)
        earlier = (
            ()
            if message is None
            else tuple(
                item
                for item in self._messages.list_for_conversation(message.conversation_id)
                if item.id != source_message_id and item.created_at <= message.created_at
            )
        )
        earlier_ids = {item.id for item in earlier}
        recent_keys = {
            item.target_key
            for item in self._evidence.list_for_profile(profile_id)
            if item.source_message_id in earlier_ids
        }
        earlier_text = " ".join(
            item.content
            for item in earlier[-RECENT_USER_TURNS * 2 :]
            if item.role is MessageRole.USER
        )
        query = f"{content} {earlier_text}"
        return select_known_keys(
            self._rebuilder.current_model(profile_id),
            query=query,
            recent_keys=recent_keys,
            semantic_scores=(
                None if self._semantics is None else self._semantics.query_scores(profile_id, query)
            ),
        )

    def _accept(self, profile_id: str, reviewed: ReviewedEvidence, now: datetime) -> int | None:
        for item in reviewed.accepted:
            self._evidence.add(item)
        if not reviewed.accepted:
            return None
        if self._catalog is not None:
            for label in reviewed.labels:
                self._catalog.upsert(label)
        register_normalized_aliases(self._evidence, self._aliases, profile_id, now)
        return self._rebuilder.rebuild(profile_id, now).version

    def _enqueue_learning(
        self,
        *,
        profile_id: str,
        source_event_id: str,
        source_message_id: str,
        created_at: datetime,
    ) -> None:
        if self._jobs is None:
            raise RuntimeError("A job repository is required for deferred conversation learning.")
        self._jobs.enqueue(
            Job(
                id=extraction_job_id(source_message_id),
                job_type=CONVERSATION_EXTRACTION_JOB,
                payload={
                    "profile_id": profile_id,
                    "source_event_id": source_event_id,
                    "source_message_id": source_message_id,
                },
                status=JobStatus.QUEUED,
                attempts=0,
                max_attempts=EXTRACTION_MAX_ATTEMPTS,
                available_at=created_at + EXTRACTION_INITIAL_DELAY,
                created_at=created_at,
                updated_at=created_at,
            )
        )

    async def retry_learning(self, payload: dict[str, object]) -> None:
        """Retry one persisted message without putting private content in the job payload."""
        profile_id = payload.get("profile_id")
        source_event_id = payload.get("source_event_id")
        source_message_id = payload.get("source_message_id")
        if (
            not isinstance(profile_id, str)
            or not isinstance(source_event_id, str)
            or not isinstance(source_message_id, str)
        ):
            raise ValueError("Conversation extraction job payload is invalid.")
        if any(
            item.source_event_id == source_event_id
            for item in self._evidence.list_for_profile(profile_id)
        ):
            return
        event = self._raw_events.get(source_event_id)
        message = self._messages.get(source_message_id)
        if (
            event is None
            or message is None
            or event.profile_id != profile_id
            or event.event_type != "conversation_message"
            or event.content.get("message_id") != source_message_id
        ):
            raise ValueError("Conversation extraction source is unavailable.")
        reviewed = await self._extract(
            profile_id,
            message.content,
            source_event_id,
            source_message_id,
            message.created_at,
        )
        self._accept(profile_id, reviewed, datetime.now(UTC))

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
            provenance=OWNER_LOCAL_EVENT,
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
        self._conversations.touch(resolved_id, assistant_created_at)
        if self._jobs is not None:
            self._enqueue_learning(
                profile_id=profile_id,
                source_event_id=event.id,
                source_message_id=user_message_id,
                created_at=now,
            )
            return ChatResult(
                resolved_id,
                user_message_id,
                assistant_message,
                (),
                0,
                None,
                "pending",
                None,
            )
        try:
            reviewed = await self._extract(profile_id, content, event.id, user_message_id, now)
        except (ProviderError, ValueError):
            return ChatResult(
                resolved_id,
                user_message_id,
                assistant_message,
                (),
                0,
                None,
                "pending",
                "The reply was saved, but learning could not be completed.",
            )
        snapshot_version = self._accept(profile_id, reviewed, now)
        return ChatResult(
            resolved_id,
            user_message_id,
            assistant_message,
            reviewed.accepted,
            reviewed.rejected_count,
            snapshot_version,
            "learned" if reviewed.accepted else "no_evidence",
            None,
        )
