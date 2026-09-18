"""Provider adapter and privacy policy behavior."""

import asyncio
import json

import httpx
import pytest
from soulmate_llm_providers import (
    EgressDeniedError,
    EgressPolicy,
    LLMMessage,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderUnavailableError,
    StructuredOutputMode,
)


def test_strict_local_policy_rejects_external_provider_endpoint() -> None:
    policy = EgressPolicy("strict_local")
    assert policy.can_send(
        provider="ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
        data_classification="personal",
    )
    with pytest.raises(EgressDeniedError):
        policy.require(
            provider="openai_compatible",
            endpoint="https://models.example.test/v1/chat/completions",
            data_classification="personal",
        )


def test_hybrid_policy_requires_tls_for_nonlocal_endpoint() -> None:
    policy = EgressPolicy("hybrid")
    assert policy.can_send(
        provider="custom", endpoint="https://models.example.test", data_classification="personal"
    )
    assert not policy.can_send(
        provider="custom", endpoint="http://models.example.test", data_classification="personal"
    )


def test_ollama_adapter_parses_text_and_structured_responses() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        content = '{"preferences":[]}' if "format" in payload else "Local response"
        return httpx.Response(200, json={"message": {"content": content}})

    async def exercise() -> tuple[str, dict[str, object]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaProvider(
                base_url="http://127.0.0.1:11434",
                model="synthetic-local",
                policy=EgressPolicy("strict_local"),
                client=client,
            )
            text = await provider.generate([LLMMessage("user", "Synthetic message")])
            structured = await provider.generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )
            return text, structured

    text, structured = asyncio.run(exercise())
    assert text == "Local response"
    assert structured == {"preferences": []}
    assert [request.url.path for request in requests] == ["/api/chat", "/api/chat"]


def test_openai_compatible_adapter_sends_schema_and_authorization() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer synthetic-secret"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"facts":[]}'}}]},
        )

    async def exercise() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://models.example.test/v1",
                model="synthetic-model",
                api_key="synthetic-secret",
                policy=EgressPolicy("hybrid"),
                client=client,
            )
            return await provider.generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )

    assert asyncio.run(exercise()) == {"facts": []}
    assert received["model"] == "synthetic-model"
    assert received["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "evidence_proposals",
            "strict": True,
            "schema": {"type": "object"},
        },
    }


def test_openai_compatible_adapter_negotiates_json_object_fallback() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict[str, object] = json.loads(request.content)
        requests.append(payload)
        response_format = payload.get("response_format")
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": "unsupported schema"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"facts":[]}'}}]},
        )

    async def exercise() -> tuple[
        dict[str, object], dict[str, object], StructuredOutputMode | None
    ]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://models.example.test/v1",
                model="synthetic-model",
                api_key=None,
                policy=EgressPolicy("hybrid"),
                client=client,
            )
            result = await provider.generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )
            cached = await provider.generate_structured(
                [LLMMessage("user", "Second synthetic message")], {"type": "object"}
            )
            return result, cached, provider.active_structured_output_mode

    result, cached, mode = asyncio.run(exercise())
    assert result == {"facts": []}
    assert cached == {"facts": []}
    assert mode is StructuredOutputMode.JSON_OBJECT
    assert len(requests) == 3
    assert requests[1]["response_format"] == {"type": "json_object"}
    assert requests[2]["response_format"] == {"type": "json_object"}
    request_messages = requests[1]["messages"]
    assert isinstance(request_messages, list)
    assert "JSON schema" in request_messages[0]["content"]


def test_openai_compatible_adapter_falls_back_to_prompted_json() -> None:
    formats: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict[str, object] = json.loads(request.content)
        formats.append(payload.get("response_format"))
        if "response_format" in payload:
            return httpx.Response(422, json={"error": {"message": "unsupported format"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '```json\n{"preferences": []}\n```'}}]},
        )

    async def exercise() -> tuple[dict[str, object], StructuredOutputMode | None]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://models.example.test/v1",
                model="synthetic-model",
                policy=EgressPolicy("hybrid"),
                client=client,
            )
            result = await provider.generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )
            return result, provider.active_structured_output_mode

    result, mode = asyncio.run(exercise())
    assert result == {"preferences": []}
    assert mode is StructuredOutputMode.PROMPTED_JSON
    assert formats == [
        {
            "type": "json_schema",
            "json_schema": {
                "name": "evidence_proposals",
                "strict": True,
                "schema": {"type": "object"},
            },
        },
        {"type": "json_object"},
        None,
    ]


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_openai_compatible_adapter_does_not_negotiate_auth_or_rate_errors(
    status_code: int,
) -> None:
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(status_code, json={"error": {"message": "denied"}})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                base_url="https://models.example.test/v1",
                model="synthetic-model",
                policy=EgressPolicy("hybrid"),
                client=client,
            )
            await provider.generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )

    with pytest.raises(ProviderError):
        asyncio.run(exercise())
    assert request_count == 1


