"""Embedding port and the null default used until the owner enables a model."""

from soulmate_core.embeddings.port import (
    EmbeddingProvider,
    EmbeddingUnavailableError,
    EmbeddingVector,
    NullEmbedding,
)

__all__ = [
    "EmbeddingProvider",
    "EmbeddingUnavailableError",
    "EmbeddingVector",
    "NullEmbedding",
]
