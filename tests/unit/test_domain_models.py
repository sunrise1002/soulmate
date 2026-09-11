"""Validate domain invariants without infrastructure."""

from datetime import UTC, datetime

import pytest
from soulmate_core.domain import Evidence, EvidenceTargetType, Profile


def test_domain_records_reject_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Profile("profile_test", None, datetime(2026, 1, 1))


@pytest.mark.parametrize("field,value", [("strength", -0.1), ("confidence", 1.1)])
def test_evidence_rejects_invalid_probability_fields(field: str, value: float) -> None:
    values = {"strength": 0.8, "confidence": 0.9, field: value}
    with pytest.raises(ValueError, match=field):
        Evidence(
            id="evidence_test",
            profile_id="profile_test",
            target_type=EvidenceTargetType.PREFERENCE,
            target_key="work.remote",
            value=0.5,
            strength=values["strength"],
            confidence=values["confidence"],
            context={},
            source_type="explicit_statement",
            source_event_id="event_test",
            extractor_version="synthetic-v1",
            created_at=datetime.now(UTC),
        )


def test_preference_evidence_rejects_non_numeric_or_out_of_range_values() -> None:
    for value in (True, "strong", 1.1):
        with pytest.raises(ValueError, match="Preference evidence value"):
            Evidence(
                id="evidence_test",
                profile_id="profile_test",
                target_type=EvidenceTargetType.PREFERENCE,
                target_key="work.remote",
                value=value,
                strength=0.8,
                confidence=0.9,
                context={},
                source_type="explicit_statement",
                source_event_id="event_test",
                extractor_version="synthetic-v1",
                created_at=datetime.now(UTC),
            )
