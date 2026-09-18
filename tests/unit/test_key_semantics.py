"""Embedded key text, cosine scoring, and semantic merge suggestions."""

from datetime import UTC, datetime

import pytest
from soulmate_core.domain import (
    EvidenceTargetType,
    TargetKeyAlias,
    TargetKeyAliasMethod,
    TargetKeyAliasStatus,
)
from soulmate_core.keys import (
    SEMANTIC_ALIAS_VERSION,
    EmbeddedKey,
    cosine_similarity,
    key_embedding_text,
    key_text_hash,
    propose_semantic_aliases,
    semantic_key_scores,
)

NOW = datetime(2026, 9, 18, tzinfo=UTC)
PROFILE = "profile_keys"
PREFERENCE = EvidenceTargetType.PREFERENCE
FACT = EvidenceTargetType.FACT


def embedded(key: str, *values: float, target_type: EvidenceTargetType = PREFERENCE) -> EmbeddedKey:
    return EmbeddedKey(target_type, key, tuple(values))


def alias_row(
    alias_key: str,
    canonical_key: str,
    *,
    status: TargetKeyAliasStatus = TargetKeyAliasStatus.REJECTED,
    profile_id: str = PROFILE,
) -> TargetKeyAlias:
    return TargetKeyAlias(
        profile_id=profile_id,
        target_type=PREFERENCE,
        alias_key=alias_key,
        canonical_key=canonical_key,
        polarity=1,
        method=TargetKeyAliasMethod.NORMALIZED,
        status=status,
        algorithm_version="key-normalizer-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def test_key_text_splits_dotted_segments_into_words() -> None:
    # Given: a dotted key with an underscore segment
    # When: its embedded text is built without a label
    # Then: every separator becomes a single space
    assert key_embedding_text("ui.theme.dark_mode") == "ui theme dark mode"


def test_key_text_appends_the_owner_label_and_aliases() -> None:
    # Given: an owner label and two alternative wordings
    # When: the embedded text is built
    # Then: they follow the key words behind separators
    text = key_embedding_text("ui.theme.dark", "giao diện tối", ("nền tối", "chế độ đêm"))
    assert text == "ui theme dark | giao diện tối | nền tối | chế độ đêm"


@pytest.mark.parametrize("label", ["", "   ", None])
def test_key_text_ignores_a_blank_label(label: str | None) -> None:
    # Given: a label that carries no wording
    # When: the embedded text is built
    # Then: only the key words remain
    assert key_embedding_text("ui.theme.dark", label) == "ui theme dark"


@pytest.mark.parametrize("key", ["", "   ", ".", "..."])
def test_key_text_rejects_a_key_without_words(key: str) -> None:
    # Given: a key that holds no words
    # When: the embedded text is built
    # Then: it is rejected instead of embedding an empty string
    with pytest.raises(ValueError, match="must not be empty"):
        key_embedding_text(key)


def test_key_text_hash_changes_with_the_label_only() -> None:
    # Given: one key with and without a label
    # When: both texts are hashed
    # Then: the hash is stable per text and differs between them
    plain = key_text_hash(key_embedding_text("ui.theme.dark"))
    assert plain == key_text_hash(key_embedding_text("ui.theme.dark"))
    assert plain != key_text_hash(key_embedding_text("ui.theme.dark", "giao diện tối"))


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ((1.0, 0.0), (1.0, 0.0), 1.0),
        ((1.0, 0.0), (0.0, 1.0), 0.0),
        ((1.0, 0.0), (-1.0, 0.0), -1.0),
        ((3.0, 0.0), (9.0, 0.0), 1.0),
        ((1.0, 0.0), (0.0, 0.0), 0.0),
    ],
)
def test_cosine_similarity_covers_equal_orthogonal_and_opposite_vectors(
    left: tuple[float, ...], right: tuple[float, ...], expected: float
) -> None:
    # Given: two vectors
    # When: their cosine is computed
    # Then: the value is the expected similarity, with a zero vector scoring zero
    assert cosine_similarity(left, right) == pytest.approx(expected)


def test_cosine_similarity_rejects_empty_and_mismatched_vectors() -> None:
    # Given: an empty vector and a vector of another length
    # When: each pair is compared
    # Then: both cases raise their own message
    with pytest.raises(ValueError, match="non-empty"):
        cosine_similarity((), (1.0,))
    with pytest.raises(ValueError, match="equal length"):
        cosine_similarity((1.0, 0.0), (1.0,))


def test_embedded_key_requires_a_key_and_a_vector() -> None:
    # Given: a missing key name and a missing vector
    # When: each embedded key is built
    # Then: both are rejected
    with pytest.raises(ValueError, match="must name a target key"):
        EmbeddedKey(PREFERENCE, "", (1.0,))
    with pytest.raises(ValueError, match="must carry a vector"):
        EmbeddedKey(PREFERENCE, "ui.theme.dark", ())