def _openai_provider(client: httpx.AsyncClient) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://models.example.test/v1",
        model="synthetic-model",
        policy=EgressPolicy("hybrid"),
        client=client,
    )


@pytest.mark.parametrize("status_code", [408, 429, 503, 504])
def test_openai_compatible_adapter_reports_transient_status_without_fallback(
    status_code: int,
) -> None:
    # Given: a provider that is overloaded for every structured mode
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(status_code, json={"error": {"message": "high demand"}})

    async def exercise() -> OpenAICompatibleProvider:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = _openai_provider(client)
            with pytest.raises(ProviderUnavailableError, match="request failed"):
                await provider.generate_structured(
                    [LLMMessage("user", "Synthetic message")], {"type": "object"}
                )
            return provider

    # When: structured output is requested
    provider = asyncio.run(exercise())

    # Then: the overload surfaces once and no weaker mode is negotiated or cached
    assert request_count == 1
    assert provider.active_structured_output_mode is None


def test_openai_compatible_adapter_still_negotiates_after_server_error() -> None:
    # Given: a server that answers 500 to json_schema but supports json_object
    formats: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict[str, object] = json.loads(request.content)
        response_format = payload.get("response_format")
        formats.append(response_format)
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            return httpx.Response(500, json={"error": {"message": "schema crashed"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"facts":[]}'}}]})

    async def exercise() -> tuple[dict[str, object], StructuredOutputMode | None]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = _openai_provider(client)
            result = await provider.generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )
            return result, provider.active_structured_output_mode

    # When: structured output is requested
    result, mode = asyncio.run(exercise())

    # Then: the 500 is treated as a format problem, not an overload
    assert result == {"facts": []}
    assert mode is StructuredOutputMode.JSON_OBJECT
    assert len(formats) == 2


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")],
    ids=["timeout", "connect"],
)
def test_openai_compatible_adapter_reports_unreachable_provider_without_fallback(
    error: httpx.HTTPError,
) -> None:
    # Given: a provider that times out or cannot be reached
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise error

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await _openai_provider(client).generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )

    # When / Then: the failure is transient and only one request is made
    with pytest.raises(ProviderUnavailableError, match="temporarily unavailable"):
        asyncio.run(exercise())
    assert request_count == 1


def test_openai_compatible_adapter_auth_error_is_not_transient() -> None:
    # Given: a provider rejecting the credential
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "denied"}})

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await _openai_provider(client).generate_structured(
                [LLMMessage("user", "Synthetic message")], {"type": "object"}
            )

    # When: structured output is requested
    with pytest.raises(ProviderError) as caught:
        asyncio.run(exercise())

    # Then: retrying later would not help, so it is not reported as unavailable
    assert not isinstance(caught.value, ProviderUnavailableError)
    assert str(caught.value) == "Model provider request failed."


def test_openai_compatible_adapter_keeps_cached_mode_during_overload() -> None:
    # Given: json_object was negotiated, then the provider becomes overloaded
    formats: list[object] = []
    overloaded = False

    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict[str, object] = json.loads(request.content)
        response_format = payload.get("response_format")
        formats.append(response_format)
        if overloaded:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"facts":[]}'}}]})

    async def exercise() -> StructuredOutputMode | None:
        nonlocal overloaded
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = _openai_provider(client)
            await provider.generate_structured([LLMMessage("user", "First")], {"type": "object"})
            overloaded = True
            formats.clear()
            with pytest.raises(ProviderUnavailableError):
                await provider.generate_structured(
                    [LLMMessage("user", "Second")], {"type": "object"}
                )
            return provider.active_structured_output_mode

    # When: the next request meets the overload
    mode = asyncio.run(exercise())

    # Then: only the cached mode was tried and it stays cached
    assert formats == [{"type": "json_object"}]
    assert mode is StructuredOutputMode.JSON_OBJECT


def test_ollama_adapter_reports_overload_without_prompted_fallback() -> None:
    # Given: a local Ollama server that is overloaded
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(503, json={"error": "busy"})

    async def exercise() -> StructuredOutputMode | None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OllamaProvider(
                base_url="http://127.0.0.1:11434",
                model="synthetic-local",
                policy=EgressPolicy("strict_local"),
                client=client,
            )
            with pytest.raises(ProviderUnavailableError):
                await provider.generate_structured(
                    [LLMMessage("user", "Synthetic message")], {"type": "object"}
                )
            return provider.active_structured_output_mode

    # When: structured output is requested
    mode = asyncio.run(exercise())

    # Then: prompted JSON is not attempted or cached
    assert request_count == 1
    assert mode is None
