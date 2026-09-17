"""Provider-neutral LLM contracts."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProviderError(RuntimeError):
    """A provider request or response failed without exposing private payloads."""


class StructuredOutputMode(StrEnum):
    """Provider strategies ordered from strongest to most portable."""

    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPTED_JSON = "prompted_json"
    OLLAMA_SCHEMA = "ollama_schema"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Capabilities an adapter can negotiate without leaking provider details inward."""

    text_generation: bool
    structured_output_modes: tuple[StructuredOutputMode, ...]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: str
    content: str


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    @property
    def active_structured_output_mode(self) -> StructuredOutputMode | None: ...

    async def generate(self, messages: Sequence[LLMMessage]) -> str: ...

    async def generate_structured(
        self, messages: Sequence[LLMMessage], schema: Mapping[str, object]
    ) -> dict[str, object]: ...
