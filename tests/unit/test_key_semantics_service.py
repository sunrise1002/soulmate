"""Key vector upkeep, semantic retrieval scores, and refresh scheduling."""

from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from soulmate_core.domain import (
    EvidenceTargetType,
    Job,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
    TargetKeyEmbedding,
    TargetKeyLabel,
    TargetKeyLabelSource,
)
from soulmate_core.embeddings import EmbeddingUnavailableError, NullEmbedding
from soulmate_core.keys import key_embedding_text, key_text_hash
from soulmate_daemon.key_semantics import (
    KEY_EMBEDDING_REFRESH_JOB,
    KeySemanticsService,
    enqueue_key_embedding_refresh,
    refresh_from_payload,
)

from tests.key_embedding_support import (
    DIMENSIONS,
    FakeConceptEmbedding,
    TruncatingEmbedding,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
PROFILE = "profile_keys"
PREFERENCE = EvidenceTargetType.PREFERENCE


class FakeEvidence:
    """Only the evidence reads the key semantics service performs."""

    def __init__(self, *keys: str, revision: int = 1) -> None:
        self.revision = revision
        self._items = tuple(
            _evidence(f"evidence_{index}", key, NOW + timedelta(seconds=index))
            for index, key in enumerate(keys)
        )

    def list_for_profile(self, profile_id: str) -> tuple[object, ...]:
        return self._items if profile_id == PROFILE else ()

    def current_revision(self, profile_id: str) -> int:
        return self.revision if profile_id == PROFILE else 0


class FakeCatalog:
    def __init__(self, *labels: TargetKeyLabel) -> None:
        self.entries = list(labels)

    def list_for_profile(self, profile_id: str) -> tuple[TargetKeyLabel, ...]:
        return tuple(item for item in self.entries if item.profile_id == profile_id)

    def upsert(self, entry: TargetKeyLabel) -> TargetKeyLabel:
        self.entries.append(entry)
        return entry


class FakeEmbeddings:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, EvidenceTargetType, str, str], TargetKeyEmbedding] = {}
        self.removed_models: list[str] = []

    def replace_many(self, embeddings: Collection[TargetKeyEmbedding]) -> int:
        for item in embeddings:
            self.rows[(item.profile_id, item.target_type, item.key, item.model_id)] = item
        return len(embeddings)

    def list_for_model(self, profile_id: str, model_id: str) -> tuple[TargetKeyEmbedding, ...]:
        return tuple(
            item
            for key, item in sorted(self.rows.items(), key=lambda entry: entry[0][2])
            if key[0] == profile_id and key[3] == model_id
        )

    def remove_other_models(self, profile_id: str, model_id: str) -> int:
        self.removed_models.append(model_id)
        stale = [key for key in self.rows if key[0] == profile_id and key[3] != model_id]
        for key in stale:
            del self.rows[key]
        return len(stale)


class FakeAliases:
    def __init__(self, *aliases: TargetKeyAlias, failure: Exception | None = None) -> None:
        self.stored = list(aliases)
        self._failure = failure

    def list_for_profile(
        self, profile_id: str, status: TargetKeyAliasStatus | None = None
    ) -> tuple[TargetKeyAlias, ...]:
        return tuple(
            item
            for item in self.stored
            if item.profile_id == profile_id and (status is None or item.status is status)
        )

    def upsert(self, alias: TargetKeyAlias) -> TargetKeyAlias:
        if self._failure is not None:
            raise self._failure
        self.stored.append(alias)
        return alias


class FakeJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def enqueue(self, job: Job) -> None:
        if job.id in self.jobs:
            raise ValueError("Duplicate job.")
        self.jobs[job.id] = job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)


def _evidence(evidence_id: str, key: str, created_at: datetime) -> object:
    from soulmate_core.domain import Evidence

    return Evidence(
        id=evidence_id,
        profile_id=PROFILE,
        target_type=PREFERENCE,
        target_key=key,
        value=0.5,
        strength=1.0,
        confidence=1.0,
        context={},
        source_type="explicit_statement",
        source_event_id=f"event_{evidence_id}",
        extractor_version="synthetic-v1",
        created_at=created_at,
    )


