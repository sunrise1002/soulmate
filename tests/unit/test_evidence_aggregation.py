"""Test deterministic, infrastructure-free Personal Model aggregation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from soulmate_core.domain import Evidence, EvidenceTargetType
from soulmate_core.preferences import ALGORITHM_VERSION, aggregate_evidence


def _evidence(
    evidence_id: str,
    value: object,
    *,
    target_type: EvidenceTargetType = EvidenceTargetType.PREFERENCE,
    source_type: str = "explicit_statement",
    offset: int = 0,
) -> Evidence:
    return Evidence(
        id=evidence_id,
        profile_id="profile_test",
        target_type=target_type,
        target_key="work.remote"
        if target_type is EvidenceTargetType.PREFERENCE
        else "owner.region",
        value=value,
        strength=1.0,
        confidence=1.0,
        context={"domain": "career"},
        source_type=source_type,
        source_event_id=f"event_{evidence_id}",
        extractor_version="synthetic-v1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )


def test_multiple_contradictory_evidence_items_produce_deterministic_preference() -> None:
    positive = _evidence("positive", 0.8)
    negative = _evidence("negative", -0.4, source_type="actual_choice", offset=1)

    forward = aggregate_evidence([positive, negative])
    reverse = aggregate_evidence([negative, positive])

    assert forward == reverse
    preference = forward.preferences[0]
    assert -0.4 < preference.value < 0.8
    assert preference.uncertainty > 0
    assert preference.supporting_evidence_ids == ("positive", "negative")
    assert ALGORITHM_VERSION == "personal-model-v1:evidence-weights-v1"


def test_contexts_remain_separate_and_correction_changes_preference() -> None:
    original = _evidence("original", 0.8)
    correction = _evidence("correction", -0.4, source_type="user_correction", offset=1)
    personal = replace(original, id="personal", context={"domain": "personal"})

    before = aggregate_evidence([original, personal])
    after = aggregate_evidence([original, correction, personal])

    before_career = next(item for item in before.preferences if item.context["domain"] == "career")
    after_career = next(item for item in after.preferences if item.context["domain"] == "career")
    assert after_career.value < before_career.value
    assert len(after.preferences) == 2


def test_fact_is_derived_without_an_llm_and_keeps_all_provenance() -> None:
    old = _evidence("old", "north", target_type=EvidenceTargetType.FACT)
    correction = _evidence(
        "corrected",
        "south",
        target_type=EvidenceTargetType.FACT,
        source_type="user_correction",
        offset=1,
    )

    model = aggregate_evidence([old, correction])

    assert model.facts[0].value == "south"
    assert model.facts[0].supporting_evidence_ids == ("old", "corrected")
