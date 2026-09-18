"""A deterministic concept embedder shared by key semantics tests.

Real multilingual vectors cannot be produced without the pinned model, which no
test may download. This fake keeps the property the product depends on: text
about the same concept lands on the same axis regardless of language, and
opposite concepts land close together, which is why suggestions need review.
"""

from collections.abc import Sequence

from soulmate_core.embeddings import EmbeddingUnavailableError, EmbeddingVector

CONCEPTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("theme", ("dark", "light", "theme", "tối", "sáng", "giao diện", "nền")),
    ("food", ("spicy", "food", "cay", "đồ ăn", "ẩm thực")),
    ("travel", ("beach", "travel", "biển", "du lịch")),
    ("work", ("remote", "office", "work", "làm việc", "từ xa")),
)
OPPOSITES: tuple[tuple[str, str], ...] = (("dark", "light"), ("tối", "sáng"))
DIMENSIONS = len(CONCEPTS) + 1


class FakeConceptEmbedding:
    """Map text onto one concept axis, with a small opposite-facing component."""

    def __init__(self, *, ready: bool = True, failure: Exception | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.releases = 0
        self._ready = ready
        self._failure = failure

    @property
    def model_id(self) -> str:
        return "fake-concept-v1"

    @property
    def dimensions(self) -> int:
        return DIMENSIONS

    @property
    def ready(self) -> bool:
        return self._ready

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        self.calls.append(tuple(texts))
        if self._failure is not None:
            raise self._failure
        if not self._ready:
            raise EmbeddingUnavailableError("The fake model is not installed.")
        return tuple(self._vector(text) for text in texts)

    def release(self) -> None:
        self.releases += 1

    def _vector(self, text: str) -> EmbeddingVector:
        folded = text.casefold()
        values = [0.0] * DIMENSIONS
        for index, (_, terms) in enumerate(CONCEPTS):
            if any(term in folded for term in terms):
                values[index] = 1.0
        if not any(values):
            # Keys of no known concept stay far from every query.
            values[-1] = 1.0
            return tuple(values)
        for left, right in OPPOSITES:
            if left in folded:
                values[-1] = 0.25
            elif right in folded:
                values[-1] = -0.25
        magnitude = sum(value * value for value in values) ** 0.5
        return tuple(value / magnitude for value in values)


class TruncatingEmbedding(FakeConceptEmbedding):
    """A provider that breaks its contract by returning too few vectors."""

    def embed(self, texts: Sequence[str]) -> tuple[EmbeddingVector, ...]:
        return super().embed(texts)[:-1]
