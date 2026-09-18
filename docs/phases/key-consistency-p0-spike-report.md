# Key consistency increment — P0 spike report

Step P0 of the [key consistency increment plan](key-consistency-increment-plan.md),
executed on 2026-09-18 under the owner authorization recorded on 2026-09-17. It
produced [ADR-016](../architecture/decisions/ADR-016-local-multilingual-key-embeddings.md)
and the measurements below. No product behavior changed in this step: the spike
added a reproducible dataset and metric harness, and a development-only runner.

## Question

Can a locally runnable multilingual embedding model put the right existing target
key inside the 50-key budget that `select_known_keys` shares with an extraction
provider when the owner writes Vietnamese and the keys are English — and can
similarity ever be trusted to merge two keys automatically?

## Method

`soulmate_core.evaluation.key_retrieval` loads a validated synthetic dataset and
computes deterministic metrics against any similarity function. It performs no
I/O and never reaches the network.

- Dataset `synthetic-key-retrieval-v1`: 168 dotted keys across 18 namespaces, each
  with a Vietnamese owner label; 84 messages (44 Vietnamese, 40 English) each
  annotated with the one key it should reinforce; 27 antonym pairs such as
  `ui.theme.dark` / `ui.theme.light`. It is synthetic and contains no owner data.
- `recall@50` is the share of messages whose expected key is ranked inside the
  50-key budget; `recall@10` and mean reciprocal rank show headroom. Ties are
  broken by key name, so every run is reproducible.
- The antonym false merge rate is the share of opposite pairs whose similarity is
  at or above a candidate automatic-merge threshold of 0.85.
- Each model was measured twice: on key text alone (`ui theme dark`) and on key
  text plus the owner label (`ui theme dark | Giao diện tối`), which is what step
  P5 would store in `target_key_catalog`.
- The baseline is `lexical_scores`, the word-overlap rule the current key
  selection policy uses.

Environment: macOS 25.4 arm64 (Mac15,6, 18 GB RAM), Python 3.12.4,
`onnxruntime` 1.30.0, `tokenizers` 0.23.2, `numpy` 2.5.3, CPU execution provider, four intra-op
threads, 128-token truncation. Models were downloaded manually into a throwaway
environment; nothing was added to `uv.lock`.

Reproduce with:

```sh
uv venv /tmp/key-spike/.venv
uv pip install --python /tmp/key-spike/.venv/bin/python onnxruntime tokenizers numpy
# download the artifact, then:
PYTHONPATH=packages/core-python/src /tmp/key-spike/.venv/bin/python \
  scripts/key_embedding_spike.py --model bge-m3-int8 \
  --onnx /tmp/key-spike/models/bge-m3.int8.onnx \
  --tokenizer /tmp/key-spike/models/bge-m3.tokenizer.json --pooling cls
```

## Retrieval results

Recall of the expected key, key text only:

| Scorer | Artifact | vi recall@50 | en recall@50 | recall@10 | MRR |
| --- | --- | --- | --- | --- | --- |
| Word overlap (step A baseline) | none | 0.273 | 0.625 | 0.238 | 0.180 |
| `bge-m3` int8 | 568 MB | 0.977 | 0.975 | 0.940 | 0.797 |
| `bge-m3` fp16 | 1134 MB | 0.977 | 1.000 | 0.952 | 0.815 |
| `multilingual-e5-base` O4 | 555 MB | 1.000 | 1.000 | 0.976 | 0.818 |
| `multilingual-e5-large` fp32 | 2236 MB | 1.000 | 1.000 | 1.000 | 0.873 |

With Vietnamese owner labels added to the key text, every model reaches
recall@50 = 1.000 in both languages; `bge-m3` int8 rises to recall@10 = 0.988 and
MRR = 0.863, matching `bge-m3` fp16 within noise. Labels are therefore valuable
but not required for the 50-key budget.

## Cost

| Model | Artifact | Load | Median latency per text | 20 texts batched | Peak RSS |
| --- | --- | --- | --- | --- | --- |
| `bge-m3` int8 | 568 MB | 0.38 s | 10.8 ms | 189 ms | 1765 MB |
| `bge-m3` fp16 | 1134 MB | 1.98 s | 29.5 ms | 518 ms | 2676 MB |
| `multilingual-e5-base` O4 | 555 MB | 0.27 s | 8.7 ms | 159 ms | 2135 MB |
| `multilingual-e5-large` fp32 | 2236 MB | 1.95 s | 29.1 ms | 542 ms | 1751 MB |

Peak RSS is the whole process including memory-mapped weights and the
`onnxruntime` arena, measured with one model per process. It is an upper bound for
sizing, not a working-set measurement, and it is why the adapter must load lazily
and release after idle.

The `multilingual-e5` int8 exports are `qint8_avx512_vnni` builds and are x86-only;
they cannot be measured or shipped for arm64. `bge-m3` is the only candidate with a
portable int8 export, which decided the quantization question on its own.

## Antonym finding

Similarity cannot separate "the same concept" from "the opposite concept":

