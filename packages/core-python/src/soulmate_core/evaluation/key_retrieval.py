"""Reproducible retrieval and antonym metrics for target key candidates.

The dataset is a synthetic Vietnamese/English personal model. It measures whether
a similarity function can put the right existing key into the limited set shared
with an extraction provider, and how close opposite keys sit, which is what makes
automatic semantic merging unsafe.
"""

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import cast

KEY_RETRIEVAL_EVALUATION_VERSION = "key-retrieval-eval-v1"
DEFAULT_KEY_DATASET_RESOURCE = "data/synthetic-key-retrieval-v1.json"
KEY_LANGUAGES = ("en", "vi")
_WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)

type SimilarityScorer = Callable[[str, Sequence[str]], Sequence[float]]


@dataclass(frozen=True, slots=True)
class KeyRetrievalKey:
    key: str
    key_type: str
    label: str


@dataclass(frozen=True, slots=True)
class KeyRetrievalQuery:
    id: str
    language: str
    text: str
    expected_key: str


@dataclass(frozen=True, slots=True)
class KeyRetrievalDataset:
    dataset_version: str
    keys: tuple[KeyRetrievalKey, ...]
    queries: tuple[KeyRetrievalQuery, ...]
    antonym_pairs: tuple[tuple[str, str], ...]

    def key_texts(self, *, include_labels: bool) -> tuple[str, ...]:
        """Return the text embedded for each key, in dataset order."""
        return tuple(key_text(key, include_label=include_labels) for key in self.keys)


@dataclass(frozen=True, slots=True)
class KeyRetrievalMetrics:
    query_count: int
    recall_at_10: float
    recall_at_50: float
    mean_reciprocal_rank: float


@dataclass(frozen=True, slots=True)
class KeyRetrievalReport:
    dataset_version: str
    evaluation_version: str
    key_count: int
    include_labels: bool
    merge_threshold: float
    overall: KeyRetrievalMetrics
    by_language: Mapping[str, KeyRetrievalMetrics]
    antonym_pair_count: int
    antonym_false_merge_rate: float
    mean_antonym_similarity: float
    max_antonym_similarity: float

    def as_dict(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))


def default_key_dataset_path() -> Path:
    """Return the packaged key retrieval dataset path in a source or wheel install."""

    resource = files("soulmate_core.evaluation").joinpath(DEFAULT_KEY_DATASET_RESOURCE)
    return Path(str(resource))


def key_text(key: KeyRetrievalKey, *, include_label: bool) -> str:
    """Return the embedded text of a key: dotted segments as words, plus its label."""

    words = key.key.replace(".", " ").replace("_", " ")
    return f"{words} | {key.label}" if include_label else words


def lexical_scores(query: str, texts: Sequence[str]) -> tuple[float, ...]:
    """Score by word overlap, the baseline the current key selection policy uses.

    Step A scores any shared word equally; Jaccard keeps that ordering and only
    breaks ties inside it, so a lexical score above zero means step A would also
    have considered the key a match.
    """
    query_words = {word for word in _WORD_PATTERN.findall(query.casefold()) if len(word) > 1}
    scores: list[float] = []
    for text in texts:
        words = {word for word in _WORD_PATTERN.findall(text.casefold()) if len(word) > 1}
        union = query_words | words
        scores.append(len(query_words & words) / len(union) if union else 0.0)
    return tuple(scores)


def _scores(scorer: SimilarityScorer, query: str, texts: Sequence[str]) -> Sequence[float]:
    scores = scorer(query, texts)
    if len(scores) != len(texts):
        raise ValueError("The scorer must return one score per key.")
    if any(not math.isfinite(score) for score in scores):
        raise ValueError("Scores must be finite.")
    return scores


def _rank_of(scores: Sequence[float], keys: Sequence[str], expected: str) -> int:
    """Return the one-based rank of ``expected``; ties are broken by key order."""

    ranked = sorted(range(len(keys)), key=lambda index: (-scores[index], keys[index]))
    return ranked.index(keys.index(expected)) + 1


def _metrics(ranks: Sequence[int]) -> KeyRetrievalMetrics:
    count = len(ranks)
    if count == 0:
        raise ValueError("Metrics need at least one query.")
    return KeyRetrievalMetrics(
        query_count=count,
        recall_at_10=sum(1 for rank in ranks if rank <= 10) / count,
        recall_at_50=sum(1 for rank in ranks if rank <= 50) / count,
        mean_reciprocal_rank=sum(1.0 / rank for rank in ranks) / count,
    )


