"""Text-to-vector port kept free of any model runtime.

Adapters live outside the kernel and satisfy this protocol structurally. Callers
must check :attr:`EmbeddingProvider.ready` and treat
:class:`EmbeddingUnavailableError` as "fall back to lexical behavior", never as a
failure worth surfacing to the owner.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

type EmbeddingVector = tuple[float, ...]


class EmbeddingUnavailableError(RuntimeError):
    """No embedding model is loaded, so the caller must use lexical behavior."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turn text into unit-length vectors of one model."""

    @property
    def model_id(self) -> str:
        """Identify the model, so derived vectors can be invalidated when it changes."""

    @property
    def dimensions(self) -> int:
        """Return the vector length, or ``0`` when no model is configured."""

    @property
    def ready(self) -> bool:
        """Report whether :meth:`embed` can run without downloading anything."""

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        """Embed every text in order, raising when no model is available."""

    def release(self) -> None:
        """Drop any loaded model so its memory is returned while idle."""


@dataclass(frozen=True, slots=True)
class NullEmbedding:
    """The default provider: no model, no dependencies, and no network access."""

    @property
    def model_id(self) -> str:
        return "none"

    @property
    def dimensions(self) -> int:
        return 0

    @property
    def ready(self) -> bool:
        return False

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        del texts
        raise EmbeddingUnavailableError("No embedding provider is enabled.")

    def release(self) -> None:
        return None
