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
