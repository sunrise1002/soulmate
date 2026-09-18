"""Similarity over key vectors: embedded text, retrieval scores, and suggestions.

The kernel never computes a vector; adapters do that through the embedding port.
Everything here is pure arithmetic over vectors supplied by the caller, so the
scoring mix and the suggestion rules stay testable without a model.

Semantic similarity may never merge keys automatically. The P0 spike measured
every opposite key pair as more similar to its opposite than a typical correct
message-to-key match, so :func:`propose_semantic_aliases` only ever produces
``suggested`` aliases for owner review.
"""

import hashlib
import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from soulmate_core.domain.models import (
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_core.keys.proposals import normalized_or_none

KEY_EMBEDDING_TEXT_VERSION = "key-text-v1"
SEMANTIC_ALIAS_VERSION = f"semantic-alias-v1:{KEY_EMBEDDING_TEXT_VERSION}"
DEFAULT_SEMANTIC_ALIAS_THRESHOLD = 0.85
DEFAULT_SEMANTIC_ALIAS_LIMIT = 20

type KeyVector = tuple[float, ...]


@dataclass(frozen=True, slots=True)
class EmbeddedKey:
    """One target key with the vector of its embedded text."""

    target_type: EvidenceTargetType
    key: str
    vector: KeyVector

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("An embedded key must name a target key.")
        if not self.vector:
            raise ValueError("An embedded key must carry a vector.")


@dataclass(frozen=True, slots=True)
class SemanticAliasProposal:
    """A suggested merge and the similarity that produced it."""

    alias: TargetKeyAlias
    similarity: float


def key_embedding_text(key: str, label: str | None = None, aliases: Sequence[str] = ()) -> str:
    """Return the text embedded for a key, as the P0 spike measured it.

    Dotted segments become words so a multilingual model sees language, and the
    owner label and catalog aliases follow after ``" | "`` when they exist. Labels
    are a quality improvement, not a prerequisite: key text alone already reached
    97.7% Vietnamese recall inside the shared key budget.
    """
    words = " ".join(key.replace(".", " ").replace("_", " ").split())
    if not words:
        raise ValueError("Target key must not be empty.")
    extra = [value.strip() for value in (label or "", *aliases) if value.strip()]
    return " | ".join([words, *extra])


def key_text_hash(text: str) -> str:
    """Hash embedded text so a changed label invalidates exactly its own vector."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cosine_similarity(left: KeyVector, right: KeyVector) -> float:
    """Return the cosine of two non-empty vectors of equal length, clamped to [-1, 1]."""
    if not left or not right:
        raise ValueError("Cosine similarity needs non-empty vectors.")
    if len(left) != len(right):
        raise ValueError("Cosine similarity needs vectors of equal length.")
    magnitude = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if magnitude == 0.0:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    return max(-1.0, min(1.0, dot / magnitude))


def semantic_key_scores(query: KeyVector, keys: Sequence[EmbeddedKey]) -> dict[str, float]:
    """Score each key name by cosine similarity to ``query``, keeping the best score.

    Vectors of a different length belong to another model and are ignored instead
    of failing, because a stale row must never break key retrieval.
    """
    if not query:
        raise ValueError("Semantic scoring needs a non-empty query vector.")
    scores: dict[str, float] = {}
    for item in keys:
        if len(item.vector) != len(query):
            continue
        score = cosine_similarity(query, item.vector)
        if item.key not in scores or score > scores[item.key]:
            scores[item.key] = score
    return scores


def _ordered_candidates(
    keys: Sequence[EmbeddedKey],
    threshold: float,
    reviewed: Collection[tuple[EvidenceTargetType, str]],
) -> list[tuple[float, EmbeddedKey, EmbeddedKey]]:
    candidates: list[tuple[float, EmbeddedKey, EmbeddedKey]] = []
    for index, canonical in enumerate(keys):
        for alias in keys[index + 1 :]:
            if canonical.target_type is not alias.target_type or canonical.key == alias.key:
                continue
            if (alias.target_type, alias.key) in reviewed:
                continue
            if len(canonical.vector) != len(alias.vector):
                continue
            normalized = normalized_or_none(canonical.key)
            if normalized is not None and normalized == normalized_or_none(alias.key):
                continue  # Equal normalized forms merge automatically instead.
            similarity = cosine_similarity(canonical.vector, alias.vector)
            if similarity >= threshold:
                candidates.append((similarity, canonical, alias))
    candidates.sort(key=lambda item: (-item[0], item[2].key, item[1].key))
    return candidates


def propose_semantic_aliases(
    profile_id: str,
    keys: Sequence[EmbeddedKey],
    aliases: Sequence[TargetKeyAlias],
    now: datetime,
    *,
    threshold: float = DEFAULT_SEMANTIC_ALIAS_THRESHOLD,
    limit: int = DEFAULT_SEMANTIC_ALIAS_LIMIT,
) -> tuple[SemanticAliasProposal, ...]:
    """Return ``suggested`` aliases for key pairs that look like the same concept.

    ``keys`` should be ordered by first use, because the earlier key becomes the
    canonical one and the later key becomes the alias. Keys that already have an
    alias row of any status are skipped, so owner rejections stay rejected, and
    each key takes part in at most one suggestion per run so a review decision
    never depends on another suggestion. Polarity is always ``+1``: only the owner
    may invert a pair, since a high similarity cannot tell "same" from "opposite".
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("The semantic alias threshold must be between zero and one.")
    if limit < 0:
        raise ValueError("The semantic alias limit must not be negative.")
    if limit == 0 or len(keys) < 2:
        return ()
    reviewed = {
        (alias.target_type, alias.alias_key) for alias in aliases if alias.profile_id == profile_id
    }
    proposals: list[SemanticAliasProposal] = []
    used: set[tuple[EvidenceTargetType, str]] = set()
    for similarity, canonical, alias in _ordered_candidates(keys, threshold, reviewed):
        identities = {(alias.target_type, alias.key), (canonical.target_type, canonical.key)}
        if identities & used:
            continue
        used |= identities
        proposals.append(
            SemanticAliasProposal(
                alias=TargetKeyAlias(
                    profile_id=profile_id,
                    target_type=alias.target_type,
                    alias_key=alias.key,
                    canonical_key=canonical.key,
                    polarity=1,
                    method=TargetKeyAliasMethod.SEMANTIC,
                    status=TargetKeyAliasStatus.SUGGESTED,
                    algorithm_version=SEMANTIC_ALIAS_VERSION,
                    created_at=now,
                    updated_at=now,
                    similarity=similarity,
                ),
                similarity=similarity,
            )
        )
        if len(proposals) == limit:
            break
    return tuple(proposals)