def _label(key: str, label: str) -> TargetKeyLabel:
    return TargetKeyLabel(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        key=key,
        label=label,
        aliases=(),
        source=TargetKeyLabelSource.EXTRACTED,
        created_at=NOW,
        updated_at=NOW,
    )


def _alias(alias_key: str, canonical_key: str) -> TargetKeyAlias:
    return TargetKeyAlias(
        profile_id=PROFILE,
        target_type=PREFERENCE,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=1,
        method=TargetKeyAliasMethod.NORMALIZED,
        status=TargetKeyAliasStatus.REJECTED,
        algorithm_version="key-normalizer-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _service(
    evidence: FakeEvidence,
    *,
    provider: object | None = None,
    catalog: FakeCatalog | None = None,
    embeddings: FakeEmbeddings | None = None,
    aliases: FakeAliases | None = None,
    threshold: float = 0.85,
    batch_size: int = 32,
) -> tuple[KeySemanticsService, FakeEmbeddings, FakeAliases | None]:
    stored = embeddings if embeddings is not None else FakeEmbeddings()
    resolved_aliases = aliases
    service = KeySemanticsService(
        evidence=evidence,  # type: ignore[arg-type]
        catalog=(catalog if catalog is not None else FakeCatalog()),  # type: ignore[arg-type]
        embeddings=stored,
        aliases=resolved_aliases,  # type: ignore[arg-type]
        provider=provider if provider is not None else FakeConceptEmbedding(),  # type: ignore[arg-type]
        threshold=threshold,
        batch_size=batch_size,
    )
    return service, stored, resolved_aliases


def test_a_refresh_embeds_every_used_key_once() -> None:
    # Given: two used keys and an installed model
    evidence = FakeEvidence("ui.theme.dark", "food.spicy")
    service, stored, _ = _service(evidence)

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: both keys are stored under the active model with their text hash
    assert result.embedded_count == 2
    assert {key[2] for key in stored.rows} == {"ui.theme.dark", "food.spicy"}
    row = stored.rows[(PROFILE, PREFERENCE, "ui.theme.dark", "fake-concept-v1")]
    assert row.text_hash == key_text_hash(key_embedding_text("ui.theme.dark"))
    assert row.dim == DIMENSIONS


def test_a_second_refresh_embeds_nothing_when_no_text_changed() -> None:
    # Given: an already embedded profile
    evidence = FakeEvidence("ui.theme.dark")
    provider = FakeConceptEmbedding()
    service, stored, _ = _service(evidence, provider=provider)
    service.refresh(PROFILE, NOW)
    calls = len(provider.calls)

    # When: the refresh runs again
    result = service.refresh(PROFILE, NOW)

    # Then: the model is not asked again and the row survives
    assert (result.embedded_count, len(provider.calls)) == (0, calls)
    assert len(stored.rows) == 1


def test_a_new_owner_label_re_embeds_only_its_own_key() -> None:
    # Given: two embedded keys, one of which gains a label afterwards
    evidence = FakeEvidence("ui.theme.dark", "food.spicy")
    catalog = FakeCatalog()
    provider = FakeConceptEmbedding()
    service, stored, _ = _service(evidence, catalog=catalog, provider=provider)
    service.refresh(PROFILE, NOW)
    catalog.entries.append(_label("ui.theme.dark", "giao diện tối"))

    # When: the refresh runs again
    result = service.refresh(PROFILE, NOW)

    # Then: only the labelled key is embedded again, with the label in its text
    assert result.embedded_count == 1
    assert provider.calls[-1] == ("ui theme dark | giao diện tối",)
    row = stored.rows[(PROFILE, PREFERENCE, "ui.theme.dark", "fake-concept-v1")]
    assert row.text_hash == key_text_hash("ui theme dark | giao diện tối")


def test_vectors_of_an_earlier_model_are_dropped() -> None:
    # Given: a vector stored by a previous model
    evidence = FakeEvidence("ui.theme.dark")
    stored = FakeEmbeddings()
    stored.replace_many(
        [
            TargetKeyEmbedding(
                profile_id=PROFILE,
                target_type=PREFERENCE,
                key="ui.theme.dark",
                model_id="retired-model",
                text_hash="stale",
                vector=(1.0,),
                created_at=NOW,
            )
        ]
    )
    service, stored, _ = _service(evidence, embeddings=stored)

    # When: the refresh runs with the current model
    service.refresh(PROFILE, NOW)

    # Then: only the current model's vector remains
    assert {key[3] for key in stored.rows} == {"fake-concept-v1"}


