"""Deterministic provider used by offline unit and integration tests."""

from collections import deque
from collections.abc import Mapping, Sequence

from soulmate_llm_providers.interface import LLMMessage, ProviderError


class FakeLLMProvider:
    def __init__(
        self,
        *,
        responses: Sequence[str] = (),
        structured_responses: Sequence[Mapping[str, object]] = (),
        model_name: str = "fake-model-v1",
    ) -> None:
        self._responses = deque(responses)
        self._structured_responses = deque(dict(item) for item in structured_responses)
        self._model_name = model_name
        self.requests: list[tuple[LLMMessage, ...]] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, messages: Sequence[LLMMessage]) -> str:
        self.requests.append(tuple(messages))
        if not self._responses:
            raise ProviderError("Fake provider has no text response configured.")
        return self._responses.popleft()

    async def generate_structured(
        self, messages: Sequence[LLMMessage], schema: Mapping[str, object]
    ) -> dict[str, object]:
        del schema
        self.requests.append(tuple(messages))
        if not self._structured_responses:
            raise ProviderError("Fake provider has no structured response configured.")
        return self._structured_responses.popleft()
