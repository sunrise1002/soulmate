"""Validation and review boundary for conversational evidence proposals."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from soulmate_core.domain import Evidence, EvidenceTargetType

EXTRACTOR_VERSION = "conversation-evidence-v1"
SENSITIVE_TERMS = frozenset(
    {"finance", "health", "identity", "medical", "politics", "religion", "sexual"}
)


class ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreferenceProposal(ProposalModel):
    target_key: Annotated[str, Field(min_length=1, max_length=200)]
    value: Annotated[float, Field(ge=-1.0, le=1.0)]
    strength: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    context: dict[str, JsonValue] = Field(default_factory=dict)


class CategoricalProposal(ProposalModel):
    target_key: Annotated[str, Field(min_length=1, max_length=200)]
    value: JsonValue
    strength: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    context: dict[str, JsonValue] = Field(default_factory=dict)


class EvidenceProposals(ProposalModel):
    facts: list[CategoricalProposal] = Field(default_factory=list, max_length=20)
    preferences: list[PreferenceProposal] = Field(default_factory=list, max_length=20)
    goals: list[CategoricalProposal] = Field(default_factory=list, max_length=20)
    constraints: list[CategoricalProposal] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True, slots=True)
class ReviewedEvidence:
    accepted: tuple[Evidence, ...]
    rejected_count: int


def extraction_schema() -> dict[str, object]:
    return EvidenceProposals.model_json_schema()


def _is_low_risk(target_key: str) -> bool:
    segments = re.split(r"[._-]+", target_key.casefold())
    return not SENSITIVE_TERMS.intersection(segments)


def review_proposals(
    proposals: EvidenceProposals,
    *,
    profile_id: str,
    source_event_id: str,
    source_message_id: str,
    extractor_model: str,
    created_at: datetime,
) -> ReviewedEvidence:
    """Automatically accept ordinary proposals and hold sensitive claims back."""
    accepted: list[Evidence] = []
    rejected = 0
    groups: tuple[
        tuple[EvidenceTargetType, list[PreferenceProposal] | list[CategoricalProposal]], ...
    ] = (
        (EvidenceTargetType.FACT, proposals.facts),
        (EvidenceTargetType.PREFERENCE, proposals.preferences),
        (EvidenceTargetType.GOAL, proposals.goals),
        (EvidenceTargetType.CONSTRAINT, proposals.constraints),
    )
    for target_type, items in groups:
        for item in items:
            if not _is_low_risk(item.target_key):
                rejected += 1
                continue
            accepted.append(
                Evidence(
                    id=f"evidence_{uuid4().hex}",
                    profile_id=profile_id,
                    target_type=target_type,
                    target_key=item.target_key,
                    value=item.value,
                    strength=item.strength,
                    confidence=item.confidence,
                    context=dict(item.context),
                    source_type="explicit_statement",
                    source_event_id=source_event_id,
                    extractor_version=EXTRACTOR_VERSION,
                    created_at=created_at,
                    extractor_model=extractor_model,
                    source_message_id=source_message_id,
                )
            )
    return ReviewedEvidence(tuple(accepted), rejected)