def test_a_refresh_without_an_installed_model_writes_nothing() -> None:
    # Given: a configured provider whose model is not installed
    evidence = FakeEvidence("ui.theme.dark")
    service, stored, _ = _service(evidence, provider=FakeConceptEmbedding(ready=False))

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: no text reaches a model and no row is written
    assert (result.embedded_count, result.suggested_count, stored.rows) == (0, 0, {})


def test_a_failing_model_releases_itself_and_keeps_the_lexical_fallback() -> None:
    # Given: a model that fails while embedding
    evidence = FakeEvidence("ui.theme.dark")
    provider = FakeConceptEmbedding(failure=EmbeddingUnavailableError("broken"))
    service, stored, _ = _service(evidence, provider=provider)

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: the failure is absorbed, memory is released, and nothing is stored
    assert (result.embedded_count, stored.rows) == (0, {})
    assert provider.releases == 1


def test_a_provider_returning_too_few_vectors_stores_nothing() -> None:
    # Given: a provider that breaks the one-vector-per-text contract
    evidence = FakeEvidence("ui.theme.dark", "food.spicy")
    service, stored, _ = _service(evidence, provider=TruncatingEmbedding())

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: the partial result is discarded instead of pairing wrong vectors
    assert (result.embedded_count, stored.rows) == (0, {})


def test_keys_are_embedded_in_batches() -> None:
    # Given: more keys than one batch holds
    evidence = FakeEvidence("a.one", "b.two", "c.three")
    provider = FakeConceptEmbedding()
    service, _, _ = _service(evidence, provider=provider, batch_size=2)

    # When: the refresh runs
    service.refresh(PROFILE, NOW)

    # Then: the provider is called once per batch
    assert [len(call) for call in provider.calls] == [2, 1]


def test_a_batch_size_below_one_is_rejected() -> None:
    # Given: an unusable batch size
    # When: the service is built
    # Then: the service refuses to exist
    with pytest.raises(ValueError, match="batch size must be positive"):
        _service(FakeEvidence(), batch_size=0)


def test_similar_keys_become_suggestions_the_owner_can_review() -> None:
    # Given: a Vietnamese label that makes two keys describe the same concept
    evidence = FakeEvidence("ui.theme.dark", "appearance.night")
    catalog = FakeCatalog(_label("appearance.night", "giao diện tối"))
    aliases = FakeAliases()
    service, _, _ = _service(evidence, catalog=catalog, aliases=aliases, threshold=0.8)

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: the pair is stored as a suggestion, never as an active merge
    assert result.suggested_count == 1
    assert aliases.stored[0].status is TargetKeyAliasStatus.SUGGESTED
    assert aliases.stored[0].method is TargetKeyAliasMethod.SEMANTIC


def test_a_rejected_pair_is_not_suggested_again() -> None:
    # Given: an owner rejection recorded for the later key
    evidence = FakeEvidence("ui.theme.dark", "appearance.night")
    catalog = FakeCatalog(_label("appearance.night", "giao diện tối"))
    aliases = FakeAliases(_alias("appearance.night", "ui.theme.dark"))
    service, _, _ = _service(evidence, catalog=catalog, aliases=aliases, threshold=0.8)

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: the rejection stands
    assert (result.suggested_count, len(aliases.stored)) == (0, 1)


def test_a_conflicting_alias_write_is_skipped_without_failing_the_refresh() -> None:
    # Given: an alias repository that rejects the write
    evidence = FakeEvidence("ui.theme.dark", "appearance.night")
    catalog = FakeCatalog(_label("appearance.night", "giao diện tối"))
    aliases = FakeAliases(failure=ValueError("cycle"))
    service, _, _ = _service(evidence, catalog=catalog, aliases=aliases, threshold=0.8)

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: the vectors are still stored and the suggestion is dropped
    assert (result.embedded_count, result.suggested_count) == (2, 0)


