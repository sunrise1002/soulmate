"""Owner-written names for target keys.

Extraction proposes a label in the language the owner used; this module is the
only way the owner replaces one. A label is personal wording, so it is never put
in an audit record, and it is only accepted for a key that evidence already uses,
which keeps the catalog pruneable together with the evidence behind it.
"""

from datetime import datetime

from soulmate_core.domain import (
    EvidenceRepository,
    EvidenceTargetType,
    TargetKeyCatalogRepository,
    TargetKeyLabel,
    TargetKeyLabelSource,
)

from soulmate_daemon.extraction import ALIAS_MAX_COUNT, LABEL_MAX_LENGTH


class KeyLabelError(RuntimeError):
    """An owner label was rejected because it names nothing or nothing to name."""


def clean_aliases(values: tuple[str, ...], label: str | None) -> tuple[str, ...]:
    """Trim, deduplicate, and cap aliases the same way extraction does."""
    kept: dict[str, None] = {}
    for value in values:
        trimmed = value.strip()[:LABEL_MAX_LENGTH]
        if trimmed and trimmed != label:
            kept.setdefault(trimmed, None)
    return tuple(kept)[:ALIAS_MAX_COUNT]


class KeyLabelService:
    """Read and write the owner-language names of keys the model already holds."""

    def __init__(self, evidence: EvidenceRepository, catalog: TargetKeyCatalogRepository) -> None:
        self._evidence = evidence
        self._catalog = catalog

    def list_for_profile(self, profile_id: str) -> tuple[TargetKeyLabel, ...]:
        return self._catalog.list_for_profile(profile_id)

    def set_label(
        self,
        *,
        profile_id: str,
        target_type: EvidenceTargetType,
        key: str,
        label: str | None,
        aliases: tuple[str, ...],
        now: datetime,
    ) -> TargetKeyLabel:
        """Store an owner label, replacing whatever extraction proposed for the key."""
        self._require_used(profile_id, target_type, key)
        trimmed = None if label is None or not label.strip() else label.strip()[:LABEL_MAX_LENGTH]
        cleaned = clean_aliases(aliases, trimmed)
        if trimmed is None and not cleaned:
            raise KeyLabelError("A key label needs a name or at least one alias.")
        existing = self._catalog.get(profile_id, target_type, key)
        return self._catalog.upsert(
            TargetKeyLabel(
                profile_id=profile_id,
                target_type=target_type,
                key=key,
                label=trimmed,
                aliases=cleaned,
                source=TargetKeyLabelSource.OWNER,
                created_at=now if existing is None else existing.created_at,
                updated_at=now,
            )
        )

    def remove(self, profile_id: str, target_type: EvidenceTargetType, key: str) -> None:
        """Drop the owner label so extraction may propose one again."""
        if not self._catalog.remove(profile_id, target_type, key):
            raise KeyError(key)

    def _require_used(self, profile_id: str, target_type: EvidenceTargetType, key: str) -> None:
        used = any(
            item.target_type is target_type
            for item in self._evidence.list_for_target(profile_id, key)
        )
        if not used:
            raise KeyError(key)
