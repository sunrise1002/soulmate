"""Decision creation, prediction, and resolution application workflow."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from soulmate_core.decisions import (
    DecisionAdvisor,
    DecisionPredictor,
    OutcomeHistory,
    ResolvedDecision,
    resolution_evidence,
)
from soulmate_core.domain import (
    DecisionAdvice,
    DecisionEvent,
    DecisionOption,
    DecisionOutcome,
    DecisionPrediction,
    DecisionRepository,
    DecisionResolution,
    DecisionStatus,
    Evidence,
    EvidenceRepository,
    OutcomeRepository,
    PersonalModelRepository,
    RawEvent,
    RawEventRepository,
)
from soulmate_core.preferences import ModelRebuilder
from soulmate_llm_providers import LLMMessage, LLMProvider

FEATURE_EXTRACTION_PROMPT = """Extract comparable preference features for each decision option.
Use stable dotted English keys that can match Personal Model preferences. Values must be normalized
from -1 (feature strongly absent/opposed) to 1 (feature strongly present), using 0 when neutral.
Return every option index exactly once. Do not make a choice or provide advice."""


class ExtractedOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_index: int = Field(ge=0)
    features: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_features(self) -> "ExtractedOption":
        if not self.features:
            raise ValueError("Extracted option features must not be empty.")
        if any(not key.strip() or not -1.0 <= value <= 1.0 for key, value in self.features.items()):
            raise ValueError("Extracted feature values must be between -1 and 1.")
        return self


class FeatureExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    options: list[ExtractedOption]


@dataclass(frozen=True, slots=True)
class DecisionOptionInput:
    label: str
    description: str
    features: dict[str, float]
    feature_confidence: float | None


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    resolution: DecisionResolution
    evidence: tuple[Evidence, ...]
    snapshot_version: int


class DecisionService:
    def __init__(
        self,
        *,
        decisions: DecisionRepository,
        raw_events: RawEventRepository,
        evidence: EvidenceRepository,
        models: PersonalModelRepository,
        outcomes: OutcomeRepository,
        provider: LLMProvider | None,
    ) -> None:
        self._decisions = decisions
        self._raw_events = raw_events
        self._evidence = evidence
        self._models = models
        self._outcomes = outcomes
        self._provider = provider

    async def create(
        self,
        *,
        profile_id: str,
        domain: str,
        question: str,
        context: dict[str, object],
        option_inputs: tuple[DecisionOptionInput, ...],
    ) -> tuple[DecisionEvent, tuple[DecisionOption, ...]]:
        extracted: dict[int, ExtractedOption] = {}
        missing = [index for index, item in enumerate(option_inputs) if not item.features]
        if missing:
            if self._provider is None:
                raise RuntimeError("A model provider is required for natural option extraction.")
            raw = await self._provider.generate_structured(
                [
                    LLMMessage("system", FEATURE_EXTRACTION_PROMPT),
                    LLMMessage(
                        "user",
                        json.dumps(
                            {
                                "domain": domain,
                                "question": question,
                                "options": [
                                    {
                                        "option_index": index,
                                        "label": item.label,
                                        "description": item.description,
                                    }
                                    for index, item in enumerate(option_inputs)
                                ],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                ],
                FeatureExtraction.model_json_schema(),
            )
            extraction = FeatureExtraction.model_validate(raw)
            extracted = {item.option_index: item for item in extraction.options}
            if len(extraction.options) != len(option_inputs) or set(extracted) != set(
                range(len(option_inputs))
            ):
                raise ValueError(
                    "Feature extraction must return every decision option exactly once."
                )

        now = datetime.now(UTC)
        decision_id = f"decision_{uuid4().hex}"
        decision = DecisionEvent(
            id=decision_id,
            profile_id=profile_id,
            domain=domain,
            question=question,
            context=context,
            status=DecisionStatus.OPEN,
            created_at=now,
        )
        options = tuple(
            DecisionOption(
                id=f"option_{uuid4().hex}",
                decision_id=decision_id,
                label=item.label,
                description=item.description,
                features=item.features or extracted[index].features,
                feature_confidence=(
                    item.feature_confidence
                    if item.feature_confidence is not None
                    else extracted[index].confidence
                    if index in extracted
                    else 1.0
                ),
            )
            for index, item in enumerate(option_inputs)
        )
        self._decisions.add(decision, options)
        return decision, options

    def predict(self, profile_id: str, decision_id: str) -> DecisionPrediction:
        stored = self._decisions.get(decision_id)
        if stored is None or stored[0].profile_id != profile_id:
            raise KeyError(decision_id)
        decision, options = stored
        if decision.status is DecisionStatus.RESOLVED:
            raise ValueError("Resolved decisions cannot receive new predictions.")
        now = datetime.now(UTC)
        snapshot = self._models.latest_snapshot(profile_id)
        evidence_revision = self._evidence.current_revision(profile_id)
        if snapshot is None or snapshot.evidence_revision != evidence_revision:
            snapshot = ModelRebuilder(self._evidence, self._models).rebuild(profile_id, now)
        history = tuple(
            ResolvedDecision(item, historical_options, resolution)
            for item, historical_options, resolution in self._decisions.list_resolved(profile_id)
        )
        prediction = DecisionPredictor().predict(
            prediction_id=f"prediction_{uuid4().hex}",
            decision=decision,
            options=options,
            snapshot=snapshot,
            history=history,
            created_at=now,
        )
        self._decisions.add_prediction(prediction)
        return prediction

    def resolve(self, profile_id: str, decision_id: str, chosen_option_id: str) -> ResolutionResult:
        stored = self._decisions.get(decision_id)
        if stored is None or stored[0].profile_id != profile_id:
            raise KeyError(decision_id)
        decision, options = stored
        if decision.status is DecisionStatus.RESOLVED:
            raise ValueError("Decision has already been resolved.")
        if all(item.id != chosen_option_id for item in options):
            raise KeyError(chosen_option_id)
        now = datetime.now(UTC)
        resolution_id = f"resolution_{uuid4().hex}"
        event = RawEvent(
            id=f"event_{uuid4().hex}",
            profile_id=profile_id,
            source_id=None,
            event_type="decision_resolution",
            content={"decision_id": decision_id, "chosen_option_id": chosen_option_id},
            created_at=now,
            ingested_at=now,
        )
        resolution = DecisionResolution(
            id=resolution_id,
            decision_id=decision_id,
            chosen_option_id=chosen_option_id,
            source_event_id=event.id,
            created_at=now,
        )
        learned = resolution_evidence(
            resolution=resolution,
            decision=decision,
            options=options,
            profile_id=profile_id,
            created_at=now,
        )
        self._raw_events.add(event)
        self._decisions.resolve(resolution)
        for item in learned:
            self._evidence.add(item)
        snapshot = ModelRebuilder(self._evidence, self._models).rebuild(profile_id, now)
        return ResolutionResult(resolution, learned, snapshot.version)

    def record_outcome(
        self,
        profile_id: str,
        decision_id: str,
        satisfaction: float,
        regret: bool,
        notes: str | None,
    ) -> DecisionOutcome:
        stored = self._decisions.get(decision_id)
        if stored is None or stored[0].profile_id != profile_id:
            raise KeyError(decision_id)
        if stored[0].status is not DecisionStatus.RESOLVED:
            raise ValueError("An outcome can be recorded only after the decision is resolved.")
        if self._outcomes.get_for_decision(decision_id) is not None:
            raise ValueError("An outcome has already been recorded for this decision.")
        now = datetime.now(UTC)
        normalized_notes = notes.strip() if notes is not None else None
        event = RawEvent(
            id=f"event_{uuid4().hex}",
            profile_id=profile_id,
            source_id=None,
            event_type="decision_outcome",
            content={
                "decision_id": decision_id,
                "satisfaction": satisfaction,
                "regret": regret,
                "notes": normalized_notes,
            },
            created_at=now,
            ingested_at=now,
        )
        outcome = DecisionOutcome(
            id=f"outcome_{uuid4().hex}",
            decision_id=decision_id,
            profile_id=profile_id,
            satisfaction=satisfaction,
            regret=regret,
            notes=normalized_notes,
            source_event_id=event.id,
            created_at=now,
        )
        self._raw_events.add(event)
        self._outcomes.add(outcome)
        return outcome

    def advise(self, profile_id: str, decision_id: str) -> DecisionAdvice:
        stored = self._decisions.get(decision_id)
        if stored is None or stored[0].profile_id != profile_id:
            raise KeyError(decision_id)
        decision, options = stored
        if decision.status is DecisionStatus.RESOLVED:
            raise ValueError("Resolved decisions cannot receive new advice.")
        snapshot = self._models.latest_snapshot(profile_id)
        evidence_revision = self._evidence.current_revision(profile_id)
        if snapshot is None or snapshot.evidence_revision != evidence_revision:
            snapshot = ModelRebuilder(self._evidence, self._models).rebuild(
                profile_id, datetime.now(UTC)
            )
        prediction = self._decisions.latest_prediction(decision_id)
        if prediction is None or prediction.model_snapshot_version != snapshot.version:
            prediction = self.predict(profile_id, decision_id)
        resolved = {
            item.id: ResolvedDecision(item, historical_options, resolution)
            for item, historical_options, resolution in self._decisions.list_resolved(profile_id)
        }
        history = tuple(
            OutcomeHistory(resolved[item.decision_id], item)
            for item in self._outcomes.list_for_profile(profile_id)
            if item.decision_id in resolved
        )
        advice = DecisionAdvisor().advise(
            advice_id=f"advice_{uuid4().hex}",
            decision=decision,
            options=options,
            prediction=prediction,
            snapshot=snapshot,
            outcome_history=history,
            created_at=datetime.now(UTC),
        )
        self._decisions.add_advice(advice)
        return advice

    def delete_outcome(self, profile_id: str, decision_id: str) -> DecisionOutcome:
        stored = self._decisions.get(decision_id)
        outcome = self._outcomes.get_for_decision(decision_id)
        if stored is None or stored[0].profile_id != profile_id or outcome is None:
            raise KeyError(decision_id)
        if not self._outcomes.remove_for_decision(decision_id):
            raise KeyError(decision_id)
        return outcome
