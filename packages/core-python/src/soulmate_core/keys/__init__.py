"""Target key normalization, canonical key aliasing, and key similarity."""

from soulmate_core.keys.aliases import KeyAliasMap, ResolvedKey
from soulmate_core.keys.normalization import KEY_NORMALIZER_VERSION, normalize_key
from soulmate_core.keys.proposals import normalized_or_none, propose_normalized_aliases
from soulmate_core.keys.semantics import (
    DEFAULT_SEMANTIC_ALIAS_LIMIT,
    DEFAULT_SEMANTIC_ALIAS_THRESHOLD,
    KEY_EMBEDDING_TEXT_VERSION,
    SEMANTIC_ALIAS_VERSION,
    EmbeddedKey,
    KeyVector,
    SemanticAliasProposal,
    cosine_similarity,
    key_embedding_text,
    key_text_hash,
    propose_semantic_aliases,
    semantic_key_scores,
)

__all__ = [
    "DEFAULT_SEMANTIC_ALIAS_LIMIT",
    "DEFAULT_SEMANTIC_ALIAS_THRESHOLD",
    "KEY_EMBEDDING_TEXT_VERSION",
    "KEY_NORMALIZER_VERSION",
    "SEMANTIC_ALIAS_VERSION",
    "EmbeddedKey",
    "KeyAliasMap",
    "KeyVector",
    "ResolvedKey",
    "SemanticAliasProposal",
    "cosine_similarity",
    "key_embedding_text",
    "key_text_hash",
    "normalize_key",
    "normalized_or_none",
    "propose_normalized_aliases",
    "propose_semantic_aliases",
    "semantic_key_scores",
]
