"""HTTP adapters for local Ollama and OpenAI-compatible chat APIs."""

import json
from collections.abc import Mapping, Sequence

import httpx

from soulmate_llm_providers.interface import LLMMessage, ProviderError
from soulmate_llm_providers.policy import EgressPolicy


def _messages(messages: Sequence[LLMMessage]) -> list[dict[str, str]]:
    return [{"role": item.role, "content": item.content} for item in messages]


def _ollama_content(data: Mapping[str, object]) -> str:
    message = data.get("message")
    if not isinstance(message, dict):
        raise ProviderError("Model provider returned an invalid response.")
    content: object = message.get("content")
    if not isinstance(content, str):
        raise ProviderError("Model provider returned an invalid response.")
    return content


def _openai_content(data: Mapping[str, object]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderError("Model provider returned an invalid response.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProviderError("Model provider returned an invalid response.")
    content: object = message.get("content")
    if not isinstance(content, str):
        raise ProviderError("Model provider returned an invalid response.")
    return content


class _HttpProvider:
    def __init__(
        self,
        *,
        endpoint: str,
        provider_name: str,
        policy: EgressPolicy,
        client: httpx.AsyncClient | None,
    ) -> None:
        self._endpoint = endpoint
        self._provider_name = provider_name
        self._policy = policy
        self._client = client

    async def _post(
        self, payload: Mapping[str, object], headers: Mapping[str, str] | None = None
    ) -> dict[str, object]:
        self._policy.require(
            provider=self._provider_name,
            endpoint=self._endpoint,
            data_classification="personal",
        )
        try:
            if self._client is not None:
                response = await self._client.post(self._endpoint, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(self._endpoint, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("Model provider request failed.") from exc


class OllamaProvider(_HttpProvider):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        policy: EgressPolicy,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model:
            raise ValueError("Ollama model must be configured.")
        super().__init__(
            endpoint=f"{base_url.rstrip('/')}/api/chat",
            provider_name="ollama",
            policy=policy,
            client=client,
        )
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, messages: Sequence[LLMMessage]) -> str:
        data = await self._post(
            {"model": self._model, "messages": _messages(messages), "stream": False}
        )
        return _ollama_content(data)

    async def generate_structured(
        self, messages: Sequence[LLMMessage], schema: Mapping[str, object]
    ) -> dict[str, object]:
        data = await self._post(
            {
                "model": self._model,
                "messages": _messages(messages),
                "format": dict(schema),
                "stream": False,
            }
        )
        try:
            result = json.loads(_ollama_content(data))
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("Model provider returned invalid structured output.") from exc


class OpenAICompatibleProvider(_HttpProvider):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        policy: EgressPolicy,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or not model:
            raise ValueError("OpenAI-compatible base URL and model must be configured.")
        super().__init__(
            endpoint=f"{base_url.rstrip('/')}/chat/completions",
            provider_name="openai_compatible",
            policy=policy,
            client=client,
        )
        self._model = model
        self._headers = {} if api_key is None else {"Authorization": f"Bearer {api_key}"}

    @property
    def model_name(self) -> str:
        return self._model

    async def _completion(
        self, messages: Sequence[LLMMessage], response_format: Mapping[str, object] | None = None
    ) -> str:
        payload: dict[str, object] = {"model": self._model, "messages": _messages(messages)}
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        data = await self._post(payload, self._headers)
        return _openai_content(data)

    async def generate(self, messages: Sequence[LLMMessage]) -> str:
        return await self._completion(messages)

    async def generate_structured(
        self, messages: Sequence[LLMMessage], schema: Mapping[str, object]
    ) -> dict[str, object]:
        content = await self._completion(
            messages,
            {
                "type": "json_schema",
                "json_schema": {"name": "evidence_proposals", "strict": True, "schema": schema},
            },
        )
        try:
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError
            return result
        except ValueError as exc:
            raise ProviderError("Model provider returned invalid structured output.") from exc
