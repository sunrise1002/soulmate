"""Known-key filtering signals in chat learning and natural decision extraction."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from soulmate_core.domain import Evidence, EvidenceTargetType, RawEvent
from soulmate_daemon.app import create_app
from soulmate_daemon.config import Settings
from soulmate_daemon.conversation import ConversationService
from soulmate_daemon.key_semantics import enqueue_key_embedding_refresh, refresh_from_payload
from soulmate_llm_providers import FakeLLMProvider

from tests.key_embedding_support import FakeConceptEmbedding

pytestmark = pytest.mark.integration

OWNER_CLIENT = ("127.0.0.1", 50000)
PROFILE_ID = "profile_default"
FILLER_COUNT = 110
KEY_LIMIT = 50


def owner_client(app: FastAPI) -> TestClient:
    return TestClient(app, client=OWNER_CLIENT)


def _seed_confident_fillers(app: FastAPI) -> None:
    """Exceed the send-all threshold with confident keys unrelated to the tests."""
    repositories = app.state.runtime["repositories"]
    now = datetime.now(UTC)
    for index in range(FILLER_COUNT):
        event = RawEvent(
            id=f"event_filler_{index}",
            profile_id=PROFILE_ID,
            source_id=None,
            event_type="synthetic_preference",
            content={},
            created_at=now,
            ingested_at=now,
        )
        repositories.raw_events.add(event)
        repositories.evidence.add(
            Evidence(
                id=f"evidence_filler_{index}",
                profile_id=PROFILE_ID,
                target_type=EvidenceTargetType.PREFERENCE,
                target_key=f"filler.key_{index:03d}",
                value=0.9,
                strength=1.0,
                confidence=1.0,
                context={},
                source_type="explicit_statement",
                source_event_id=event.id,
                extractor_version="synthetic-v1",
                created_at=now,
            )
        )


def _preference_output(*keys: str) -> dict[str, object]:
    return {
        "facts": [],
        "preferences": [
            {
                "target_key": key,
                "value": 0.5,
                "strength": 0.1,
                "confidence": 0.1,
                "context": [],
            }
            for key in keys
        ],
        "goals": [],
        "constraints": [],
    }


def _chat_and_learn(
    client: TestClient,
    app: FastAPI,
    provider: FakeLLMProvider,
    content: str,
    conversation_id: str | None = None,
) -> str:
    payload = {"content": content}
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    response = client.post("/v1/chat", json=payload)
    assert response.status_code == 200
    body = response.json()
    repositories = app.state.runtime["repositories"]
    job = repositories.jobs.get(f"job_extract_{body['user_message_id']}")
    assert job is not None
    asyncio.run(
        ConversationService(
            conversations=repositories.conversations,
            messages=repositories.messages,
            raw_events=repositories.raw_events,
            evidence=repositories.evidence,
            models=repositories.personal_models,
            provider=provider,
            jobs=repositories.jobs,
            aliases=repositories.key_aliases,
            catalog=repositories.key_catalog,
            semantics=app.state.runtime["key_semantics"],
        ).retry_learning(job.payload)
    )
    return str(body["conversation_id"])


def _last_chat_known_keys(provider: FakeLLMProvider) -> dict[str, list[str]]:
    system_prompt = provider.requests[-1][0].content
    return dict(json.loads(system_prompt.split("Known keys by type: ", 1)[1]))


def test_chat_filtering_prefers_same_conversation_keys_and_earlier_words(
    tmp_path: Path,
) -> None:
    # Given: a large model, a key learned in another conversation, and a
    # conversation that learned ui.theme.dark after mentioning spicy food
    provider = FakeLLMProvider(
        responses=["Noted.", "Noted.", "Noted."],
        structured_responses=[
            _preference_output("travel.beach", "food.spicy"),
            _preference_output("ui.theme.dark"),
            _preference_output(),
        ],
    )
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        _seed_confident_fillers(app)
        _chat_and_learn(client, app, provider, "Tôi thích biển")
        conversation_id = _chat_and_learn(
            client, app, provider, "Tôi thích giao diện tối và đồ ăn spicy"
        )

        # When: a follow-up without shared words is learned in the same conversation
        _chat_and_learn(client, app, provider, "Vẫn vậy", conversation_id)

    # Then: recent and earlier-word keys are shared, the other conversation's is not
    known = _last_chat_known_keys(provider)
    assert "ui.theme.dark" in known["preferences"]
    assert "food.spicy" in known["preferences"]
    assert "travel.beach" not in known["preferences"]
    assert len(known["preferences"]) == KEY_LIMIT
    assert {"filler", "travel", "ui.theme", "food"} <= set(known["namespaces"])


def test_chat_filtering_without_signals_uses_confidence_only(tmp_path: Path) -> None:
    # Given: a large model and a low-confidence key learned in another conversation
    provider = FakeLLMProvider(
        responses=["Noted.", "Noted."],
        structured_responses=[_preference_output("ui.theme.dark"), _preference_output()],
    )
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        _seed_confident_fillers(app)
        _chat_and_learn(client, app, provider, "Tôi thích giao diện tối")

        # When: a new conversation with no shared words is learned
        _chat_and_learn(client, app, provider, "Xin chào")

    # Then: the low-confidence key is filtered out but its namespace remains
    known = _last_chat_known_keys(provider)
    assert "ui.theme.dark" not in known["preferences"]
    assert all(key.startswith("filler.") for key in known["preferences"])
    assert "ui.theme" in known["namespaces"]


def _resolve_explicit_decision(client: TestClient, domain: str, key: str) -> None:
    decision = client.post(
        "/v1/decisions",
        json={
            "domain": domain,
            "question": "Synthetic choice",
            "options": [
                {
                    "label": "Yes",
                    "description": "Synthetic yes",
                    "features": {key: 1.0},
                    "feature_confidence": 0.1,
                },
                {
                    "label": "No",
                    "description": "Synthetic no",
                    "features": {key: -1.0},
                    "feature_confidence": 0.1,
                },
            ],
        },
    )
    assert decision.status_code == 201
    body = decision.json()
    resolved = client.post(
        f"/v1/decisions/{body['id']}/resolve",
        json={"chosen_option_id": body["options"][0]["id"]},
    )
    assert resolved.status_code == 201


def test_decision_filtering_prefers_keys_from_same_domain_decisions(tmp_path: Path) -> None:
    # Given: a large model and resolved decisions in two domains
    provider = FakeLLMProvider(
        structured_responses=[
            {
                "options": [
                    {"option_index": 0, "features": {"ui.theme.dark": 1.0}, "confidence": 0.9},
                    {"option_index": 1, "features": {"ui.theme.dark": -1.0}, "confidence": 0.9},
                ]
            }
        ]
    )
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        _seed_confident_fillers(app)
        _resolve_explicit_decision(client, "general", "ui.theme.dark")
        _resolve_explicit_decision(client, "career", "work.remote")

        # When: a natural decision without shared words is created in the same domain
        response = client.post(
            "/v1/decisions",
            json={
                "domain": "General",
                "question": "Tôi thích màu nào hơn",
                "options": [
                    {"label": "Tối", "description": "Nền tối"},
                    {"label": "Sáng", "description": "Nền sáng"},
                ],
            },
        )

    # Then: only the same-domain key is promoted and only preference keys are sent
    assert response.status_code == 201
    known = json.loads(provider.requests[0][1].content)["known_keys"]
    assert set(known) == {"namespaces", "preferences"}
    assert "ui.theme.dark" in known["preferences"]
    assert "work.remote" not in known["preferences"]
    assert len(known["preferences"]) == KEY_LIMIT


def _labelled_output(key: str, label: str) -> dict[str, object]:
    output = _preference_output(key)
    preferences = output["preferences"]
    assert isinstance(preferences, list)
    preferences[0]["label"] = label
    return output


def _refresh_key_embeddings(app: FastAPI) -> None:
    """Run the durable refresh the daemon scheduler would queue in the background."""
    runtime = app.state.runtime
    semantics = runtime["key_semantics"]
    assert semantics is not None
    repositories = runtime["repositories"]
    job = enqueue_key_embedding_refresh(
        repositories.jobs, repositories.evidence, semantics, PROFILE_ID
    )
    assert job is not None
    assert refresh_from_payload(semantics, job.payload).embedded_count > 0


def test_semantic_retrieval_shares_a_key_named_in_another_language(tmp_path: Path) -> None:
    # Given: a large model that learned ui.theme.dark with low confidence from a
    # Vietnamese message, and an embedding model that is installed
    provider = FakeLLMProvider(
        responses=["Noted.", "Noted."],
        structured_responses=[
            _labelled_output("ui.theme.dark", "giao diện tối"),
            _preference_output(),
        ],
    )
    embeddings = FakeConceptEmbedding()
    app = create_app(
        Settings(data_dir=tmp_path / "owner-data"), provider=provider, embeddings=embeddings
    )
    with owner_client(app) as client:
        _seed_confident_fillers(app)
        _chat_and_learn(client, app, provider, "Tôi thích giao diện tối")
        _refresh_key_embeddings(app)

        # When: a new conversation mentions the same topic in Vietnamese only
        _chat_and_learn(client, app, provider, "giao diện tối")

    # Then: the key is shared although no word is shared and confidence is low,
    # which lexical ranking alone could not do
    known = _last_chat_known_keys(provider)
    assert "ui.theme.dark" in known["preferences"]
    assert len(known["preferences"]) == KEY_LIMIT


def test_the_extracted_label_is_stored_for_the_key(tmp_path: Path) -> None:
    # Given: a chat message whose extraction proposes an owner-language label
    provider = FakeLLMProvider(
        responses=["Noted."],
        structured_responses=[_labelled_output("ui.theme.dark", "giao diện tối")],
    )
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        # When: the message is learned
        _chat_and_learn(client, app, provider, "Tôi thích giao diện tối")

    # Then: the catalog keeps the wording the owner used, marked as extracted
    repositories = app.state.runtime["repositories"]
    stored = repositories.key_catalog.get(
        PROFILE_ID, EvidenceTargetType.PREFERENCE, "ui.theme.dark"
    )
    assert stored is not None
    assert (stored.label, stored.source.value) == ("giao diện tối", "extracted")


def test_without_an_embedding_model_no_vector_is_stored(tmp_path: Path) -> None:
    # Given: the default configuration, which enables no embedding model
    provider = FakeLLMProvider(
        responses=["Noted."],
        structured_responses=[_labelled_output("ui.theme.dark", "giao diện tối")],
    )
    app = create_app(Settings(data_dir=tmp_path / "owner-data"), provider=provider)
    with owner_client(app) as client:
        # When: a message is learned
        _chat_and_learn(client, app, provider, "Tôi thích giao diện tối")

    # Then: no key semantics service exists and nothing derived was written
    runtime = app.state.runtime
    assert runtime["key_semantics"] is None
    assert runtime["repositories"].key_embeddings.list_for_model(PROFILE_ID, "bge-m3-int8") == ()