def test_semantic_scores_keep_the_best_score_per_key_name() -> None:
    # Given: the same key name stored for two target types with different vectors
    keys = [
        embedded("ui.theme.dark", 1.0, 0.0),
        embedded("ui.theme.dark", 0.0, 1.0, target_type=FACT),
        embedded("food.spicy", -1.0, 0.0),
    ]

    # When: a query aligned with the first vector is scored
    scores = semantic_key_scores((1.0, 0.0), keys)

    # Then: the better score wins and every key is scored once
    assert scores == pytest.approx({"ui.theme.dark": 1.0, "food.spicy": -1.0})


def test_semantic_scores_ignore_vectors_of_another_model() -> None:
    # Given: one stored vector of a different dimension
    keys = [embedded("ui.theme.dark", 1.0, 0.0, 0.0), embedded("food.spicy", 1.0, 0.0)]

    # When: a two-dimensional query is scored
    scores = semantic_key_scores((1.0, 0.0), keys)

    # Then: the stale row is skipped instead of failing the retrieval
    assert scores == pytest.approx({"food.spicy": 1.0})


def test_semantic_scores_reject_an_empty_query_vector() -> None:
    # Given: no query vector
    # When: scoring runs
    # Then: it is rejected rather than scoring everything as zero
    with pytest.raises(ValueError, match="non-empty query vector"):
        semantic_key_scores((), [embedded("ui.theme.dark", 1.0)])


def test_similar_keys_are_suggested_for_review_and_never_activated() -> None:
    # Given: two differently named keys with nearly identical vectors
    keys = [embedded("ui.theme.dark", 1.0, 0.0), embedded("appearance.night", 0.99, 0.141)]

    # When: suggestions are proposed
    proposals = propose_semantic_aliases(PROFILE, keys, (), NOW)

    # Then: one suggestion points the later key at the earlier key, unapproved
    assert len(proposals) == 1
    alias = proposals[0].alias
    assert (alias.alias_key, alias.canonical_key) == ("appearance.night", "ui.theme.dark")
    assert alias.status is TargetKeyAliasStatus.SUGGESTED
    assert alias.method is TargetKeyAliasMethod.SEMANTIC
    assert alias.polarity == 1
    assert alias.algorithm_version == SEMANTIC_ALIAS_VERSION
    assert alias.similarity == pytest.approx(proposals[0].similarity)
    assert alias.similarity is not None and alias.similarity >= 0.85


def test_keys_below_the_threshold_are_not_suggested() -> None:
    # Given: two keys whose vectors sit just below the threshold
    keys = [embedded("ui.theme.dark", 1.0, 0.0), embedded("food.spicy", 0.8, 0.6)]

    # When: suggestions are proposed at the default threshold
    # Then: the pair stays separate
    assert propose_semantic_aliases(PROFILE, keys, (), NOW) == ()


def test_opposite_keys_are_suggested_but_keep_positive_polarity() -> None:
    # Given: two opposite keys that embeddings place close together
    keys = [embedded("ui.theme.dark", 1.0, 0.05), embedded("ui.theme.light", 1.0, -0.05)]

    # When: suggestions are proposed
    proposals = propose_semantic_aliases(PROFILE, keys, (), NOW)

    # Then: the pair waits for the owner to invert it, never merged automatically
    assert len(proposals) == 1
    assert proposals[0].alias.polarity == 1
    assert proposals[0].alias.status is TargetKeyAliasStatus.SUGGESTED


def test_keys_with_equal_normalized_forms_are_left_to_automatic_merging() -> None:
    # Given: two keys that normalize to the same form
    keys = [embedded("ui.theme.dark", 1.0, 0.0), embedded("ui.theme.dark_mode", 1.0, 0.0)]

    # When: suggestions are proposed
    # Then: nothing is suggested, because the normalized rule already merged them
    assert propose_semantic_aliases(PROFILE, keys, (), NOW) == ()


@pytest.mark.parametrize(
    "status",
    [TargetKeyAliasStatus.REJECTED, TargetKeyAliasStatus.ACTIVE, TargetKeyAliasStatus.SUGGESTED],
)
def test_a_reviewed_key_is_never_suggested_again(status: TargetKeyAliasStatus) -> None:
    # Given: an alias row of any status for the later key
    keys = [embedded("ui.theme.dark", 1.0, 0.0), embedded("appearance.night", 1.0, 0.0)]
    stored = [alias_row("appearance.night", "other.key", status=status)]

    # When: suggestions are proposed
    # Then: the owner decision stands and nothing is re-proposed
    assert propose_semantic_aliases(PROFILE, keys, stored, NOW) == ()


