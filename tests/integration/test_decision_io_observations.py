"""Decision I/O observations: correlation, promotion, and owner confirmation."""

from pathlib import Path

import pytest

from .decision_io_support import (
    ALL_SCOPES,
    OUTCOME_RECORD_SCOPE,
    client,
    decision_history,
    decision_payload,
    outcome_payload,
    prepared,
    resolution_payload,
)

pytestmark = pytest.mark.integration


def test_agent_reported_choices_stay_observations(tmp_path: Path) -> None:
    # Given: a stored decision from the same source
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        # When: the agent reports the choice as its own
        response = agent.post(
            "/v1/external/decision-io/resolutions",
            json=resolution_payload(source_id, actor_type="agent"),
        )
    # Then: the report is pending, not a canonical resolution
    assert response.status_code == 201
    assert response.json()["promoted"] is False
    assert response.json()["observation_status"] == "pending"
    with client(tmp_path) as owner:
        entries = owner.get("/v1/decisions").json()
    assert entries[0]["decision"]["status"] == "open"
    assert entries[0]["resolution"] is None


def test_an_owner_choice_is_promoted_once_and_creates_choice_evidence(tmp_path: Path) -> None:
    # Given: a stored decision from an owner-approved source
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        decision = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
        # When: the owner's own explicit choice is reported
        promoted = agent.post(
            "/v1/external/decision-io/resolutions", json=resolution_payload(source_id)
        )
    # Then: the decision is resolved once and choice evidence exists
    assert promoted.status_code == 201, promoted.text
    assert promoted.json()["promoted"] is True
    assert promoted.json()["observation_status"] == "confirmed"
    decision_id = decision.json()["decision_id"]
    with client(tmp_path) as owner:
        history = decision_history(owner, decision_id)
        preferences = owner.get("/v1/preferences").json()
    assert history["decision"]["status"] == "resolved"
    assert history["resolution"] is not None
    assert [item for item in preferences if item["key"] == "code.simplicity"]


def test_a_technical_result_never_becomes_owner_satisfaction(tmp_path: Path) -> None:
    # Given: a stored decision
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        decision = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
        # When: the agent reports that the tests passed
        response = agent.post(
            "/v1/external/decision-io/outcomes",
            json=outcome_payload(source_id, technical_status="succeeded"),
        )
    # Then: the result is technical, ignored for learning, and has no wellbeing
    assert response.status_code == 201, response.text
    assert response.json()["evidence_eligibility"] == "ignored"
    with client(tmp_path) as owner:
        observations = owner.get("/v1/decision-io/observations").json()
        history = decision_history(owner, decision.json()["decision_id"])
    technical = [item for item in observations if item["kind"] == "technical"]
    assert technical and technical[0]["satisfaction"] is None
    assert history["outcome"] is None


def test_an_agent_cannot_report_owner_wellbeing(tmp_path: Path) -> None:
    # Given: an owner-approved source
    api_key, source_id = prepared(tmp_path)
    # When: the agent claims an owner-reported outcome
    with client(tmp_path, api_key) as agent:
        response = agent.post(
            "/v1/external/decision-io/outcomes",
            json=outcome_payload(source_id, kind="owner_reported"),
        )
    # Then: the request is rejected before persistence
    assert response.status_code == 422
    assert "wellbeing" in response.text.lower() or "owner" in response.text.lower()


def test_an_outcome_before_its_decision_stays_unmatched_then_correlates(
    tmp_path: Path,
) -> None:
    # Given: an owner-approved source with no decision yet
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        early = agent.post(
            "/v1/external/decision-io/outcomes",
            json=outcome_payload(source_id, kind="user_behavior", disposition="modified"),
        )
        assert early.json()["observation_status"] == "unmatched"
        # When: the decision it refers to arrives later
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
    # Then: the retained observation attaches to it instead of being lost
    with client(tmp_path) as owner:
        observations = owner.get("/v1/decision-io/observations").json()
    matched = [item for item in observations if item["id"] == early.json()["observation_id"]]
    assert matched and matched[0]["status"] == "pending"
    assert matched[0]["decision_id"] is not None