def evaluate_key_retrieval(
    dataset: KeyRetrievalDataset,
    scorer: SimilarityScorer,
    *,
    include_labels: bool = False,
    merge_threshold: float = 0.85,
) -> KeyRetrievalReport:
    """Measure recall of the expected key and how often opposite keys look identical.

    ``merge_threshold`` is the similarity at which an automatic merge would have
    been proposed; the antonym false merge rate is the share of opposite pairs at
    or above it. Evaluation is deterministic and never touches the network.
    """
    if not -1.0 <= merge_threshold <= 1.0:
        raise ValueError("The merge threshold must be between minus one and one.")
    if not dataset.antonym_pairs:
        raise ValueError("The dataset needs antonym pairs to measure false merges.")
    keys = [key.key for key in dataset.keys]
    texts = dataset.key_texts(include_labels=include_labels)
    ranks: dict[str, list[int]] = {language: [] for language in KEY_LANGUAGES}
    for query in dataset.queries:
        scores = _scores(scorer, query.text, texts)
        ranks[query.language].append(_rank_of(scores, keys, query.expected_key))
    by_key = dict(zip(keys, texts, strict=True))
    similarities = [
        _scores(scorer, by_key[left], (by_key[right],))[0] for left, right in dataset.antonym_pairs
    ]
    pair_count = len(similarities)
    return KeyRetrievalReport(
        dataset_version=dataset.dataset_version,
        evaluation_version=KEY_RETRIEVAL_EVALUATION_VERSION,
        key_count=len(keys),
        include_labels=include_labels,
        merge_threshold=merge_threshold,
        overall=_metrics([rank for values in ranks.values() for rank in values]),
        by_language={
            language: _metrics(values) for language, values in sorted(ranks.items()) if values
        },
        antonym_pair_count=pair_count,
        antonym_false_merge_rate=sum(1 for value in similarities if value >= merge_threshold)
        / pair_count,
        mean_antonym_similarity=sum(similarities) / pair_count,
        max_antonym_similarity=max(similarities),
    )


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value


def _load_key(value: object, index: int) -> KeyRetrievalKey:
    if not isinstance(value, dict):
        raise ValueError(f"Key {index} must be an object.")
    return KeyRetrievalKey(
        key=_text(value.get("key"), f"Key {index} key"),
        key_type=_text(value.get("key_type"), f"Key {index} key_type"),
        label=_text(value.get("label"), f"Key {index} label"),
    )


def _load_query(value: object, index: int, known: set[str]) -> KeyRetrievalQuery:
    if not isinstance(value, dict):
        raise ValueError(f"Query {index} must be an object.")
    language = _text(value.get("language"), f"Query {index} language")
    if language not in KEY_LANGUAGES:
        raise ValueError(f"Query {index} language must be one of {', '.join(KEY_LANGUAGES)}.")
    expected = _text(value.get("expected_key"), f"Query {index} expected_key")
    if expected not in known:
        raise ValueError(f"Query {index} expects unknown key {expected!r}.")
    return KeyRetrievalQuery(
        id=_text(value.get("id"), f"Query {index} id"),
        language=language,
        text=_text(value.get("text"), f"Query {index} text"),
        expected_key=expected,
    )


def _load_pair(value: object, index: int, known: set[str]) -> tuple[str, str]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"Antonym pair {index} must hold exactly two keys.")
    left = _text(value[0], f"Antonym pair {index} first key")
    right = _text(value[1], f"Antonym pair {index} second key")
    if left == right:
        raise ValueError(f"Antonym pair {index} must name two different keys.")
    if not known.issuperset({left, right}):
        raise ValueError(f"Antonym pair {index} references an unknown key.")
    return (left, right)


def load_key_dataset(path: Path | None = None) -> KeyRetrievalDataset:
    """Load and strictly validate a synthetic key retrieval dataset."""

    resolved = path if path is not None else default_key_dataset_path()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Key retrieval dataset could not be read as JSON.") from exc
    if not isinstance(raw, dict):
        raise ValueError("The dataset must be an object.")
    version = _text(raw.get("dataset_version"), "dataset_version")
    raw_keys = raw.get("keys")
    raw_queries = raw.get("queries")
    raw_pairs = raw.get("antonym_pairs")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise ValueError("The dataset must hold a non-empty keys array.")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError("The dataset must hold a non-empty queries array.")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ValueError("The dataset must hold a non-empty antonym_pairs array.")
    keys = tuple(_load_key(value, index) for index, value in enumerate(raw_keys))
    known = {key.key for key in keys}
    if len(known) != len(keys):
        raise ValueError("Dataset keys must be unique.")
    queries = tuple(_load_query(value, index, known) for index, value in enumerate(raw_queries))
    if len({query.id for query in queries}) != len(queries):
        raise ValueError("Query IDs must be unique.")
    return KeyRetrievalDataset(
        dataset_version=version,
        keys=keys,
        queries=queries,
        antonym_pairs=tuple(
            _load_pair(value, index, known) for index, value in enumerate(raw_pairs)
        ),
    )