def test_an_alias_row_of_another_profile_does_not_block_a_suggestion() -> None:
    # Given: a rejection recorded for a different profile
    keys = [embedded("ui.theme.dark", 1.0, 0.0), embedded("appearance.night", 1.0, 0.0)]
    stored = [alias_row("appearance.night", "other.key", profile_id="profile_other")]

    # When: suggestions are proposed
    # Then: this profile still receives its suggestion
    assert len(propose_semantic_aliases(PROFILE, keys, stored, NOW)) == 1


def test_each_key_takes_part_in_at_most_one_suggestion() -> None:
    # Given: three keys that are all mutually similar
    keys = [
        embedded("ui.theme.dark", 1.0, 0.0),
        embedded("appearance.night", 1.0, 0.0),
        embedded("display.nocturnal", 1.0, 0.0),
    ]

    # When: suggestions are proposed
    proposals = propose_semantic_aliases(PROFILE, keys, (), NOW)

    # Then: only one pair is suggested, so each review stands on its own
    assert len(proposals) == 1
    assert proposals[0].alias.alias_key == "appearance.night"


def test_keys_of_different_target_types_are_never_paired() -> None:
    # Given: an identical vector stored as a preference and as a fact
    keys = [
        embedded("ui.theme.dark", 1.0, 0.0),
        embedded("appearance.night", 1.0, 0.0, target_type=FACT),
    ]

    # When: suggestions are proposed
    # Then: nothing is suggested, because the two types aggregate separately
    assert propose_semantic_aliases(PROFILE, keys, (), NOW) == ()


def test_suggestions_stop_at_the_limit_and_prefer_the_closest_pairs() -> None:
    # Given: two similar pairs and a limit of one
    keys = [
        embedded("ui.theme.dark", 1.0, 0.0),
        embedded("appearance.night", 0.99, 0.141),
        embedded("food.spicy", 0.0, 1.0),
        embedded("cuisine.hot", 0.0, 1.0),
    ]

    # When: suggestions are proposed with a limit of one
    proposals = propose_semantic_aliases(PROFILE, keys, (), NOW, limit=1)

    # Then: the closest pair is kept
    assert [item.alias.alias_key for item in proposals] == ["cuisine.hot"]


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_the_limit_bounds_the_number_of_suggestions(limit: int) -> None:
    # Given: two independent similar pairs
    keys = [
        embedded("ui.theme.dark", 1.0, 0.0),
        embedded("appearance.night", 1.0, 0.0),
        embedded("food.spicy", 0.0, 1.0),
        embedded("cuisine.hot", 0.0, 1.0),
    ]

    # When: suggestions are proposed with the given limit
    # Then: no more than the limit is returned
    assert len(propose_semantic_aliases(PROFILE, keys, (), NOW, limit=limit)) == limit


@pytest.mark.parametrize("keys", [[], [embedded("ui.theme.dark", 1.0)]])
def test_fewer_than_two_keys_produce_no_suggestions(keys: list[EmbeddedKey]) -> None:
    # Given: no key or a single key
    # When: suggestions are proposed
    # Then: there is no pair to suggest
    assert propose_semantic_aliases(PROFILE, keys, (), NOW) == ()


@pytest.mark.parametrize("threshold", [-0.01, 1.01, 2.0])
def test_a_threshold_outside_the_similarity_range_is_rejected(threshold: float) -> None:
    # Given: a threshold outside the range a stored similarity may take
    # When: suggestions are proposed
    # Then: it is rejected with the allowed range
    with pytest.raises(ValueError, match="between zero and one"):
        propose_semantic_aliases(PROFILE, (), (), NOW, threshold=threshold)


def test_a_negative_limit_is_rejected() -> None:
    # Given: a negative suggestion limit
    # When: suggestions are proposed
    # Then: the limit is refused
    with pytest.raises(ValueError, match="must not be negative"):
        propose_semantic_aliases(PROFILE, (), (), NOW, limit=-1)


@pytest.mark.parametrize(("threshold", "expected"), [(1.0, 1), (0.999999, 1)])
def test_a_pair_exactly_at_the_threshold_is_suggested(threshold: float, expected: int) -> None:
    # Given: two keys with identical vectors, so their similarity is exactly one
    keys = [embedded("ui.theme.dark", 1.0, 0.0), embedded("appearance.night", 1.0, 0.0)]

    # When: suggestions are proposed at the boundary
    # Then: equality counts as a match
    assert len(propose_semantic_aliases(PROFILE, keys, (), NOW, threshold=threshold)) == expected
