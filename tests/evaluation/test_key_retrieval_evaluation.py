"""Test the reproducible key retrieval and antonym spike harness."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from soulmate_core.evaluation import (
    KeyRetrievalDataset,
    KeyRetrievalKey,
    KeyRetrievalQuery,
    SimilarityScorer,
    evaluate_key_retrieval,
    key_text,
    lexical_scores,
    load_key_dataset,
)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset_version": "test-v1",
        "keys": [
            {"key": "ui.theme.dark", "key_type": "preferences", "label": "Giao diện tối"},
            {"key": "ui.theme.light", "key_type": "preferences", "label": "Giao diện sáng"},
            {"key": "food.spice.high", "key_type": "preferences", "label": "Ăn cay nhiều"},
        ],
        "queries": [
            {"id": "q1", "language": "vi", "text": "nền tối", "expected_key": "ui.theme.dark"},
            {"id": "q2", "language": "en", "text": "spicy", "expected_key": "food.spice.high"},
        ],
        "antonym_pairs": [["ui.theme.dark", "ui.theme.light"]],
    }
    payload.update(overrides)
    return payload


def _written(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(_payload(**overrides), ensure_ascii=False), encoding="utf-8")
    return path


def _constant(value: float) -> SimilarityScorer:
    def scorer(query: str, texts: Sequence[str]) -> Sequence[float]:  # noqa: ARG001
        return [value] * len(texts)

    return scorer


@pytest.mark.evaluation
def test_packaged_dataset_covers_both_languages_and_opposite_keys() -> None:
    # Given: the packaged synthetic Vietnamese/English key set.
    # When: it is loaded and validated.
    dataset = load_key_dataset()

    # Then: it holds enough keys for a 50-key budget to be a real constraint.
    assert dataset.dataset_version == "synthetic-key-retrieval-v1"
    assert len(dataset.keys) > 100
    assert {query.language for query in dataset.queries} == {"en", "vi"}
    assert dataset.antonym_pairs
    assert all(query.expected_key in {key.key for key in dataset.keys} for query in dataset.queries)


@pytest.mark.evaluation
def test_perfect_scorer_reaches_full_recall_and_reciprocal_rank(tmp_path: Path) -> None:
    # Given: a scorer that always ranks the expected key first.
    dataset = load_key_dataset(_written(tmp_path))
    expected = {query.text: query.expected_key for query in dataset.queries}
    keys = [key.key for key in dataset.keys]

    def scorer(query: str, texts: Sequence[str]) -> Sequence[float]:
        wanted = expected.get(query)
        return [1.0 if keys[index] == wanted else 0.0 for index in range(len(texts))]

    # When: the dataset is evaluated.
    report = evaluate_key_retrieval(dataset, scorer)

    # Then: every query is retrieved at rank one.
    assert report.overall.query_count == 2
    assert report.overall.recall_at_10 == 1.0
    assert report.overall.recall_at_50 == 1.0
    assert report.overall.mean_reciprocal_rank == 1.0
    assert set(report.by_language) == {"en", "vi"}


@pytest.mark.evaluation
def test_worst_case_scorer_pushes_the_expected_key_below_the_shared_budget() -> None:
    # Given: the packaged dataset and a scorer that ranks the expected key last.
    dataset = load_key_dataset()
    keys = [key.key for key in dataset.keys]
    expected = {query.text: query.expected_key for query in dataset.queries}

    def scorer(query: str, texts: Sequence[str]) -> Sequence[float]:
        wanted = expected.get(query)
        return [0.0 if keys[index] == wanted else 1.0 for index in range(len(texts))]

    # When: the dataset is evaluated.
    report = evaluate_key_retrieval(dataset, scorer)

    # Then: nothing is recalled and the reciprocal rank is the smallest possible.
    assert report.overall.recall_at_10 == 0.0
    assert report.overall.recall_at_50 == 0.0
    assert report.overall.mean_reciprocal_rank == pytest.approx(1.0 / len(keys))


@pytest.mark.evaluation
def test_lexical_baseline_recalls_far_fewer_vietnamese_keys_than_english_keys() -> None:
    # Given: the word-overlap scoring the current key selection policy uses.
    dataset = load_key_dataset()

    # When: it runs against the packaged dataset without owner labels.
    report = evaluate_key_retrieval(dataset, lexical_scores)

    # Then: Vietnamese messages mostly cannot reach their English key.
    assert report.by_language["vi"].recall_at_50 < 0.5
    assert report.by_language["vi"].recall_at_50 < report.by_language["en"].recall_at_50
    assert report.antonym_false_merge_rate == 0.0


@pytest.mark.evaluation
def test_similarity_equal_to_the_threshold_counts_as_a_false_merge(tmp_path: Path) -> None:
    # Given: opposite keys whose similarity is exactly the merge threshold.
    dataset = load_key_dataset(_written(tmp_path))

    # When: the dataset is evaluated at that threshold.
    at_threshold = evaluate_key_retrieval(dataset, _constant(0.85), merge_threshold=0.85)
    below = evaluate_key_retrieval(dataset, _constant(0.8499), merge_threshold=0.85)

    # Then: the boundary is inclusive, as an automatic merge rule would be.
    assert at_threshold.antonym_false_merge_rate == 1.0
    assert at_threshold.max_antonym_similarity == pytest.approx(0.85)
    assert below.antonym_false_merge_rate == 0.0


@pytest.mark.evaluation
def test_equal_scores_rank_deterministically_by_key(tmp_path: Path) -> None:
    # Given: a scorer that cannot separate any key.
    dataset = load_key_dataset(_written(tmp_path))

    # When: the same dataset is evaluated twice.
    first = evaluate_key_retrieval(dataset, _constant(0.0))
    second = evaluate_key_retrieval(dataset, _constant(0.0))

    # Then: ties fall back to alphabetical key order and repeat exactly.
    assert first == second
    assert first.overall.mean_reciprocal_rank == pytest.approx((1.0 / 2 + 1.0 / 1) / 2)


@pytest.mark.evaluation
def test_key_text_adds_the_owner_label_only_when_requested() -> None:
    # Given: one key with a Vietnamese owner label.
    key = KeyRetrievalKey(key="ui.theme.dark", key_type="preferences", label="Giao diện tối")

    # When / Then: dotted segments become words and the label is optional.
    assert key_text(key, include_label=False) == "ui theme dark"
    assert key_text(key, include_label=True) == "ui theme dark | Giao diện tối"


@pytest.mark.evaluation
def test_lexical_scores_return_zero_for_an_empty_query() -> None:
    # Given: an empty message and two key texts.
    # When: the baseline scores them.
    scores = lexical_scores("", ("ui theme dark", "food spice high"))

    # Then: no overlap exists, so nothing is preferred.
    assert scores == (0.0, 0.0)


@pytest.mark.evaluation
def test_scorer_returning_the_wrong_number_of_scores_is_rejected(tmp_path: Path) -> None:
    # Given: a scorer that drops one score.
    dataset = load_key_dataset(_written(tmp_path))

    def scorer(query: str, texts: Sequence[str]) -> Sequence[float]:  # noqa: ARG001
        return [0.0] * (len(texts) - 1)

    # When / Then: evaluation refuses the misaligned ranking.
    with pytest.raises(ValueError, match="one score per key"):
        evaluate_key_retrieval(dataset, scorer)


@pytest.mark.evaluation
def test_non_finite_scores_are_rejected(tmp_path: Path) -> None:
    # Given: a scorer that returns infinity.
    dataset = load_key_dataset(_written(tmp_path))

    # When / Then: evaluation refuses to rank on it.
    with pytest.raises(ValueError, match="finite"):
        evaluate_key_retrieval(dataset, _constant(float("inf")))


@pytest.mark.evaluation
@pytest.mark.parametrize("threshold", [-1.5, 1.5])
def test_merge_threshold_outside_the_cosine_range_is_rejected(
    tmp_path: Path, threshold: float
) -> None:
    # Given: a threshold no cosine similarity can reach.
    dataset = load_key_dataset(_written(tmp_path))

    # When / Then: evaluation refuses the meaningless threshold.
    with pytest.raises(ValueError, match="between minus one and one"):
        evaluate_key_retrieval(dataset, _constant(0.5), merge_threshold=threshold)


@pytest.mark.evaluation
def test_dataset_without_antonym_pairs_cannot_report_false_merges() -> None:
    # Given: a hand-built dataset with no opposite keys.
    dataset = KeyRetrievalDataset(
        dataset_version="test-v1",
        keys=(KeyRetrievalKey(key="ui.theme.dark", key_type="preferences", label="Tối"),),
        queries=(
            KeyRetrievalQuery(id="q1", language="vi", text="tối", expected_key="ui.theme.dark"),
        ),
        antonym_pairs=(),
    )

    # When / Then: the antonym metric cannot be computed.
    with pytest.raises(ValueError, match="antonym pairs"):
        evaluate_key_retrieval(dataset, _constant(0.5))


@pytest.mark.evaluation
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "keys": [
                    {"key": "ui.theme.dark", "key_type": "preferences", "label": "Tối"},
                    {"key": "ui.theme.dark", "key_type": "preferences", "label": "Tối"},
                ]
            },
            "unique",
        ),
        (
            {
                "queries": [
                    {"id": "q1", "language": "vi", "text": "x", "expected_key": "ui.theme.missing"}
                ]
            },
            "unknown key",
        ),
        (
            {
                "queries": [
                    {"id": "q1", "language": "vi", "text": "x", "expected_key": "ui.theme.dark"},
                    {"id": "q1", "language": "en", "text": "y", "expected_key": "ui.theme.dark"},
                ]
            },
            "Query IDs must be unique",
        ),
        (
            {
                "queries": [
                    {"id": "q1", "language": "fr", "text": "x", "expected_key": "food.spice.high"}
                ]
            },
            "language must be one of",
        ),
        ({"antonym_pairs": [["ui.theme.dark", "ui.theme.dark"]]}, "two different keys"),
        ({"antonym_pairs": [["ui.theme.dark", "ui.theme.missing"]]}, "unknown key"),
        ({"antonym_pairs": [["ui.theme.dark"]]}, "exactly two keys"),
        ({"antonym_pairs": []}, "non-empty antonym_pairs"),
        ({"keys": []}, "non-empty keys"),
        ({"queries": []}, "non-empty queries"),
        ({"dataset_version": ""}, "dataset_version"),
        ({"keys": [{"key": "ui.theme.dark", "key_type": "preferences"}]}, "label"),
    ],
)
def test_invalid_datasets_are_rejected_with_a_specific_message(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    # Given: a dataset file that breaks one validation rule.
    path = _written(tmp_path, **overrides)

    # When / Then: loading states which rule failed.
    with pytest.raises(ValueError, match=message):
        load_key_dataset(path)


@pytest.mark.evaluation
def test_unreadable_or_non_object_datasets_are_rejected(tmp_path: Path) -> None:
    # Given: a missing file and a JSON array.
    missing = tmp_path / "missing.json"
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")

    # When / Then: both are refused before any metric is computed.
    with pytest.raises(ValueError, match="could not be read"):
        load_key_dataset(missing)
    with pytest.raises(ValueError, match="must be an object"):
        load_key_dataset(array)
