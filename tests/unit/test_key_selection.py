"""Deterministic known-key selection for extraction prompts."""

from datetime import UTC, datetime, timedelta

import pytest
from soulmate_core.context import KeySelectionPolicy, select_known_keys
from soulmate_core.domain import DerivedModel, Fact, Preference

NOW = datetime(2026, 1, 1, tzinfo=UTC)
FILTER = KeySelectionPolicy(send_all_threshold=0, limit=1)


def _preference(
    key: str,
    confidence: float = 0.5,
    context: dict[str, object] | None = None,
    updated_at: datetime = NOW,
) -> Preference:
    return Preference(key, 0.5, 0.5, confidence, context or {}, (), updated_at, 1)


def _model(*preferences: Preference, facts: tuple[Fact, ...] = ()) -> DerivedModel:
    return DerivedModel(preferences, facts, (), ())


def test_empty_model_returns_empty_groups() -> None:
    # Given: a model without records
    # When: keys are selected
    result = select_known_keys(_model(), query="anything")
    # Then: every group is present and empty
    assert result == {
        "namespaces": [],
        "facts": [],
        "preferences": [],
        "goals": [],
        "constraints": [],
    }


def test_small_model_at_threshold_is_shared_whole() -> None:
    # Given: exactly as many keys as the send-all threshold
    model = _model(*(_preference(f"topic.key_{index}") for index in range(3)))
    policy = KeySelectionPolicy(send_all_threshold=3, limit=1)
    # When: an unrelated query selects keys
    result = select_known_keys(model, query="unrelated", policy=policy)
    # Then: every key is kept despite the lower limit
    assert result["preferences"] == ["topic.key_0", "topic.key_1", "topic.key_2"]


def test_model_above_threshold_is_limited() -> None:
    # Given: one more key than the send-all threshold
    model = _model(*(_preference(f"topic.key_{index}") for index in range(4)))
    policy = KeySelectionPolicy(send_all_threshold=3, limit=2)
    # When: keys are selected
    result = select_known_keys(model, query="unrelated", policy=policy)
    # Then: only the limit is kept while every namespace is still listed
    assert len(result["preferences"]) == 2
    assert result["namespaces"] == ["topic"]


def test_zero_limit_keeps_only_namespaces() -> None:
    # Given: a filtered model and a zero key budget
    model = _model(_preference("ui.theme.dark"))
    policy = KeySelectionPolicy(send_all_threshold=0, limit=0)
    # When: keys are selected
    result = select_known_keys(model, query="dark", policy=policy)
    # Then: no key is shared but its namespace is
    assert result["preferences"] == []
    assert result["namespaces"] == ["ui.theme"]


def test_recent_key_outranks_lexical_and_confidence() -> None:
    # Given: a lexical, confident key and a recently used key
    model = _model(_preference("ui.theme.dark", 0.9), _preference("food.spicy", 0.1))
    # When: keys are selected with the food key marked recent
    result = select_known_keys(model, query="dark", recent_keys={"food.spicy"}, policy=FILTER)
    # Then: the recent key wins
    assert result["preferences"] == ["food.spicy"]


def test_lexical_match_splits_underscores_and_ignores_case() -> None:
    # Given: a matching key with lower confidence than an unrelated key
    model = _model(_preference("ui.theme.dark_mode", 0.1), _preference("work.remote", 0.9))
    # When: the query mentions the key words in another case
    result = select_known_keys(model, query="I like DARK MODE", policy=FILTER)
    # Then: the lexical match wins
    assert result["preferences"] == ["ui.theme.dark_mode"]


def test_lexical_match_uses_categorical_values() -> None:
    # Given: a fact whose value, not key, matches the query
    fact = Fact("home.city", "Hanoi", 0.1, {}, (), NOW, 1)
    model = _model(_preference("work.remote", 0.9), facts=(fact,))
    # When: keys are selected across types
    result = select_known_keys(model, query="I moved to hanoi", policy=FILTER)
    # Then: the fact is chosen and grouped as a fact
    assert result["facts"] == ["home.city"]
    assert result["preferences"] == []


def test_single_character_words_do_not_match() -> None:
    # Given: a key whose only shared word is one character long
    model = _model(_preference("plan.a", 0.1), _preference("work.remote", 0.9))
    # When: the query contains only that short word
    result = select_known_keys(model, query="a", policy=FILTER)
    # Then: confidence decides instead of the short word
    assert result["preferences"] == ["work.remote"]


