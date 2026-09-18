"""Test deterministic, infrastructure-free Personal Model aggregation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from soulmate_core.domain import (
    Evidence,
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
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


def _alias(
    alias_key: str,
    canonical_key: str,
    *,
    target_type: EvidenceTargetType = EvidenceTargetType.PREFERENCE,
    polarity: int = 1,
    status: TargetKeyAliasStatus = TargetKeyAliasStatus.ACTIVE,
) -> TargetKeyAlias:
    return TargetKeyAlias(
        profile_id="profile_test",
        target_type=target_type,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=polarity,
        method=TargetKeyAliasMethod.NORMALIZED,
        status=status,
        algorithm_version="key-normalizer-v1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_aliased_near_duplicate_keys_reinforce_one_preference() -> None:
    learned = _evidence("learned", 0.6)
    extracted = replace(_evidence("extracted", 0.6, offset=1), target_key="work.remote_mode")

    split = aggregate_evidence([learned, extracted])
    merged = aggregate_evidence(
        [learned, extracted], aliases=[_alias("work.remote_mode", "work.remote")]
    )

    assert [item.key for item in split.preferences] == ["work.remote", "work.remote_mode"]
    assert [item.key for item in merged.preferences] == ["work.remote"]
    assert merged.preferences[0].supporting_evidence_ids == ("learned", "extracted")
    assert merged.preferences[0].confidence > max(item.confidence for item in split.preferences)


def test_opposite_keys_merge_into_one_signed_axis() -> None:
    positive = _evidence("dark", 0.8)
    opposite = replace(_evidence("light", 0.8, offset=1), target_key="work.onsite")

    merged = aggregate_evidence(
        [positive, opposite], aliases=[_alias("work.onsite", "work.remote", polarity=-1)]
    )

    assert [item.key for item in merged.preferences] == ["work.remote"]
    assert merged.preferences[0].value == 0.0
    assert (
        merged.preferences[0].confidence < aggregate_evidence([positive]).preferences[0].confidence
    )


def test_aliases_leave_stored_evidence_and_provenance_untouched() -> None:
    extracted = replace(_evidence("extracted", -0.5), target_key="work.remote_mode")

    merged = aggregate_evidence([extracted], aliases=[_alias("work.remote_mode", "work.remote")])

    assert extracted.target_key == "work.remote_mode"
    assert extracted.value == -0.5
    assert merged.preferences[0].supporting_evidence_ids == ("extracted",)


def test_removing_an_alias_restores_the_previous_grouping() -> None:
    learned = _evidence("learned", 0.6)
    extracted = replace(_evidence("extracted", 0.6, offset=1), target_key="work.remote_mode")

    before = aggregate_evidence([learned, extracted])
    aggregate_evidence([learned, extracted], aliases=[_alias("work.remote_mode", "work.remote")])
    after = aggregate_evidence([learned, extracted])

    assert after == before


def test_suggested_aliases_do_not_change_the_model_before_owner_review() -> None:
    learned = _evidence("learned", 0.6)
    extracted = replace(_evidence("extracted", 0.6, offset=1), target_key="work.remote_mode")
    suggestion = _alias("work.remote_mode", "work.remote", status=TargetKeyAliasStatus.SUGGESTED)

    reviewed = aggregate_evidence([learned, extracted], aliases=[suggestion])

    assert reviewed == aggregate_evidence([learned, extracted])


def test_aliases_merge_categorical_evidence_without_inverting_values() -> None:
    old = _evidence("old", "north", target_type=EvidenceTargetType.FACT)
    renamed = replace(
        _evidence(
            "renamed",
            "south",
            target_type=EvidenceTargetType.FACT,
            source_type="user_correction",
            offset=1,
        ),
        target_key="owner.region_setting",
    )

    merged = aggregate_evidence(
        [old, renamed],
        aliases=[
            _alias("owner.region_setting", "owner.region", target_type=EvidenceTargetType.FACT)
        ],
    )

    assert [item.key for item in merged.facts] == ["owner.region"]
    assert merged.facts[0].value == "south"
    assert merged.facts[0].supporting_evidence_ids == ("old", "renamed")


def test_aliases_of_another_profile_do_not_merge_this_profile_keys() -> None:
    learned = _evidence("learned", 0.6)
    extracted = replace(_evidence("extracted", 0.6, offset=1), target_key="work.remote_mode")
    foreign = replace(_alias("work.remote_mode", "work.remote"), profile_id="profile_other")

    aggregated = aggregate_evidence([learned, extracted], aliases=[foreign])

    assert [item.key for item in aggregated.preferences] == ["work.remote", "work.remote_mode"]


def test_conflicting_aliases_fail_the_rebuild_instead_of_grouping_arbitrarily() -> None:
    learned = _evidence("learned", 0.6)
    conflicting = [
        _alias("work.remote_mode", "work.remote"),
        _alias("work.remote_mode", "work.from_home"),
    ]

    with pytest.raises(ValueError, match="Conflicting active aliases"):
        aggregate_evidence([learned], aliases=conflicting)
