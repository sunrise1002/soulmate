"""The real pinned embedding model, exercised end to end.

These checks are the only ones in the suite that load a 568 MB artifact, so they
are opt-in: they are deselected by default and run with

    SOULMATE_TEST_MODEL_DIR=<DATA_DIR>/models uv run --locked pytest -m local_model

Everything else uses fakes. The point here is the code no fake can reach: the
ONNX session, its padding and pooling, the pinned hashes of the published files,
and real 1024-dimension vectors surviving a round trip through SQLite.
"""

import json
import os
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest
from soulmate_core.embeddings import EmbeddingUnavailableError
from soulmate_core.evaluation import evaluate_key_retrieval, load_key_dataset
from soulmate_daemon.cli import _embedding_model
from soulmate_daemon.config import Settings
from soulmate_daemon.embeddings import LocalOnnxEmbedding
from soulmate_daemon.key_semantics import KeySemanticsService
from soulmate_daemon.model_artifacts import (
    BGE_M3_INT8,
    ModelArtifactError,
    ModelArtifactStore,
    file_sha256,
)

from .key_alias_support import NOW, PROFILE, add_evidence, add_profile, open_storage

pytestmark = [pytest.mark.integration, pytest.mark.local_model]

# Read before the isolating fixture clears the environment for every test.
MODEL_ROOT = os.environ.get("SOULMATE_TEST_MODEL_DIR")
IDLE = timedelta(seconds=30)
DARK = "ui.theme.dark"
LIGHT = "ui.theme.light"
VOLUME = "notifications.volume"
VIETNAMESE_DARK = "mình thích giao diện tối"

# Measured on macOS arm64 in the P0 spike and again when P6 downloaded the artifact.
RECORDED_VIETNAMESE_RECALL_AT_50 = 0.977


def _store() -> ModelArtifactStore:
    if MODEL_ROOT is None:
        pytest.skip("Set SOULMATE_TEST_MODEL_DIR to the models directory of an installed artifact.")
    store = ModelArtifactStore(BGE_M3_INT8, Path(MODEL_ROOT) / BGE_M3_INT8.model_id)
    if not store.installed():
        pytest.skip(f"The pinned artifact is not installed in {store.directory}.")
    return store


@pytest.fixture(scope="module")
def provider() -> LocalOnnxEmbedding:
    """Load the model once; every check below only reads from it."""
    return LocalOnnxEmbedding(_store(), idle_timeout=IDLE)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_installed_artifact_files_match_their_pinned_hashes() -> None:
    # Given: the artifact the owner downloaded from the pinned URLs
    store = _store()

    # When: every stored file is hashed
    digests = {file.name: file_sha256(store.path(file)) for file in BGE_M3_INT8.files}

    # Then: the published bytes are exactly what the code pins
    assert digests == {file.name: file.sha256 for file in BGE_M3_INT8.files}


def test_stored_file_sizes_match_the_sizes_shown_before_a_download() -> None:
    # Given: the sizes the download dialog shows the owner
    store = _store()

    # When: the installed files are measured
    sizes = {file.name: store.path(file).stat().st_size for file in BGE_M3_INT8.files}

    # Then: the progress bar counts toward the real totals
    assert sizes == {file.name: file.approximate_bytes for file in BGE_M3_INT8.files}


def test_embedding_returns_normalized_vectors_of_the_pinned_dimension(
    provider: LocalOnnxEmbedding,
) -> None:
    # Given: a ready model and two texts
    assert provider.ready

    # When: both are embedded in one batch of different lengths
    vectors = provider.embed(("ui theme dark | giao diện tối", "a"))

    # Then: pooling and L2 normalization produced unit vectors of the pinned width
    assert len(vectors) == 2
    assert {len(vector) for vector in vectors} == {BGE_M3_INT8.dimensions}
    for vector in vectors:
        assert _cosine(vector, vector) == pytest.approx(1.0, abs=1e-4)


def test_a_vietnamese_message_ranks_its_english_key_above_an_opposite_key(
    provider: LocalOnnxEmbedding,
) -> None:
    # Given: one Vietnamese message and three English key texts
    query, dark, light, volume = provider.embed(
        (VIETNAMESE_DARK, "ui theme dark", "ui theme light", "notifications volume")
    )

    # When: the message is compared with each key
    scores = (_cosine(query, dark), _cosine(query, light), _cosine(query, volume))

    # Then: the right key wins, which word overlap alone cannot do across languages
    assert scores[0] > scores[1] > scores[2]


def test_semantic_retrieval_reaches_the_recorded_vietnamese_recall(
    provider: LocalOnnxEmbedding,
) -> None:
    # Given: the packaged synthetic dataset and a cache over the real model
    dataset = load_key_dataset()
    cache: dict[str, tuple[float, ...]] = {}

    def vectors(texts: Sequence[str]) -> list[tuple[float, ...]]:
        missing = [text for text in dict.fromkeys(texts) if text not in cache]
        for start in range(0, len(missing), 32):
            batch = missing[start : start + 32]
            cache.update(zip(batch, provider.embed(batch), strict=True))
        return [cache[text] for text in texts]

    def scorer(query: str, texts: Sequence[str]) -> Sequence[float]:
        embedded = vectors([query, *texts])
        return [_cosine(embedded[0], candidate) for candidate in embedded[1:]]

    # When: retrieval is measured without owner labels, the worst supported case
    report = evaluate_key_retrieval(dataset, scorer, include_labels=False, merge_threshold=0.85)

    # Then: the shared 50-key budget still contains the right key as P0 measured
    assert report.by_language["vi"].recall_at_50 >= RECORDED_VIETNAMESE_RECALL_AT_50
    # And: opposite keys stay close, so similarity may never merge keys by itself
    assert report.antonym_false_merge_rate > 0.0