def test_disabled_aliases_produce_no_suggestions() -> None:
    # Given: the owner disabled key aliases
    evidence = FakeEvidence("ui.theme.dark", "appearance.night")
    catalog = FakeCatalog(_label("appearance.night", "giao diện tối"))
    service, _, _ = _service(evidence, catalog=catalog, aliases=None, threshold=0.8)

    # When: the refresh runs
    result = service.refresh(PROFILE, NOW)

    # Then: vectors are kept for retrieval but nothing is suggested
    assert (result.embedded_count, result.suggested_count) == (2, 0)


def test_query_scores_rank_a_vietnamese_message_against_english_keys() -> None:
    # Given: embedded English keys
    evidence = FakeEvidence("ui.theme.dark", "work.remote")
    service, _, _ = _service(evidence)
    service.refresh(PROFILE, NOW)

    # When: a Vietnamese message is scored
    scores = service.query_scores(PROFILE, "Tôi thích giao diện tối")

    # Then: the matching key scores highest
    assert max(scores, key=lambda key: scores[key]) == "ui.theme.dark"
    assert scores["ui.theme.dark"] > scores["work.remote"]


@pytest.mark.parametrize("query", ["", "   "])
def test_a_blank_query_is_never_embedded(query: str) -> None:
    # Given: an embedded profile
    evidence = FakeEvidence("ui.theme.dark")
    provider = FakeConceptEmbedding()
    service, _, _ = _service(evidence, provider=provider)
    service.refresh(PROFILE, NOW)
    calls = len(provider.calls)

    # When: a blank query is scored
    # Then: no score is produced and the model is not used
    assert service.query_scores(PROFILE, query) == {}
    assert len(provider.calls) == calls


def test_query_scores_are_empty_before_anything_is_embedded() -> None:
    # Given: an installed model but no stored vectors
    service, _, _ = _service(FakeEvidence("ui.theme.dark"))

    # When: a query is scored
    # Then: the caller falls back to lexical ranking
    assert service.query_scores(PROFILE, "giao diện tối") == {}


def test_query_scores_are_empty_when_the_model_is_not_installed() -> None:
    # Given: stored vectors but a model that is no longer installed
    evidence = FakeEvidence("ui.theme.dark")
    service, stored, _ = _service(evidence)
    service.refresh(PROFILE, NOW)
    offline, _, _ = _service(
        evidence, provider=FakeConceptEmbedding(ready=False), embeddings=stored
    )

    # When: a query is scored
    # Then: nothing is scored and no download is triggered
    assert offline.query_scores(PROFILE, "giao diện tối") == {}


def test_query_scores_absorb_a_failing_model() -> None:
    # Given: stored vectors and a model that fails at query time
    evidence = FakeEvidence("ui.theme.dark")
    service, stored, _ = _service(evidence)
    service.refresh(PROFILE, NOW)
    failing, _, _ = _service(
        evidence,
        provider=FakeConceptEmbedding(failure=EmbeddingUnavailableError("broken")),
        embeddings=stored,
    )

    # When: a query is scored
    # Then: the lexical fallback is used instead of surfacing an error
    assert failing.query_scores(PROFILE, "giao diện tối") == {}


def test_the_null_provider_reports_itself_as_unusable() -> None:
    # Given: the default provider
    service, _, _ = _service(FakeEvidence("ui.theme.dark"), provider=NullEmbedding())

    # When: its readiness and model are inspected
    # Then: nothing is ready and the model name says so
    assert (service.ready, service.model_id) == (False, "none")


def test_one_refresh_is_queued_per_evidence_revision_and_model() -> None:
    # Given: an installed model and no queued job
    evidence = FakeEvidence("ui.theme.dark")
    service, _, _ = _service(evidence)
    jobs = FakeJobs()

    # When: the check runs twice for the same revision
    first = enqueue_key_embedding_refresh(jobs, evidence, service, PROFILE, NOW)  # type: ignore[arg-type]
    second = enqueue_key_embedding_refresh(jobs, evidence, service, PROFILE, NOW)  # type: ignore[arg-type]

    # Then: exactly one job exists and it names only the profile
    assert first is not None and second is None
    assert first.job_type == KEY_EMBEDDING_REFRESH_JOB
    assert first.payload == {"profile_id": PROFILE}
    assert first.available_at > NOW
    assert len(jobs.jobs) == 1


