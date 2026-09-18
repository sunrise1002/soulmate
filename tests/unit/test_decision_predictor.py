"""Test deterministic Predict Me scoring without providers or persistence."""

from datetime import UTC, datetime

import pytest
from soulmate_core.decisions import (
    DECISION_ALGORITHM_VERSION,
    DecisionPredictor,
    ResolvedDecision,
    resolution_evidence,
)
from soulmate_core.domain import (
    DecisionEvent,
    DecisionOption,
    DecisionPrediction,
    DecisionResolution,
    DecisionStatus,
    DerivedModel,
    EvidenceTargetType,
    Preference,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
    UserModelSnapshot,
)
from soulmate_core.keys import KeyAliasMap


def _fixture() -> tuple[DecisionEvent, tuple[DecisionOption, ...], UserModelSnapshot, datetime]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    decision = DecisionEvent(
        "decision_test",
        "profile_test",
        "career",
        "Which role would I choose?",
        {},
        DecisionStatus.OPEN,
        now,
    )
    options = (
        DecisionOption(
            "option_office", decision.id, "Office", "Office role", {"work.remote": -1.0}, 1.0
        ),
        DecisionOption(
            "option_remote", decision.id, "Remote", "Remote role", {"work.remote": 1.0}, 1.0
        ),
    )
    preference = Preference(
        "work.remote", 0.9, 0.1, 0.9, {"domain": "career"}, ("evidence_remote",), now, 3
    )
    snapshot = UserModelSnapshot(
        "profile_test", 3, "personal-model-v1", 1, DerivedModel((preference,), (), (), ()), now
    )
    return decision, options, snapshot, now


def test_predictor_ranks_preferences_and_records_snapshot_and_evidence() -> None:
    decision, options, snapshot, now = _fixture()
    prediction = DecisionPredictor().predict(
        prediction_id="prediction_test",
        decision=decision,
        options=options,
        snapshot=snapshot,
        history=(),
        created_at=now,
    )

    assert prediction.ranking[0].option_id == "option_remote"
    assert sum(item.probability for item in prediction.ranking) == pytest.approx(1.0)
    assert prediction.important_factors == ("work.remote",)
    assert prediction.supporting_evidence_ids == ("evidence_remote",)
    assert prediction.model_snapshot_version == 3


def test_resolution_creates_relative_actual_choice_evidence() -> None:
    decision, options, _, now = _fixture()
    resolution = DecisionResolution(
        "resolution_test", decision.id, "option_office", "event_resolution", now
    )

    evidence = resolution_evidence(
        resolution=resolution,
        decision=decision,
        options=options,
        profile_id="profile_test",
        created_at=now,
    )

    assert len(evidence) == 1
    assert evidence[0].target_key == "work.remote"
    assert evidence[0].value == -1.0
    assert evidence[0].source_type == "actual_choice"


def _alias(
    alias_key: str,
    canonical_key: str,
    *,
    polarity: int = 1,
    status: TargetKeyAliasStatus = TargetKeyAliasStatus.ACTIVE,
) -> TargetKeyAlias:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return TargetKeyAlias(
        profile_id="profile_test",
        target_type=EvidenceTargetType.PREFERENCE,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=polarity,
        method=TargetKeyAliasMethod.OWNER,
        status=status,
        algorithm_version="owner-alias-v1",
        created_at=now,
        updated_at=now,
    )


def _options_with(
    decision: DecisionEvent, office: dict[str, float], remote: dict[str, float]
) -> tuple[DecisionOption, ...]:
    return (
        DecisionOption("option_office", decision.id, "Office", "Office role", office, 1.0),
        DecisionOption("option_remote", decision.id, "Remote", "Remote role", remote, 1.0),
    )


def _predict(
    decision: DecisionEvent,
    options: tuple[DecisionOption, ...],
    snapshot: UserModelSnapshot,
    now: datetime,
    aliases: KeyAliasMap | None = None,
    history: tuple[ResolvedDecision, ...] = (),
) -> DecisionPrediction:
    return DecisionPredictor().predict(
        prediction_id="prediction_test",
        decision=decision,
        options=options,
        snapshot=snapshot,
        history=history,
        created_at=now,
        aliases=aliases,
    )


def test_prediction_version_records_canonical_feature_matching() -> None:
    # Given / When: the published predictor version
    # Then: it names the feature canonicalization and the key normalizer
    assert DECISION_ALGORITHM_VERSION.startswith("decision-predictor-v2:")
    assert DECISION_ALGORITHM_VERSION.endswith(":canonical-features-v1:key-normalizer-v1")


def test_normalized_feature_key_matches_the_learned_preference() -> None:
    # Given: the model learned work.remote but the decision uses a variant key
    decision, _, snapshot, now = _fixture()
    options = _options_with(decision, {"Work.Remote_Mode": -1.0}, {"work.remote-setting": 1.0})

    # When: the decision is predicted without any stored alias
    prediction = _predict(decision, options, snapshot, now)

    # Then: the preference applies instead of a 50/50 guess
    assert prediction.ranking[0].option_id == "option_remote"
    assert prediction.ranking[0].probability > 0.6
    assert prediction.important_factors == ("work.remote",)
    assert prediction.supporting_evidence_ids == ("evidence_remote",)
    assert prediction.uncertain_factors == ()