def test_real_vectors_survive_storage_and_rank_a_vietnamese_query(tmp_path: Path) -> None:
    # Given: three used keys in a migrated database and the real provider
    _, repositories = open_storage(tmp_path / "keys.sqlite3")
    add_profile(repositories)
    for index, key in enumerate((DARK, LIGHT, VOLUME)):
        add_evidence(repositories, f"evidence_{index}", key)
    service = KeySemanticsService(
        evidence=repositories.evidence,
        catalog=repositories.key_catalog,
        embeddings=repositories.key_embeddings,
        aliases=repositories.key_aliases,
        provider=LocalOnnxEmbedding(_store(), idle_timeout=IDLE),
        threshold=0.85,
    )

    # When: the refresh job embeds them and a Vietnamese message is scored
    refresh = service.refresh(PROFILE, NOW)
    scores = service.query_scores(PROFILE, VIETNAMESE_DARK)

    # Then: float32 storage kept the ranking the model produced
    assert refresh.embedded_count == 3
    assert max(scores, key=lambda key: scores[key]) == DARK
    assert scores[DARK] > scores[LIGHT] > scores[VOLUME]


def test_an_unreadable_weights_file_reports_the_model_as_unavailable(tmp_path: Path) -> None:
    # Given: a store whose weights file is present but not a model
    installed = _store()
    directory = tmp_path / BGE_M3_INT8.model_id
    directory.mkdir()
    (directory / BGE_M3_INT8.weights_file).write_bytes(b"not an onnx graph")
    (directory / BGE_M3_INT8.tokenizer_file).write_bytes(installed.tokenizer_path.read_bytes())
    provider = LocalOnnxEmbedding(ModelArtifactStore(BGE_M3_INT8, directory), idle_timeout=IDLE)

    # When: it is asked to embed
    with pytest.raises(EmbeddingUnavailableError) as failure:
        provider.embed(("giao diện tối",))

    # Then: the caller can fall back to lexical ranking instead of failing a request
    assert str(failure.value) == "The embedding model could not be loaded."
    assert provider.ready


def test_a_missing_artifact_reports_the_model_as_unavailable(tmp_path: Path) -> None:
    # Given: a store with no files at all
    provider = LocalOnnxEmbedding(
        ModelArtifactStore(BGE_M3_INT8, tmp_path / "absent"), idle_timeout=IDLE
    )

    # When: it is asked to embed
    with pytest.raises(EmbeddingUnavailableError) as failure:
        provider.embed(("giao diện tối",))

    # Then: nothing is downloaded and the model is simply not ready
    assert str(failure.value) == "The embedding model is not installed."
    assert not provider.ready


def test_importing_a_file_whose_contents_are_wrong_is_rejected(tmp_path: Path) -> None:
    # Given: a file with a pinned name but unpinned contents
    source = tmp_path / BGE_M3_INT8.tokenizer_file
    source.write_bytes(b"{}")
    store = ModelArtifactStore(BGE_M3_INT8, tmp_path / BGE_M3_INT8.model_id)

    # When: the owner imports it as the offline fallback
    with pytest.raises(ModelArtifactError) as failure:
        store.import_file(BGE_M3_INT8.tokenizer_file, source)

    # Then: verification refuses it and leaves nothing behind
    assert str(failure.value) == "tokenizer.json failed SHA-256 verification and was discarded."
    assert not store.installed()
    assert not store.path(BGE_M3_INT8.file(BGE_M3_INT8.tokenizer_file)).exists()


def test_importing_the_real_tokenizer_activates_it(tmp_path: Path) -> None:
    # Given: the published tokenizer file the owner obtained elsewhere
    installed = _store()
    store = ModelArtifactStore(BGE_M3_INT8, tmp_path / BGE_M3_INT8.model_id)

    # When: the owner installs it as the offline fallback
    status = store.import_file(BGE_M3_INT8.tokenizer_file, installed.tokenizer_path)

    # Then: it is activated, while the weights file is still reported as missing
    names = {item.name: item.installed for item in status.files}
    assert names == {BGE_M3_INT8.tokenizer_file: True, BGE_M3_INT8.weights_file: False}
    assert not status.installed


def test_the_model_is_released_when_it_stays_idle(provider: LocalOnnxEmbedding) -> None:
    # Given: a model loaded by a first call
    provider.embed(("giao diện tối",))

    # When: the idle period passes and the provider is asked to release
    released = LocalOnnxEmbedding(_store(), idle_timeout=timedelta(0))
    released.embed(("giao diện tối",))
    released.release_if_idle()

    # Then: the next call reloads and still produces a usable vector
    again = released.embed(("giao diện tối",))
    assert len(again[0]) == BGE_M3_INT8.dimensions


def test_the_verify_command_loads_the_installed_model(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: the installed artifact, reached through the configured data directory
    store = _store()
    settings = Settings(data_dir=store.directory.parent.parent)

    # When: the owner runs the verification the packaged binary also offers
    code = _embedding_model(settings, True)
    report = json.loads(capsys.readouterr().out)

    # Then: the real runtime produced a vector of the pinned width
    assert code == 0
    assert report["verified"] is True
    assert report["dimensions"] == BGE_M3_INT8.dimensions
    assert report["runtime_available"] is True