| Model | Text | Median correct match | Median antonym pair | Max antonym pair | Antonyms above the median correct match |
| --- | --- | --- | --- | --- | --- |
| `bge-m3` int8 | key only | 0.644 | 0.809 | 0.866 | 27 of 27 |
| `bge-m3` int8 | key + label | 0.669 | 0.795 | 0.871 | 26 of 27 |
| `multilingual-e5-base` O4 | key only | 0.819 | 0.946 | 0.977 | 27 of 27 |
| `multilingual-e5-base` O4 | key + label | 0.846 | 0.968 | 0.987 | 27 of 27 |

Every opposite pair is more similar to its opposite than a typical correct
message-to-key match is. At a 0.85 threshold the false merge rate is 0.259 for
`bge-m3` int8 and 1.000 for both `multilingual-e5` models. Lowering the threshold
to remove false merges removes true matches first. Owner decision 3 — semantic
matches are only ever `suggested` and never merge automatically — is therefore a
measured invariant, and `e5`'s compressed similarity range would additionally make
its suggestions much noisier.

## Decisions

1. Default model and quantization: **`bge-m3` int8**, confirmed by the owner on
   2026-09-18. `multilingual-e5-large` was rejected on size and lack of a portable
   quantized export; `multilingual-e5-base` on antonym behavior; `bge-m3` fp16 on
   cost for no measurable quality gain.
2. Pinned artifacts for step P4, downloaded from `https://huggingface.co`:

   | File | Path | SHA-256 |
   | --- | --- | --- |
   | Weights | `Xenova/bge-m3/resolve/main/onnx/model_int8.onnx` | `a206e10e995aa2a833924bcd725ba5dd6c3425cd34bac3cf2b5677cd2a1c51d6` |
   | Tokenizer | `Xenova/bge-m3/resolve/main/tokenizer.json` | `6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790` |

   Both are MIT licensed, as is the upstream `BAAI/bge-m3` model. Verify the hash
   again when P4 pins it; an upstream re-upload must be a deliberate change.
3. Pooling and text form: CLS pooling with L2 normalization, no instruction
   prefix, 128-token truncation, and key text written as dotted segments split
   into words plus the owner label when one exists.
4. Owner labels are a quality improvement, not a prerequisite, so P5 may ship
   semantic scoring before the catalog UI is complete.

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result |
| --- | --- | --- | --- |
| P0-T01 | Packaged dataset | Normal | Loads with both languages, over 100 keys, and antonym pairs |
| P0-T02 | Scorer that ranks the expected key first | Normal | recall@10, recall@50, and MRR are 1.0 |
| P0-T03 | Scorer that ranks the expected key last | Boundary | Recall is 0.0 and MRR is exactly 1/168 |
| P0-T04 | Word-overlap baseline on the packaged dataset | Regression | Vietnamese recall@50 stays below 0.5 and below English |
| P0-T05 | Antonym similarity exactly at the threshold | Boundary | Counted as a false merge; 0.0001 below is not |
| P0-T06 | Every score identical | Boundary | Ties break by key name and two runs are equal |
| P0-T07 | Key with and without a label | Normal | Dotted segments become words; the label is appended only when asked |
| P0-T08 | Empty query text | Empty | All lexical scores are 0.0 |
| P0-T09 | Scorer returning too few scores | Abnormal | `ValueError` naming one score per key |
| P0-T10 | Scorer returning infinity | Abnormal | `ValueError` naming finite scores |
| P0-T11 | Merge threshold of -1.5 or 1.5 | Boundary | `ValueError` naming the cosine range |
| P0-T12 | Dataset without antonym pairs | Abnormal | `ValueError`; the false merge rate cannot be invented |
| P0-T13 | Duplicate keys, duplicate query IDs | Abnormal | `ValueError` naming uniqueness |
| P0-T14 | Query expecting an unknown key; antonym pair naming an unknown key | Abnormal | `ValueError` naming the unknown key |
| P0-T15 | Antonym pair naming one key twice or holding one key | Abnormal | `ValueError` |
| P0-T16 | Unsupported query language | Invalid value | `ValueError` listing the supported languages |
| P0-T17 | Empty keys, queries, antonym pairs, or `dataset_version`; missing label | Empty / NULL | `ValueError` per field |
| P0-T18 | Missing file and a JSON array instead of an object | Abnormal | `ValueError` before any metric is computed |

`0`, minimum, and maximum boundaries are covered through rank 1, rank 168, the
threshold equality case, and empty collections. There is no upper bound on key or
query count to test; large-scale search cost is a step P5 concern.

## Verification

```sh
uv run --locked ruff check . && uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
```

Ruff, `ruff format --check`, strict `mypy`, and the full Python suite passed
locally on macOS arm64, including 29 evaluation tests for this harness. Coverage
is not reported because `pytest-cov` is not installed in this workspace.

The ONNX measurements are not part of the automated suite: they need models and
dependencies that are deliberately absent from `uv.lock`. `scripts/key_embedding_spike.py`
reproduces them from a throwaway environment.

## Limits

- Measured only on macOS arm64. Windows, Linux, and x64 remain unverified; step P6
  owns that smoke test, and the step A fallback exists for load failures.
- The dataset is synthetic and written by one author, so absolute recall is
  optimistic; the comparison between scorers is the useful signal.
- Only single-key retrieval was measured. Messages that legitimately touch several
  keys, and the ranking mix with recency and domain scores, belong to step P5.
- No product code loads a model yet. The download flow, egress `model_artifact`
  handling, resumability, SHA verification, and idle release are step P4 and are
  only designed here.
