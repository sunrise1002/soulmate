"""Application service for rebuilding versioned derived Personal Models."""

from datetime import UTC, datetime

from soulmate_core.domain import EvidenceRepository, PersonalModelRepository, UserModelSnapshot
from soulmate_core.preferences.aggregation import ALGORITHM_VERSION, aggregate_evidence


class ModelRebuilder:
    """Rebuild a profile model from its complete evidence history."""

    def __init__(self, evidence: EvidenceRepository, models: PersonalModelRepository) -> None:
        self._evidence = evidence
        self._models = models

    def rebuild(self, profile_id: str, now: datetime | None = None) -> UserModelSnapshot:
        rebuilt_at = now if now is not None else datetime.now(UTC)
        items, evidence_revision = self._evidence.list_for_profile_with_revision(profile_id)
        model = aggregate_evidence(items)
        return self._models.replace(
            profile_id=profile_id,
            model=model,
            evidence_revision=evidence_revision,
            algorithm_version=ALGORITHM_VERSION,
            created_at=rebuilt_at,
        )