def test_an_unmatched_observation_never_attaches_to_another_decision(tmp_path: Path) -> None:
    # Given: an observation for a decision ID that no decision uses
    api_key, source_id = prepared(tmp_path)
    orphan = outcome_payload(source_id, kind="user_behavior", disposition="reverted")
    orphan["external_decision_id"] = "decision-unknown"
    with client(tmp_path, api_key) as agent:
        stored = agent.post("/v1/external/decision-io/outcomes", json=orphan)
        # When: an unrelated decision is ingested
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
    # Then: the observation stays unmatched
    with client(tmp_path) as owner:
        observations = owner.get("/v1/decision-io/observations").json()
    orphaned = [item for item in observations if item["id"] == stored.json()["observation_id"]]
    assert orphaned and orphaned[0]["status"] == "unmatched"
    assert orphaned[0]["decision_id"] is None


def test_the_owner_confirms_an_observation_before_it_becomes_wellbeing(
    tmp_path: Path,
) -> None:
    # Given: a resolved decision and an agent's legacy outcome report
    api_key, source_id = prepared(tmp_path, scopes=[*ALL_SCOPES, OUTCOME_RECORD_SCOPE])
    with client(tmp_path, api_key) as agent:
        decision = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
        agent.post("/v1/external/decision-io/resolutions", json=resolution_payload(source_id))
        reported = agent.post(
            "/v1/external/record-outcome",
            json={
                "decision_id": decision.json()["decision_id"],
                "satisfaction": 0.9,
                "regret": False,
                "notes": "Synthetic report",
            },
        )
    # Then: the compatibility wrapper stores an unconfirmed observation
    assert reported.status_code == 201, reported.text
    assert reported.json()["requires_owner_confirmation"] is True
    assert reported.json()["status"] == "pending"
    decision_id = decision.json()["decision_id"]
    with client(tmp_path) as owner:
        assert decision_history(owner, decision_id)["outcome"] is None
        pending = [
            item
            for item in owner.get("/v1/decision-io/observations").json()
            if item["kind"] == "owner_reported"
        ]
        # When: the owner confirms it with their own report
        confirmed = owner.post(
            f"/v1/decision-io/observations/{pending[0]['id']}/confirm",
            json={"satisfaction": 0.6, "regret": False},
        )
        stored = decision_history(owner, decision_id)["outcome"]
    # Then: owner wellbeing exists only after that confirmation
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert stored is not None
    assert stored["satisfaction"] == 0.6


def test_the_owner_can_reject_a_reported_observation(tmp_path: Path) -> None:
    # Given: an agent-reported choice
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        observation = agent.post(
            "/v1/external/decision-io/resolutions",
            json=resolution_payload(source_id, actor_type="agent"),
        )
    with client(tmp_path) as owner:
        # When: the owner rejects it
        rejected = owner.post(
            f"/v1/decision-io/observations/{observation.json()['observation_id']}/reject"
        )
    # Then: the observation is closed without changing the decision
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"


def test_the_owner_confirms_an_agent_reported_choice_exactly_once(tmp_path: Path) -> None:
    # Given: a choice the agent reported, which stays pending
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        decision = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
        reported = agent.post(
            "/v1/external/decision-io/resolutions",
            json=resolution_payload(source_id, actor_type="agent"),
        )
    observation_id = reported.json()["observation_id"]
    with client(tmp_path) as owner:
        # When: the owner confirms it, then tries again
        confirmed = owner.post(f"/v1/decision-io/observations/{observation_id}/confirm")
        again = owner.post(f"/v1/decision-io/observations/{observation_id}/confirm")
        history = decision_history(owner, decision.json()["decision_id"])
        preferences = owner.get("/v1/preferences").json()
    # Then: one canonical resolution and its choice Evidence exist
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert again.status_code == 409
    assert history["decision"]["status"] == "resolved"
    assert [item for item in preferences if item["key"] == "code.simplicity"]


