"""HTTP adapters for local Ollama and OpenAI-compatible chat APIs."""

import json
from collections.abc import Mapping, Sequence

import httpx

from soulmate_llm_providers.interface import (
    LLMMessage,
    ProviderCapabilities,
    ProviderError,
    ProviderUnavailableError,
    StructuredOutputMode,
)
from soulmate_llm_providers.policy import EgressPolicy

_STRUCTURED_NEGOTIATION_STATUSES = {400, 404, 415, 422, 500, 501, 502}
# Overload and timeout statuses say nothing about format support, so a weaker
# structured mode would only fail the same way; the caller retries later instead.
_TRANSIENT_STATUSES = {408, 429, 503, 504}


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


def _decode_json_object(content: str) -> dict[str, object]:
    candidate = content.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        result = json.loads(candidate)
    except ValueError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("Model provider returned invalid structured output.") from None
        try:
            result = json.loads(candidate[start : end + 1])
        except ValueError as exc:
            raise ProviderError("Model provider returned invalid structured output.") from exc
    if not isinstance(result, dict):
        raise ProviderError("Model provider returned invalid structured output.")
    return result


class _ProviderHTTPError(ProviderError):
    def __init__(self, status_code: int) -> None:
        super().__init__("Model provider request failed.")
        self.status_code = status_code


class _ProviderUnavailableHTTPError(_ProviderHTTPError, ProviderUnavailableError):
    pass


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
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in _TRANSIENT_STATUSES:
                raise _ProviderUnavailableHTTPError(status_code) from exc
            raise _ProviderHTTPError(status_code) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderUnavailableError("Model provider is temporarily unavailable.") from exc
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
        self._active_structured_output_mode: StructuredOutputMode | None = None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            True,
            (StructuredOutputMode.OLLAMA_SCHEMA, StructuredOutputMode.PROMPTED_JSON),
        )

    @property
    def active_structured_output_mode(self) -> StructuredOutputMode | None:
        return self._active_structured_output_mode

    async def generate(self, messages: Sequence[LLMMessage]) -> str:
        data = await self._post(
            {"model": self._model, "messages": _messages(messages), "stream": False}
        )
        return _ollama_content(data)

    async def generate_structured(
        self, messages: Sequence[LLMMessage], schema: Mapping[str, object]
    ) -> dict[str, object]:
        if self._active_structured_output_mode is StructuredOutputMode.PROMPTED_JSON:
            prompted = _with_json_instructions(messages, schema)
            data = await self._post(
                {"model": self._model, "messages": _messages(prompted), "stream": False}
            )
            return _decode_json_object(_ollama_content(data))
        try:
            data = await self._post(
                {
                    "model": self._model,
                    "messages": _messages(messages),
                    "format": dict(schema),
                    "stream": False,
                }
            )
            result = _decode_json_object(_ollama_content(data))
            self._active_structured_output_mode = StructuredOutputMode.OLLAMA_SCHEMA
            return result
        except _ProviderHTTPError as exc:
            if exc.status_code not in _STRUCTURED_NEGOTIATION_STATUSES:
                raise
        prompted = _with_json_instructions(messages, schema)
        data = await self._post(
            {"model": self._model, "messages": _messages(prompted), "stream": False}
        )
        result = _decode_json_object(_ollama_content(data))
        self._active_structured_output_mode = StructuredOutputMode.PROMPTED_JSON
        return result


def _with_json_instructions(
    messages: Sequence[LLMMessage], schema: Mapping[str, object]
) -> tuple[LLMMessage, ...]:
    instruction = (
        "Return only one JSON object matching this schema. Do not use Markdown fences or add "
        f"explanatory text. JSON schema: {json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
    )
    if messages and messages[0].role == "system":
        combined = LLMMessage("system", f"{messages[0].content}\n\n{instruction}")
        return (combined, *messages[1:])
    return (LLMMessage("system", instruction), *messages)


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
        self._active_structured_output_mode: StructuredOutputMode | None = None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            True,
            (
                StructuredOutputMode.JSON_SCHEMA,
                StructuredOutputMode.JSON_OBJECT,
                StructuredOutputMode.PROMPTED_JSON,
            ),
        )

    @property
    def active_structured_output_mode(self) -> StructuredOutputMode | None:
        return self._active_structured_output_mode

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
        strategies: list[
            tuple[
                StructuredOutputMode,
                Sequence[LLMMessage],
                Mapping[str, object] | None,
            ]
        ] = [
            (
                StructuredOutputMode.JSON_SCHEMA,
                messages,
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "evidence_proposals",
                        "strict": True,
                        "schema": schema,
                    },
                },
            ),
            (
                StructuredOutputMode.JSON_OBJECT,
                _with_json_instructions(messages, schema),
                {"type": "json_object"},
            ),
            (StructuredOutputMode.PROMPTED_JSON, _with_json_instructions(messages, schema), None),
        ]
        if self._active_structured_output_mode is not None:
            strategies.sort(key=lambda item: item[0] is not self._active_structured_output_mode)
        last_error: ProviderError | None = None
        for mode, prompted_messages, response_format in strategies:
            try:
                content = await self._completion(prompted_messages, response_format)
                result = _decode_json_object(content)
            except _ProviderHTTPError as exc:
                last_error = exc
                if exc.status_code not in _STRUCTURED_NEGOTIATION_STATUSES:
                    raise
                continue
            except ProviderUnavailableError:
                raise
            except ProviderError as exc:
                last_error = exc
                continue
            self._active_structured_output_mode = mode
            return result
        raise ProviderError("Model provider returned invalid structured output.") from last_error
