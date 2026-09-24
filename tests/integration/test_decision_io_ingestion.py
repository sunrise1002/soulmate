"""Decision I/O ingestion: provenance, idempotency, consent, and authorization."""

from pathlib import Path

import pytest

from .decision_io_support import (
    ALL_SCOPES,
    INTERACTION_SCOPE,
    OCCURRED_AT,
    client,
    create_identity,
    decision_payload,
    prepared,
    register_source,
    resolution_payload,
)

pytestmark = pytest.mark.integration


def test_owner_approved_source_commits_an_event_with_complete_provenance(
    tmp_path: Path,
) -> None:
    # Given: an owner-approved push source for an active service identity
    api_key, source_id = prepared(tmp_path)
    # When: the adapter reports a decision it observed
    with client(tmp_path, api_key) as agent:
        response = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
    # Then: the event and its decision projection are stored with provenance
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert body["decision_id"] is not None
    assert body["actor_type"] == "agent"
    assert body["evidence_eligibility"] == "contextual_only"
    assert body["policy_profile_version"] == "p13.1"


def test_an_identical_retry_returns_the_original_result(tmp_path: Path) -> None:
    # Given: one accepted event
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        first = agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        # When: the adapter retries the identical request
        second = agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
    # Then: the original event is replayed instead of duplicated
    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json()["duplicate"] is True
    assert second.json()["event_id"] == first.json()["event_id"]
    with client(tmp_path) as owner:
        source = owner.get("/v1/decision-io/sources").json()[0]
    assert source["raw_event_count"] == 1
    assert source["decision_count"] == 1


def test_reusing_an_external_event_id_for_other_content_is_rejected(tmp_path: Path) -> None:
    # Given: one accepted event
    api_key, source_id = prepared(tmp_path)
    conflicting = decision_payload(source_id)
    conflicting["question"] = "A different question entirely?"
    conflicting["content"] = {"repository": "other"}
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        # When: the same external event ID carries different content
        conflict = agent.post("/v1/external/decision-io/decisions", json=conflicting)
    # Then: the request is rejected and nothing is mutated
    assert conflict.status_code == 409
    with client(tmp_path) as owner:
        source = owner.get("/v1/decision-io/sources").json()[0]
    assert source["raw_event_count"] == 1


def test_a_changed_projection_under_the_same_event_id_is_a_conflict(tmp_path: Path) -> None:
    # Given: one accepted decision event
    api_key, source_id = prepared(tmp_path)
    changed = decision_payload(source_id)
    changed["question"] = "Which other refactor should be applied?"
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        # When: only the projected decision changes, not the envelope content
        conflict = agent.post("/v1/external/decision-io/decisions", json=changed)
    # Then: it is not mistaken for an identical retry
    assert conflict.status_code == 409


def test_a_caller_without_the_exact_scope_is_refused(tmp_path: Path) -> None:
    # Given: an identity holding only the interaction scope
    api_key, source_id = prepared(tmp_path, scopes=[INTERACTION_SCOPE])
    # When: it attempts to record a decision
    with client(tmp_path, api_key) as agent:
        refused = agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        allowed = agent.post(
            "/v1/external/decision-io/interactions",
            json={
                "source_id": source_id,
                "external_event_id": "event-interaction-1",
                "occurred_at": OCCURRED_AT,
                "actor_type": "agent",
                "content": {"tool": "search"},
            },
        )
    # Then: only the operation its scope covers succeeds
    assert refused.status_code == 403
    assert allowed.status_code == 201


def test_a_source_belonging_to_another_identity_cannot_be_written(tmp_path: Path) -> None:
    # Given: two identities, each with the full scope set
    with client(tmp_path) as owner:
        first = create_identity(owner, ALL_SCOPES)
        source = register_source(owner, first["identity"]["id"])
        second = owner.post(
            "/v1/service-identities",
            json={"name": "Other agent", "description": None, "scopes": ALL_SCOPES},
        ).json()
    # When: the second identity writes to the first identity's source
    with client(tmp_path, str(second["api_key"])) as other:
        response = other.post(
            "/v1/external/decision-io/decisions", json=decision_payload(str(source["id"]))
        )
    # Then: the write is refused
    assert response.status_code == 403


def test_events_outside_the_declared_consent_are_rejected(tmp_path: Path) -> None:
    # Given: a source that declares metadata only and an owner-only author scope
    api_key, source_id = prepared(tmp_path, data_classes=["metadata"], author_scope="owner_only")
    with client(tmp_path, api_key) as agent:
        # When: a decision-class event and an agent-authored event arrive
        undeclared = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
        outside_scope = agent.post(
            "/v1/external/decision-io/interactions",
            json={
                "source_id": source_id,
                "external_event_id": "event-interaction-2",
                "occurred_at": OCCURRED_AT,
                "actor_type": "agent",
                "content": {},
            },
        )
    # Then: both are rejected before persistence
    assert undeclared.status_code == 422
    assert outside_scope.status_code == 422
    with client(tmp_path) as owner:
        assert owner.get("/v1/decision-io/sources").json()[0]["raw_event_count"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("occurred_at", "2026-09-23T10:00:00"),
        ("external_event_id", ""),
    ],
)
def test_invalid_envelopes_are_rejected_without_partial_state(
    tmp_path: Path, field: str, value: object
) -> None:
    # Given: an owner-approved source
    api_key, source_id = prepared(tmp_path)
    payload = decision_payload(source_id)
    payload[field] = value
    # When: an unsupported schema, naive timestamp, or empty ID is sent
    with client(tmp_path, api_key) as agent:
        response = agent.post("/v1/external/decision-io/decisions", json=payload)
    # Then: the request fails and nothing is stored
    assert response.status_code == 422
    with client(tmp_path) as owner:
        assert owner.get("/v1/decision-io/sources").json()[0]["raw_event_count"] == 0


def test_provenance_and_observations_survive_a_restart(tmp_path: Path) -> None:
    # Given: an accepted decision and observation
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        agent.post(
            "/v1/external/decision-io/resolutions",
            json=resolution_payload(source_id, actor_type="agent"),
        )
    # When: the daemon restarts and the adapter retries the same event
    with client(tmp_path, api_key) as restarted:
        retry = restarted.post(
            "/v1/external/decision-io/resolutions",
            json=resolution_payload(source_id, actor_type="agent"),
        )
    # Then: idempotency, provenance, and observation state all survived
    assert retry.json()["duplicate"] is True
    with client(tmp_path) as owner:
        source = owner.get("/v1/decision-io/sources").json()[0]
        observations = owner.get("/v1/decision-io/observations").json()
    assert source["resolution_observation_count"] == 1
    assert observations[0]["status"] == "pending"
    assert source["policy_profile_version"] == "p13.1"


def test_audit_records_hold_no_event_content(tmp_path: Path) -> None:
    # Given: an ingested decision whose content is distinctive
    api_key, source_id = prepared(tmp_path)
    payload = decision_payload(source_id)
    payload["content"] = {"secret": "synthetic-should-not-appear"}
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=payload)
    # When: the owner reads the audit log
    with client(tmp_path) as owner:
        events = owner.get("/v1/audit/events?limit=50")
    # Then: identifiers and reason codes are present but content is not
    assert "synthetic-should-not-appear" not in events.text
    assert "Which refactor" not in events.text
    ingestions = [item for item in events.json() if item["action"] == "decision_io.ingest"]
    assert ingestions and ingestions[0]["metadata"]["evidence_eligibility"] == "contextual_only"