def test_domain_match_outranks_confidence() -> None:
    # Given: a domain-scoped key and a more confident global key
    model = _model(
        _preference("cost.low", 0.1, {"domain": "Purchase"}), _preference("work.remote", 0.9)
    )
    # When: the decision domain matches case-insensitively
    result = select_known_keys(model, query="", domain="purchase", policy=FILTER)
    # Then: the domain key wins
    assert result["preferences"] == ["cost.low"]


def test_without_domain_scoped_keys_get_no_bonus() -> None:
    # Given: the same records without a requested domain
    model = _model(
        _preference("cost.low", 0.1, {"domain": "purchase"}), _preference("work.remote", 0.9)
    )
    # When: keys are selected without a domain
    result = select_known_keys(model, query="", policy=FILTER)
    # Then: confidence decides
    assert result["preferences"] == ["work.remote"]


def test_ties_prefer_recent_updates_after_confidence() -> None:
    # Given: equally confident keys updated at different times
    model = _model(
        _preference("topic.old", 0.5, updated_at=NOW),
        _preference("topic.new", 0.5, updated_at=NOW + timedelta(days=1)),
    )
    # When: no signal separates them
    result = select_known_keys(model, query="", policy=FILTER)
    # Then: the most recently updated key wins
    assert result["preferences"] == ["topic.new"]


def test_duplicate_keys_across_contexts_count_once() -> None:
    # Given: one key in two contexts and another key
    model = _model(
        _preference("ui.theme.dark", 0.2),
        _preference("ui.theme.dark", 0.9, {"domain": "work"}),
        _preference("ui.theme.light", 0.5),
    )
    policy = KeySelectionPolicy(send_all_threshold=0, limit=2)
    # When: keys are selected
    result = select_known_keys(model, query="", policy=policy)
    # Then: both distinct keys fit and the best context confidence is used
    assert result["preferences"] == ["ui.theme.dark", "ui.theme.light"]


def test_namespaces_skip_flat_keys_and_keep_most_frequent() -> None:
    # Given: flat keys and namespaces with different frequencies
    model = _model(
        _preference("flat"),
        _preference("ui.theme.dark"),
        _preference("ui.theme.light"),
        _preference("food.spicy"),
    )
    policy = KeySelectionPolicy(namespace_limit=1)
    # When: keys are selected
    result = select_known_keys(model, query="", policy=policy)
    # Then: only the most frequent dotted namespace is listed
    assert result["namespaces"] == ["ui.theme"]


def test_key_types_restrict_output_groups() -> None:
    # Given: a model with a preference and a fact
    fact = Fact("home.city", "Hanoi", 0.9, {}, (), NOW, 1)
    model = _model(_preference("cost.low"), facts=(fact,))
    # When: only preferences are requested
    result = select_known_keys(model, query="", key_types=("preferences",))
    # Then: facts are neither listed nor used for namespaces
    assert result == {"namespaces": ["cost"], "preferences": ["cost.low"]}


def test_query_without_shared_words_falls_back_to_confidence() -> None:
    # Given: English keys and a Vietnamese query with no shared words
    model = _model(_preference("ui.theme.dark", 0.1), _preference("work.remote", 0.9))
    # When: keys are selected
    result = select_known_keys(model, query="Tôi thích giao diện tối", policy=FILTER)
    # Then: lexical filtering cannot help and confidence decides
    assert result["preferences"] == ["work.remote"]


def test_unknown_key_type_is_rejected() -> None:
    # Given: an unsupported key type
    # When: keys are selected
    # Then: a validation error names the type
    with pytest.raises(ValueError, match=r"^Unknown key types: memories\.$"):
        select_known_keys(_model(), query="", key_types=("preferences", "memories"))


@pytest.mark.parametrize("field", ["send_all_threshold", "limit", "namespace_limit"])
def test_negative_budget_is_rejected(field: str) -> None:
    # Given: a negative budget value
    # When: the policy is created
    # Then: a validation error is raised
    with pytest.raises(ValueError, match=r"^Key selection budgets must not be negative\.$"):
        KeySelectionPolicy(**{field: -1})