def test_an_owner_choice_for_an_already_resolved_decision_is_not_applied_twice(
    tmp_path: Path,
) -> None:
    # Given: a decision the owner already resolved through the adapter
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        agent.post("/v1/external/decision-io/resolutions", json=resolution_payload(source_id))
        # When: a second owner choice arrives for the same decision
        late = agent.post(
            "/v1/external/decision-io/resolutions",
            json=resolution_payload(
                source_id, external_event_id="event-resolution-2", external_option_id="option-b"
            ),
        )
    # Then: it is kept for review instead of overwriting the resolution
    assert late.status_code == 201, late.text
    assert late.json()["promoted"] is False
    assert late.json()["observation_status"] == "pending"
    with client(tmp_path) as owner:
        confirm = owner.post(
            f"/v1/decision-io/observations/{late.json()['observation_id']}/confirm"
        )
    assert confirm.status_code == 409


def test_a_late_matched_owner_choice_waits_for_confirmation(tmp_path: Path) -> None:
    # Given: an owner choice that arrives before its decision
    api_key, source_id = prepared(tmp_path)
    with client(tmp_path, api_key) as agent:
        early = agent.post(
            "/v1/external/decision-io/resolutions", json=resolution_payload(source_id)
        )
        # When: the decision arrives afterwards
        decision = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
    # Then: the choice is matched but not silently promoted
    assert early.json()["observation_status"] == "unmatched"
    with client(tmp_path) as owner:
        history = decision_history(owner, decision.json()["decision_id"])
        matched = [
            item
            for item in owner.get("/v1/decision-io/observations").json()
            if item["id"] == early.json()["observation_id"]
        ]
    assert history["resolution"] is None
    assert matched[0]["status"] == "pending"


@pytest.mark.parametrize(
    ("kind", "extra", "status_code"),
    [
        ("technical", {"technical_status": "succeeded"}, 409),
        ("user_behavior", {"disposition": "accepted"}, 409),
    ],
)
def test_only_satisfaction_reports_can_become_wellbeing(
    tmp_path: Path, kind: str, extra: dict[str, str], status_code: int
) -> None:
    # Given: a technical or behavioral observation for a stored decision
    api_key, source_id = prepared(tmp_path)
    payload = outcome_payload(source_id, kind=kind)
    payload.update(extra)
    with client(tmp_path, api_key) as agent:
        agent.post("/v1/external/decision-io/decisions", json=decision_payload(source_id))
        observed = agent.post("/v1/external/decision-io/outcomes", json=payload)
    # When: the owner tries to confirm it as wellbeing
    with client(tmp_path) as owner:
        response = owner.post(
            f"/v1/decision-io/observations/{observed.json()['observation_id']}/confirm",
            json={"satisfaction": 0.5, "regret": False},
        )
    # Then: the confirmation is refused as wellbeing
    assert response.status_code == status_code


def test_confirming_a_satisfaction_report_requires_the_owners_values(tmp_path: Path) -> None:
    # Given: a pending legacy satisfaction report for a resolved decision
    api_key, source_id = prepared(tmp_path, scopes=[*ALL_SCOPES, OUTCOME_RECORD_SCOPE])
    with client(tmp_path, api_key) as agent:
        decision = agent.post(
            "/v1/external/decision-io/decisions", json=decision_payload(source_id)
        )
        agent.post("/v1/external/decision-io/resolutions", json=resolution_payload(source_id))
        report = agent.post(
            "/v1/external/record-outcome",
            json={
                "decision_id": decision.json()["decision_id"],
                "satisfaction": 1.0,
                "regret": False,
            },
        )
    # When: the owner confirms without giving their own values
    with client(tmp_path) as owner:
        response = owner.post(f"/v1/decision-io/observations/{report.json()['id']}/confirm")
    # Then: the agent's values are never copied into owner wellbeing
    assert response.status_code == 422
