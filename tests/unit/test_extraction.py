"""Structured extraction validation and low-risk review rules."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from soulmate_core.domain import EvidenceTargetType
from soulmate_daemon.extraction import (
    EvidenceProposals,
    extraction_schema,
    review_proposals,
    validate_proposals,
)


def test_extraction_rejects_invalid_preference_value() -> None:
    with pytest.raises(ValidationError):
        EvidenceProposals.model_validate(
            {
                "preferences": [
                    {
                        "target_key": "work.remote",
                        "value": 2,
                        "strength": 0.8,
                        "confidence": 0.9,
                        "context": {},
                    }
                ]
            }
        )


def test_review_stamps_provenance_and_holds_sensitive_claims() -> None:
    proposals = EvidenceProposals.model_validate(
        {
            "preferences": [
                {
                    "target_key": "work.remote",
                    "value": 0.8,
                    "strength": 0.7,
                    "confidence": 0.9,
                    "context": {"domain": "career"},
                },
                {
                    "target_key": "health.condition",
                    "value": -0.5,
                    "strength": 0.7,
                    "confidence": 0.9,
                    "context": {},
                },
            ]
        }
    )
    reviewed = review_proposals(
        proposals,
        profile_id="profile_test",
        source_event_id="event_test",
        source_message_id="message_test",
        extractor_model="fake-model-v1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert reviewed.rejected_count == 1
    assert len(reviewed.accepted) == 1
    evidence = reviewed.accepted[0]
    assert evidence.target_type is EvidenceTargetType.PREFERENCE
    assert evidence.extractor_model == "fake-model-v1"
    assert evidence.extractor_version == "conversation-evidence-v1"
    assert evidence.source_message_id == "message_test"


def test_portable_schema_avoids_dynamic_values_and_normalizes_context() -> None:
    schema = extraction_schema()
    assert "$defs" not in schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    facts = properties["facts"]
    assert isinstance(facts, dict)
    items = facts["items"]
    assert isinstance(items, dict)
    item_properties = items["properties"]
    assert isinstance(item_properties, dict)
    context = item_properties["context"]
    assert isinstance(context, dict)
    assert context["type"] == "array"

    proposals = validate_proposals(
        {
            "facts": [
                {
                    "target_key": "work.location",
                    "value": "remote",
                    "strength": 0.8,
                    "confidence": 0.9,
                    "context": [{"key": "domain", "value": "career"}],
                }
            ],
            "preferences": [],
            "goals": [],
            "constraints": [],
        }
    )
    assert proposals.facts[0].context == {"domain": "career"}