def test_new_evidence_queues_another_refresh() -> None:
    # Given: an already queued refresh
    evidence = FakeEvidence("ui.theme.dark")
    service, _, _ = _service(evidence)
    jobs = FakeJobs()
    enqueue_key_embedding_refresh(jobs, evidence, service, PROFILE, NOW)  # type: ignore[arg-type]

    # When: the evidence revision advances
    evidence.revision = 2
    queued = enqueue_key_embedding_refresh(jobs, evidence, service, PROFILE, NOW)  # type: ignore[arg-type]

    # Then: a second job is queued
    assert queued is not None
    assert len(jobs.jobs) == 2


def test_nothing_is_queued_while_no_model_is_installed() -> None:
    # Given: a configured provider without an installed model
    evidence = FakeEvidence("ui.theme.dark")
    service, _, _ = _service(evidence, provider=FakeConceptEmbedding(ready=False))
    jobs = FakeJobs()

    # When: the check runs
    # Then: no job is queued, so nothing can trigger a download
    assert enqueue_key_embedding_refresh(jobs, evidence, service, PROFILE, NOW) is None  # type: ignore[arg-type]
    assert jobs.jobs == {}


def test_a_queued_refresh_runs_for_the_named_profile() -> None:
    # Given: a queued payload
    evidence = FakeEvidence("ui.theme.dark")
    service, stored, _ = _service(evidence)

    # When: the job handler runs it
    result = refresh_from_payload(service, {"profile_id": PROFILE})

    # Then: the refresh happened for that profile
    assert result.embedded_count == 1
    assert {key[0] for key in stored.rows} == {PROFILE}


@pytest.mark.parametrize("payload", [{}, {"profile_id": ""}, {"profile_id": 7}, {"other": "x"}])
def test_an_invalid_refresh_payload_is_rejected(payload: dict[str, object]) -> None:
    # Given: a payload that names no profile
    service, _, _ = _service(FakeEvidence())

    # When: the job handler runs it
    # Then: the job fails loudly instead of refreshing the wrong profile
    with pytest.raises(ValueError, match="payload is invalid"):
        refresh_from_payload(service, payload)


def test_another_profile_is_never_embedded() -> None:
    # Given: evidence that belongs to one profile only
    evidence = FakeEvidence("ui.theme.dark")
    service, stored, _ = _service(evidence)

    # When: a refresh runs for a different profile
    result = service.refresh("profile_other", NOW)

    # Then: no row is written for either profile
    assert (result.embedded_count, stored.rows) == (0, {})


def test_embedded_keys_keep_their_order_of_first_use() -> None:
    # Given: two keys whose evidence was created in a known order
    evidence = FakeEvidence("ui.theme.dark", "appearance.night")
    catalog = FakeCatalog(_label("appearance.night", "giao diện tối"))
    aliases = FakeAliases()
    service, _, _ = _service(evidence, catalog=catalog, aliases=aliases, threshold=0.8)

    # When: a suggestion is produced
    service.refresh(PROFILE, NOW)

    # Then: the earlier key is canonical, so established keys keep their name
    assert aliases.stored[0].canonical_key == "ui.theme.dark"
    assert aliases.stored[0].alias_key == "appearance.night"


def test_a_vector_is_stored_for_every_text_in_order() -> None:
    # Given: a provider whose vectors differ per concept
    evidence = FakeEvidence("ui.theme.dark", "food.spicy")
    provider = FakeConceptEmbedding()
    service, stored, _ = _service(evidence, provider=provider)

    # When: the refresh runs
    service.refresh(PROFILE, NOW)

    # Then: each key carries the vector of its own text
    expected: Sequence[tuple[float, ...]] = provider.embed(("ui theme dark", "food spicy"))
    assert stored.rows[(PROFILE, PREFERENCE, "ui.theme.dark", "fake-concept-v1")].vector == (
        pytest.approx(expected[0])
    )
    assert stored.rows[(PROFILE, PREFERENCE, "food.spicy", "fake-concept-v1")].vector == (
        pytest.approx(expected[1])
    )
