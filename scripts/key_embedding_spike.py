"""Measure one ONNX embedding model against the packaged key retrieval dataset.

This is the reproducible P0 spike runner for the key consistency increment. It is
a development tool, not product code, and it never downloads anything: pass an
already installed artifact, for example the one an owner download placed in
`DATA_DIR/models/bge-m3-int8`. Since step P6 the embedding runtimes are pinned in
`uv.lock` through the `soulmate-daemon[embeddings]` extra, so the workspace
environment can run it directly:

    uv run --locked python scripts/key_embedding_spike.py --model bge-m3-int8 \
        --onnx "$DATA_DIR/models/bge-m3-int8/model_int8.onnx" \
        --tokenizer "$DATA_DIR/models/bge-m3-int8/tokenizer.json" --pooling cls

It prints one JSON object with retrieval quality, antonym similarity, latency, and
peak resident memory.
"""

import argparse
import json
import resource
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import onnxruntime as ort
from soulmate_core.evaluation import (
    KeyRetrievalDataset,
    evaluate_key_retrieval,
    key_text,
    load_key_dataset,
)
from tokenizers import Tokenizer


class OnnxEmbedder:
    """Minimal ONNX sentence embedder with CLS or mean pooling and L2 normalization."""

    def __init__(self, onnx: Path, tokenizer: Path, *, pooling: str, max_length: int) -> None:
        self._tokenizer = Tokenizer.from_file(str(tokenizer))
        self._tokenizer.enable_truncation(max_length=max_length)
        self._tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        started = time.perf_counter()
        self._session = ort.InferenceSession(str(onnx), options, providers=["CPUExecutionProvider"])
        self.load_seconds = time.perf_counter() - started
        self._inputs = {value.name for value in self._session.get_inputs()}
        self._pooling = pooling

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(list(texts))
        ids = np.array([encoding.ids for encoding in encodings], dtype=np.int64)
        mask = np.array([encoding.attention_mask for encoding in encodings], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = np.asarray(self._session.run(None, feeds)[0], dtype=np.float32)
        if hidden.ndim == 2:  # The export already pools.
            pooled = hidden
        elif self._pooling == "cls":
            pooled = hidden[:, 0]
        else:
            weights = mask.astype(np.float32)[:, :, None]
            pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled / np.clip(norms, 1e-9, None)


class CachingScorer:
    """Cosine similarity over cached vectors, applying the model's own text prefixes."""

    def __init__(self, embedder: OnnxEmbedder, key_texts: set[str], prefixes: tuple[str, str]):
        self._embedder = embedder
        self._key_texts = key_texts
        self._query_prefix, self._passage_prefix = prefixes
        self._cache: dict[str, np.ndarray] = {}
        self.embed_calls = 0

    def _vectors(self, texts: Sequence[str]) -> np.ndarray:
        missing = [text for text in dict.fromkeys(texts) if text not in self._cache]
        for start in range(0, len(missing), 32):
            batch = missing[start : start + 32]
            prefixed = [
                (self._passage_prefix if text in self._key_texts else self._query_prefix) + text
                for text in batch
            ]
            for text, vector in zip(batch, self._embedder.embed(prefixed), strict=True):
                self._cache[text] = vector
            self.embed_calls += len(batch)
        return np.stack([self._cache[text] for text in texts])

    def __call__(self, query: str, texts: Sequence[str]) -> Sequence[float]:
        vectors = self._vectors(texts)
        return [float(value) for value in vectors @ self._vectors([query])[0]]


def _peak_rss_bytes() -> float:
    """Return peak resident memory; macOS reports bytes and Linux reports kilobytes."""
    peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024.0


def _latency(embedder: OnnxEmbedder, dataset: KeyRetrievalDataset) -> dict[str, float]:
    texts = [query.text for query in dataset.queries[:20]]
    single = []
    for text in texts:
        started = time.perf_counter()
        embedder.embed([text])
        single.append((time.perf_counter() - started) * 1000.0)
    started = time.perf_counter()
    embedder.embed(texts)
    batch = (time.perf_counter() - started) * 1000.0
    single.sort()
    return {
        "single_text_median_ms": round(single[len(single) // 2], 2),
        "single_text_max_ms": round(single[-1], 2),
        "batch_20_total_ms": round(batch, 2),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Label used in the report")
    parser.add_argument("--onnx", required=True, type=Path)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--pooling", choices=("cls", "mean"), default="cls")
    parser.add_argument("--query-prefix", default="")
    parser.add_argument("--passage-prefix", default="")
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--merge-threshold", type=float, default=0.85)
    parser.add_argument("--dataset", type=Path, default=None)
    arguments = parser.parse_args(argv)

    dataset = load_key_dataset(arguments.dataset)
    embedder = OnnxEmbedder(
        arguments.onnx,
        arguments.tokenizer,
        pooling=arguments.pooling,
        max_length=arguments.max_length,
    )
    reports = {}
    for include_labels in (False, True):
        texts = set(dataset.key_texts(include_labels=include_labels))
        scorer = CachingScorer(embedder, texts, (arguments.query_prefix, arguments.passage_prefix))
        report = evaluate_key_retrieval(
            dataset,
            scorer,
            include_labels=include_labels,
            merge_threshold=arguments.merge_threshold,
        )
        reports["with_labels" if include_labels else "key_only"] = report.as_dict()
    external = arguments.onnx.parent.glob(f"{arguments.onnx.name}_data")
    disk_bytes = arguments.onnx.stat().st_size + sum(path.stat().st_size for path in external)
    print(
        json.dumps(
            {
                "model": arguments.model,
                "onnx_file_mb": round(arguments.onnx.stat().st_size / 1e6, 1),
                "artifact_mb": round(disk_bytes / 1e6, 1),
                "example_key_text": key_text(dataset.keys[0], include_label=True),
                "load_seconds": round(embedder.load_seconds, 2),
                "latency": _latency(embedder, dataset),
                "peak_rss_mb": round(_peak_rss_bytes() / 1e6, 1),
                "reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
