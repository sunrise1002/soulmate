"""Key vector upkeep, semantic key retrieval, and semantic merge suggestions.

Embedding runs in a durable background job, never on the chat path, and every
failure degrades to the lexical key ranking of step A instead of surfacing an
error. Similarity never merges keys by itself: suggestions wait for owner review,
because the P0 spike measured opposite keys as more similar than typical correct
matches.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from soulmate_core.domain import (
    Evidence,
    EvidenceRepository,
    EvidenceTargetType,
    Job,
    JobRepository,
    JobStatus,
    TargetKeyAliasRepository,
    TargetKeyCatalogRepository,
    TargetKeyEmbedding,
    TargetKeyEmbeddingRepository,
    TargetKeyLabel,
)
from soulmate_core.embeddings import EmbeddingProvider, EmbeddingUnavailableError
from soulmate_core.keys import (
    DEFAULT_SEMANTIC_ALIAS_LIMIT,
    EmbeddedKey,
    key_embedding_text,
    key_text_hash,
    propose_semantic_aliases,
    semantic_key_scores,
)
from soulmate_storage_sqlite import Repositories

from soulmate_daemon.config import Settings
from soulmate_daemon.key_aliases import alias_repository

KEY_EMBEDDING_REFRESH_JOB = "key_embedding_refresh"
KEY_EMBEDDING_INITIAL_DELAY = timedelta(seconds=1)
KEY_EMBEDDING_INTERVAL_SECONDS = 60
EMBEDDING_BATCH_SIZE = 32

type _TypedKey = tuple[EvidenceTargetType, str]


@dataclass(frozen=True, slots=True)
class KeyEmbeddingRefresh:
    """What one refresh changed, for tests and job diagnostics only."""

    embedded_count: int
    suggested_count: int
    model_id: str


def _key_texts(
    evidence: Sequence[Evidence], labels: Sequence[TargetKeyLabel]
) -> dict[_TypedKey, str]:
    """Return the embedded text of every used key, in order of first use."""
    by_key = {(label.target_type, label.key): label for label in labels}
    texts: dict[_TypedKey, str] = {}
    for item in sorted(evidence, key=lambda value: (value.created_at, value.id)):
        identity = (item.target_type, item.target_key)
        if identity in texts:
            continue
        label = by_key.get(identity)
        texts[identity] = key_embedding_text(
            item.target_key,
            None if label is None else label.label,
            () if label is None else label.aliases,
        )
    return texts


class KeySemanticsService:
    """Own the derived key vectors and everything read from them."""

    def __init__(
        self,
        *,
        evidence: EvidenceRepository,
        catalog: TargetKeyCatalogRepository,
        embeddings: TargetKeyEmbeddingRepository,
        aliases: TargetKeyAliasRepository | None,
        provider: EmbeddingProvider,
        threshold: float,
        suggestion_limit: int = DEFAULT_SEMANTIC_ALIAS_LIMIT,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("The embedding batch size must be positive.")
        self._evidence = evidence
        self._catalog = catalog
        self._embeddings = embeddings
        self._aliases = aliases
        self._provider = provider
        self._threshold = threshold
        self._suggestion_limit = suggestion_limit
        self._batch_size = batch_size

    @property
    def ready(self) -> bool:
        """Report whether a model is installed, so no caller triggers a download."""
        return self._provider.ready

    @property
    def model_id(self) -> str:
        return self._provider.model_id

    def query_scores(self, profile_id: str, query: str) -> dict[str, float]:
        """Score stored keys against ``query``; an unusable model scores nothing."""
        if not query.strip() or not self._provider.ready:
            return {}
        stored = self._embeddings.list_for_model(profile_id, self._provider.model_id)
        if not stored:
            return {}
        try:
            vectors = self._provider.embed((query,))
        except EmbeddingUnavailableError:
            return {}
        if not vectors:
            return {}
        return semantic_key_scores(
            vectors[0],
            [EmbeddedKey(item.target_type, item.key, item.vector) for item in stored],
        )

    def refresh(self, profile_id: str, now: datetime) -> KeyEmbeddingRefresh:
        """Recompute stale key vectors, then suggest semantic merges from them."""
        model_id = self._provider.model_id
        if not self._provider.ready:
            return KeyEmbeddingRefresh(0, 0, model_id)
        texts = _key_texts(
            self._evidence.list_for_profile(profile_id),
            self._catalog.list_for_profile(profile_id),
        )
        stored = {
            (item.target_type, item.key): item
            for item in self._embeddings.list_for_model(profile_id, model_id)
        }
        stale = [
            identity
            for identity, text in texts.items()
            if identity not in stored or stored[identity].text_hash != key_text_hash(text)
        ]
        try:
            written = self._embed(profile_id, texts, stale, model_id, now)
        except EmbeddingUnavailableError:
            self._provider.release()
            return KeyEmbeddingRefresh(0, 0, model_id)
        self._embeddings.remove_other_models(profile_id, model_id)
        current = {**stored, **{(item.target_type, item.key): item for item in written}}
        keys = [
            EmbeddedKey(target_type, key, current[(target_type, key)].vector)
            for target_type, key in texts
            if (target_type, key) in current
        ]
        return KeyEmbeddingRefresh(len(written), self._suggest(profile_id, keys, now), model_id)

    def _embed(
        self,
        profile_id: str,
        texts: dict[_TypedKey, str],
        stale: Sequence[_TypedKey],
        model_id: str,
        now: datetime,
    ) -> tuple[TargetKeyEmbedding, ...]:
        written: list[TargetKeyEmbedding] = []
        for start in range(0, len(stale), self._batch_size):
            batch = stale[start : start + self._batch_size]
            vectors = self._provider.embed([texts[identity] for identity in batch])
            if len(vectors) != len(batch):
                raise EmbeddingUnavailableError("The embedding provider returned wrong output.")
            for (target_type, key), vector in zip(batch, vectors, strict=True):
                written.append(
                    TargetKeyEmbedding(
                        profile_id=profile_id,
                        target_type=target_type,
                        key=key,
                        model_id=model_id,
                        text_hash=key_text_hash(texts[(target_type, key)]),
                        vector=vector,
                        created_at=now,
                    )
                )
        self._embeddings.replace_many(written)
        return tuple(written)

    def _suggest(self, profile_id: str, keys: Sequence[EmbeddedKey], now: datetime) -> int:
        """Store owner-review suggestions; aliases stay disabled when the owner says so."""
        if self._aliases is None:
            return 0
        proposals = propose_semantic_aliases(
            profile_id,
            keys,
            self._aliases.list_for_profile(profile_id),
            now,
            threshold=self._threshold,
            limit=self._suggestion_limit,
        )
        stored = 0
        for proposal in proposals:
            try:
                self._aliases.upsert(proposal.alias)
            except ValueError:
                # A concurrent owner change made the pair impossible; keep them apart.
                continue
            stored += 1
        return stored


def key_semantics_service(
    repositories: Repositories,
    settings: Settings,
    provider: EmbeddingProvider,
) -> KeySemanticsService:
    """Compose the service from stored repositories and the configured provider."""
    return KeySemanticsService(
        evidence=repositories.evidence,
        catalog=repositories.key_catalog,
        embeddings=repositories.key_embeddings,
        aliases=alias_repository(repositories, settings),
        provider=provider,
        threshold=settings.key_aliases.semantic_threshold,
    )


def enqueue_key_embedding_refresh(
    jobs: JobRepository,
    evidence: EvidenceRepository,
    semantics: KeySemanticsService,
    profile_id: str,
    now: datetime | None = None,
) -> Job | None:
    """Queue one refresh per evidence revision and model, or nothing when up to date.

    The job identity carries the revision and the model, so new evidence, an
    installed model, and a changed model each queue exactly one refresh while
    repeated checks stay free. Nothing is queued while no model is installed, so
    this never triggers a download.
    """
    if not semantics.ready:
        return None
    revision = evidence.current_revision(profile_id)
    job_id = f"job_key_embeddings_{profile_id}_{semantics.model_id}_{revision}"
    if jobs.get(job_id) is not None:
        return None
    created_at = now if now is not None else datetime.now(UTC)
    job = Job(
        id=job_id,
        job_type=KEY_EMBEDDING_REFRESH_JOB,
        payload={"profile_id": profile_id},
        status=JobStatus.QUEUED,
        attempts=0,
        max_attempts=3,
        available_at=created_at + KEY_EMBEDDING_INITIAL_DELAY,
        created_at=created_at,
        updated_at=created_at,
    )
    jobs.enqueue(job)
    return job


def refresh_from_payload(
    semantics: KeySemanticsService, payload: dict[str, object]
) -> KeyEmbeddingRefresh:
    """Run one queued refresh; the payload names a profile and never key text."""
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise ValueError("Key embedding refresh job payload is invalid.")
    return semantics.refresh(profile_id, datetime.now(UTC))
