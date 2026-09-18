"""Validation and review boundary for conversational evidence proposals."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from soulmate_core.domain import (
    Evidence,
    EvidenceTargetType,
    TargetKeyLabel,
    TargetKeyLabelSource,
)

EXTRACTOR_VERSION = "conversation-evidence-v1"
KEY_REUSE_RULES = """Key rules: when a key in the supplied known keys describes the same concept,
reuse that exact key instead of inventing a variant. Otherwise prefer placing a new key under a
listed namespace. Represent one concept as one signed axis (for example ui.theme.dark with -1..1)
rather than separate keys for each opposite."""
KEY_LABEL_RULES = """Label rules: set label to a short name for the key in the language the user
wrote, and aliases to other wordings the user might use for it, separated by commas. Use empty
strings when the key needs no label."""
LABEL_MAX_LENGTH = 200
ALIAS_MAX_COUNT = 5
SENSITIVE_TERMS = frozenset(
    {"finance", "health", "identity", "medical", "politics", "religion", "sexual"}
)


class ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LabelledProposal(ProposalModel):
    """Shared optional owner-language naming of the target key."""

    label: Annotated[str, Field(max_length=LABEL_MAX_LENGTH)] = ""
    aliases: Annotated[str, Field(max_length=LABEL_MAX_LENGTH * ALIAS_MAX_COUNT)] = ""

    def label_aliases(self) -> tuple[str, ...]:
        """Split the comma-separated aliases, keeping the first of any duplicates."""
        seen: dict[str, None] = {}
        for value in self.aliases.split(","):
            trimmed = value.strip()[:LABEL_MAX_LENGTH]
            if trimmed and trimmed != self.label.strip():
                seen.setdefault(trimmed, None)
        return tuple(seen)[:ALIAS_MAX_COUNT]


class PreferenceProposal(LabelledProposal):
    target_key: Annotated[str, Field(min_length=1, max_length=200)]
    value: Annotated[float, Field(ge=-1.0, le=1.0)]
    strength: Annotated[float, Field(ge=0.0, le=1.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    context: dict[str, JsonValue] = Field(default_factory=dict)


class CategoricalProposal(LabelledProposal):
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
    labels: tuple[TargetKeyLabel, ...] = ()


def extraction_schema() -> dict[str, object]:
    """Return the portable wire schema shared by provider adapter families.

    Provider JSON-schema dialects disagree on unconstrained values, dynamic object
    properties, references, and optional fields. Keep this boundary deliberately
    small; Pydantic still performs the authoritative validation after normalization.
    """

    context_entry: dict[str, object] = {
        "type": "object",
        "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
        "required": ["key", "value"],
        "additionalProperties": False,
    }
    common_properties: dict[str, object] = {
        "target_key": {"type": "string"},
        "strength": {"type": "number"},
        "confidence": {"type": "number"},
        "context": {"type": "array", "items": context_entry},
        "label": {"type": "string"},
        "aliases": {"type": "string"},
    }

    def proposal(value_schema: dict[str, object]) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {**common_properties, "value": value_schema},
            "required": [
                "target_key",
                "value",
                "strength",
                "confidence",
                "context",
                "label",
                "aliases",
            ],
            "additionalProperties": False,
        }

    categorical = proposal({"type": "string"})
    preference = proposal({"type": "number"})
    return {
        "type": "object",
        "properties": {
            "facts": {"type": "array", "items": categorical},
            "preferences": {"type": "array", "items": preference},
            "goals": {"type": "array", "items": categorical},
            "constraints": {"type": "array", "items": categorical},
        },
        "required": ["facts", "preferences", "goals", "constraints"],
        "additionalProperties": False,
    }


def validate_proposals(raw: object) -> EvidenceProposals:
    """Normalize the portable wire representation and validate all provider output."""
    if not isinstance(raw, dict):
        return EvidenceProposals.model_validate(raw)
    normalized: dict[str, object] = dict(raw)
    for group_name in ("facts", "preferences", "goals", "constraints"):
        group = normalized.get(group_name)
        if not isinstance(group, list):
            continue
        normalized_group: list[object] = []
        for proposal in group:
            if not isinstance(proposal, dict):
                normalized_group.append(proposal)
                continue
            normalized_proposal = dict(proposal)
            context = normalized_proposal.get("context")
            if isinstance(context, list):
                normalized_context: dict[str, JsonValue] = {}
                for entry in context:
                    if (
                        isinstance(entry, dict)
                        and isinstance(entry.get("key"), str)
                        and isinstance(entry.get("value"), str)
                    ):
                        normalized_context[entry["key"]] = entry["value"]
                normalized_proposal["context"] = normalized_context
            normalized_group.append(normalized_proposal)
        normalized[group_name] = normalized_group
    return EvidenceProposals.model_validate(normalized)


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
    """Automatically accept ordinary proposals and hold sensitive claims back.

    Labels travel with accepted evidence only, so a rejected sensitive claim never
    leaves its owner-language wording behind in the key catalog.
    """
    accepted: list[Evidence] = []
    labels: dict[tuple[EvidenceTargetType, str], TargetKeyLabel] = {}
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
            label = _label(item, target_type, profile_id, created_at)
            if label is not None:
                labels.setdefault((target_type, item.target_key), label)
    return ReviewedEvidence(tuple(accepted), rejected, tuple(labels.values()))


def _label(
    item: PreferenceProposal | CategoricalProposal,
    target_type: EvidenceTargetType,
    profile_id: str,
    created_at: datetime,
) -> TargetKeyLabel | None:
    """Return the extracted owner-language naming of a key, or ``None`` when absent."""
    label = item.label.strip()[:LABEL_MAX_LENGTH]
    aliases = item.label_aliases()
    if not label and not aliases:
        return None
    return TargetKeyLabel(
        profile_id=profile_id,
        target_type=target_type,
        key=item.target_key,
        label=label or None,
        aliases=aliases,
        source=TargetKeyLabelSource.EXTRACTED,
        created_at=created_at,
        updated_at=created_at,
    )
