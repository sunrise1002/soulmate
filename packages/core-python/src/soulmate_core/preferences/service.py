"""Application service for rebuilding versioned derived Personal Models."""

from datetime import UTC, datetime

from soulmate_core.domain import (
    DerivedModel,
    EvidenceRepository,
    PersonalModelRepository,
    TargetKeyAlias,
    TargetKeyAliasRepository,
    TargetKeyAliasStatus,
    UserModelSnapshot,
)
from soulmate_core.keys import KeyAliasMap
from soulmate_core.preferences.aggregation import ALGORITHM_VERSION, aggregate_evidence

KEY_ALIAS_ALGORITHM_SUFFIX = "key-aliases-v1"
ALIASED_ALGORITHM_VERSION = f"{ALGORITHM_VERSION}:{KEY_ALIAS_ALGORITHM_SUFFIX}"


class ModelRebuilder:
    """Rebuild a profile model from its complete evidence history.

    When an alias repository is given, active aliases group keys during
    aggregation; alias writes advance the evidence revision, so stale snapshots
    are detected the same way as evidence changes. Snapshots also record whether
    aliases were applied, so enabling or disabling aliases invalidates them.
    """

    def __init__(
        self,
        evidence: EvidenceRepository,
        models: PersonalModelRepository,
        aliases: TargetKeyAliasRepository | None = None,
    ) -> None:
        self._evidence = evidence
        self._models = models
        self._aliases = aliases

    @property
    def algorithm_version(self) -> str:
        return ALGORITHM_VERSION if self._aliases is None else ALIASED_ALGORITHM_VERSION

    def _active_aliases(self, profile_id: str) -> tuple[TargetKeyAlias, ...]:
        if self._aliases is None:
            return ()
        return self._aliases.list_for_profile(profile_id, TargetKeyAliasStatus.ACTIVE)

    def alias_map(self, profile_id: str) -> KeyAliasMap:
        """Return the active aliases this rebuilder applies, for feature matching."""
        return KeyAliasMap(self._active_aliases(profile_id))

    def rebuild(self, profile_id: str, now: datetime | None = None) -> UserModelSnapshot:
        rebuilt_at = now if now is not None else datetime.now(UTC)
        # Read aliases after the revision: a concurrent alias write then leaves the
        # snapshot marked stale instead of silently fresh.
        items, evidence_revision = self._evidence.list_for_profile_with_revision(profile_id)
        model = aggregate_evidence(items, aliases=self._active_aliases(profile_id))
        return self._models.replace(
            profile_id=profile_id,
            model=model,
            evidence_revision=evidence_revision,
            algorithm_version=self.algorithm_version,
            created_at=rebuilt_at,
        )

    def _fresh_snapshot(self, profile_id: str) -> UserModelSnapshot | None:
        snapshot = self._models.latest_snapshot(profile_id)
        if (
            snapshot is None
            or snapshot.algorithm_version != self.algorithm_version
            or snapshot.evidence_revision != self._evidence.current_revision(profile_id)
        ):
            return None
        return snapshot

    def current(self, profile_id: str, now: datetime | None = None) -> UserModelSnapshot:
        """Return the latest snapshot, rebuilding it when evidence has changed since."""
        snapshot = self._fresh_snapshot(profile_id)
        return snapshot if snapshot is not None else self.rebuild(profile_id, now)

    def current_model(self, profile_id: str) -> DerivedModel:
        """Return up-to-date model content without persisting a new snapshot."""
        snapshot = self._fresh_snapshot(profile_id)
        if snapshot is not None:
            return snapshot.model
        return aggregate_evidence(
            self._evidence.list_for_profile(profile_id),
            aliases=self._active_aliases(profile_id),
        )
