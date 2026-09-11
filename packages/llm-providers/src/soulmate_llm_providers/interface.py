"""Provider-neutral LLM contracts."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class ProviderError(RuntimeError):
    """A provider request or response failed without exposing private payloads."""


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str
    content: str


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate(self, messages: Sequence[LLMMessage]) -> str: ...

    async def generate_structured(
        self, messages: Sequence[LLMMessage], schema: Mapping[str, object]
    ) -> dict[str, object]: ...
