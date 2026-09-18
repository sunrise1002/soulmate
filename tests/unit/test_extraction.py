"""Structured extraction validation and low-risk review rules."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from soulmate_core.domain import EvidenceTargetType, TargetKeyLabelSource
from soulmate_daemon.extraction import (
    EvidenceProposals,
    ReviewedEvidence,
    extraction_schema,
    review_proposals,
    validate_proposals,
)

CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


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


def _reviewed(*preferences: dict[str, object]) -> ReviewedEvidence:
    return review_proposals(
        EvidenceProposals.model_validate({"preferences": list(preferences)}),
        profile_id="profile_test",
        source_event_id="event_test",
        source_message_id="message_test",
        extractor_model="fake-model-v1",
        created_at=CREATED_AT,
    )


def _proposal(**overrides: object) -> dict[str, object]:
    return {
        "target_key": "ui.theme.dark",
        "value": 0.8,
        "strength": 0.7,
        "confidence": 0.9,
        "context": {},
        **overrides,
    }


def test_the_portable_schema_asks_for_a_label_and_aliases() -> None:
    # Given: the wire schema shared with every provider family
    schema = extraction_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    preferences = properties["preferences"]
    assert isinstance(preferences, dict)
    items = preferences["items"]
    assert isinstance(items, dict)

    # When: the preference item schema is inspected
    item_properties = items["properties"]
    assert isinstance(item_properties, dict)

    # Then: both naming fields are plain required strings, keeping the schema flat
    assert item_properties["label"] == {"type": "string"}
    assert item_properties["aliases"] == {"type": "string"}
    assert {"label", "aliases"} <= set(items["required"])


def test_an_extracted_label_and_its_aliases_are_kept_for_the_key_catalog() -> None:
    # Given: a proposal labelled in the language the owner wrote
    # When: review runs over it
    reviewed = _reviewed(
        _proposal(label=" giao diện tối ", aliases="nền tối, chế độ đêm ,, giao diện tối")
    )

    # Then: one label carries the trimmed wording, without duplicates or the label
    assert len(reviewed.labels) == 1
    label = reviewed.labels[0]
    assert (label.key, label.label) == ("ui.theme.dark", "giao diện tối")
    assert label.aliases == ("nền tối", "chế độ đêm")
    assert label.source is TargetKeyLabelSource.EXTRACTED
    assert label.target_type is EvidenceTargetType.PREFERENCE
    assert label.created_at == CREATED_AT


@pytest.mark.parametrize("overrides", [{}, {"label": "   "}, {"aliases": " , ,"}])
def test_a_proposal_without_wording_stores_no_label(overrides: dict[str, object]) -> None:
    # Given: a proposal with no label and no aliases
    # When: review runs over it
    reviewed = _reviewed(_proposal(**overrides))

    # Then: the evidence is accepted and the catalog stays empty
    assert len(reviewed.accepted) == 1
    assert reviewed.labels == ()


def test_aliases_alone_are_enough_to_record_a_label() -> None:
    # Given: alternative wordings without a primary label
    # When: the proposal is reviewed
    reviewed = _reviewed(_proposal(aliases="nền tối"))

    # Then: the record keeps the aliases and no label
    assert len(reviewed.labels) == 1
    assert (reviewed.labels[0].label, reviewed.labels[0].aliases) == (None, ("nền tối",))


def test_at_most_five_aliases_are_kept() -> None:
    # Given: more alternative wordings than the catalog accepts
    # When: the proposal is reviewed
    reviewed = _reviewed(_proposal(aliases="a1, a2, a3, a4, a5, a6, a7"))

    # Then: the first five survive
    assert reviewed.labels[0].aliases == ("a1", "a2", "a3", "a4", "a5")


def test_a_rejected_sensitive_proposal_leaves_no_label_behind() -> None:
    # Given: a sensitive proposal that review holds back
    # When: review runs over it
    reviewed = _reviewed(_proposal(target_key="health.condition", label="bệnh của tôi"))

    # Then: neither the claim nor its owner-language wording is kept
    assert (reviewed.rejected_count, reviewed.accepted, reviewed.labels) == (1, (), ())


def test_the_first_label_of_a_repeated_key_wins() -> None:
    # Given: the same key proposed twice with different wording
    # When: both proposals are reviewed
    reviewed = _reviewed(_proposal(label="giao diện tối"), _proposal(label="nền tối"))

    # Then: two pieces of evidence are accepted under one label
    assert len(reviewed.accepted) == 2
    assert [item.label for item in reviewed.labels] == ["giao diện tối"]


@pytest.mark.parametrize("field", ["label", "aliases"])
def test_wording_longer_than_the_schema_allows_is_rejected(field: str) -> None:
    # Given: wording far longer than the catalog column expects
    # When: the proposal is validated
    # Then: validation fails instead of storing a huge label
    with pytest.raises(ValidationError):
        EvidenceProposals.model_validate({"preferences": [_proposal(**{field: "x" * 1001})]})