def test_unrelated_feature_key_is_not_matched() -> None:
    # Given: a feature key that neither aliases nor normalization connect
    decision, _, snapshot, now = _fixture()
    options = _options_with(decision, {"work.office": 1.0}, {"work.office": -1.0})

    # When: the decision is predicted
    prediction = _predict(decision, options, snapshot, now)

    # Then: no preference applies and the feature stays uncertain
    assert prediction.ranking[0].probability == pytest.approx(0.5)
    assert prediction.important_factors == ()
    assert prediction.uncertain_factors == ("work.office",)


def test_inverted_active_alias_flips_the_feature_sign() -> None:
    # Given: work.office is the opposite axis of the learned work.remote preference
    decision, _, snapshot, now = _fixture()
    options = _options_with(decision, {"work.office": 1.0}, {"work.office": -1.0})
    aliases = KeyAliasMap([_alias("work.office", "work.remote", polarity=-1)])

    # When: the decision is predicted with the alias
    prediction = _predict(decision, options, snapshot, now, aliases)

    # Then: the option without the office feature wins
    assert prediction.ranking[0].option_id == "option_remote"
    assert prediction.important_factors == ("work.remote",)


def test_suggested_alias_is_not_used_for_matching() -> None:
    # Given: the same inverse mapping only as an unreviewed suggestion
    decision, _, snapshot, now = _fixture()
    options = _options_with(decision, {"work.office": 1.0}, {"work.office": -1.0})
    aliases = KeyAliasMap(
        [_alias("work.office", "work.remote", status=TargetKeyAliasStatus.SUGGESTED)]
    )

    # When: the decision is predicted
    prediction = _predict(decision, options, snapshot, now, aliases)

    # Then: the suggestion has no effect
    assert prediction.ranking[0].probability == pytest.approx(0.5)
    assert prediction.important_factors == ()


def test_keys_that_collapse_together_are_averaged() -> None:
    # Given: one option lists two variants of the same feature with different values
    decision, _, snapshot, now = _fixture()
    options = _options_with(
        decision,
        {"work.remote": -1.0},
        {"work.remote": 1.0, "work.remote_preference": 0.0},
    )
    single = _options_with(decision, {"work.remote": -1.0}, {"work.remote": 0.5})

    # When: both decisions are predicted
    collapsed = _predict(decision, options, snapshot, now)
    reference = _predict(decision, single, snapshot, now)

    # Then: the collapsed option scores like the averaged value 0.5
    assert collapsed.ranking[0].utility == pytest.approx(reference.ranking[0].utility)
    assert collapsed.ranking[1].utility == pytest.approx(reference.ranking[1].utility)


def test_history_features_are_canonicalized_for_pairwise_learning() -> None:
    # Given: an empty model and a past choice recorded under an opposite key
    decision, _, _, now = _fixture()
    empty = UserModelSnapshot(
        "profile_test", 1, "personal-model-v1", 0, DerivedModel((), (), (), ()), now
    )
    past = DecisionEvent(
        "decision_past", "profile_test", "career", "Earlier role?", {}, DecisionStatus.RESOLVED, now
    )
    past_options = (
        DecisionOption("past_office", past.id, "Office", "Office", {"work.office": 1.0}, 1.0),
        DecisionOption("past_remote", past.id, "Remote", "Remote", {"work.office": -1.0}, 1.0),
    )
    history = (
        ResolvedDecision(
            past,
            past_options,
            DecisionResolution("resolution_past", past.id, "past_remote", "event_past", now),
        ),
    )
    options = _options_with(decision, {"work.remote": -1.0}, {"work.remote": 1.0})
    aliases = KeyAliasMap([_alias("work.office", "work.remote", polarity=-1)])

    # When: the new decision uses the canonical key
    with_alias = _predict(decision, options, empty, now, aliases, history)
    without_alias = _predict(decision, options, empty, now, None, history)

    # Then: the past choice teaches the canonical feature only through the alias
    assert with_alias.ranking[0].option_id == "option_remote"
    assert with_alias.important_factors == ("work.remote",)
    assert with_alias.similar_decision_ids == ("decision_past",)
    assert without_alias.important_factors == ()
    assert without_alias.ranking[0].probability < with_alias.ranking[0].probability


def test_predictor_rejects_a_snapshot_of_another_profile_with_aliases() -> None:
    # Given: a snapshot belonging to another profile
    decision, options, snapshot, now = _fixture()
    foreign = UserModelSnapshot("profile_other", 1, "personal-model-v1", 0, snapshot.model, now)

    # When / Then: prediction fails before any alias mapping
    with pytest.raises(ValueError, match="same profile"):
        _predict(decision, options, foreign, now, KeyAliasMap())
