# Key consistency increment report — canonical keys and local multilingual retrieval

Completed locally on 2026-09-18. This report closes the owner-authorized
cross-phase increment recorded in the
[increment plan](key-consistency-increment-plan.md). It does not start Phase 13 or
authorize Phase 14.

## Problem this increment solved

Evidence extraction, decision option extraction, and resolution learning each
produced free-form dotted target keys, and the Personal Model aggregated by exact
`(target_type, target_key, context)`. Semantically equal keys therefore never
reinforced each other: chat could learn `ui.theme.dark` while a decision extracted
`ui.theme.dark_mode`, leaving a prediction at 50/50 with no matched preference.
Two statements about one topic produced two weak entries instead of one strong
one, contradictions under different keys were never compared, and one concept was
often split into opposite keys instead of one signed axis. Word overlap could not
bridge languages at all: a Vietnamese message shared the right English key with
the provider in only 27.3% of measured cases.

## Delivered

| Step | Delivered | Verification |
|---|---|---|
| A | Known key names and shared key rules in extraction prompts; `select_known_keys` | Recorded before this plan |
| P0 | ADR-016, `synthetic-key-retrieval-v1` dataset, `evaluate_key_retrieval` harness, `scripts/key_embedding_spike.py`, model choice | 29 evaluation tests; measurements on macOS arm64 |
| P1 | `normalize_key`, `TargetKeyAlias`, `KeyAliasMap`, alias-aware `aggregate_evidence` | 398 Python tests |
| P2 | Migration `0011`, alias repository, revision bump, export and restore rules | 430 Python tests, migration from a real `0010` schema |
| P3 | Automatic normalized aliases, alias-aware prediction, owner alias API, review UI | 500 Python and 122 client tests |
| P4 | `EmbeddingProvider` port, `LocalOnnxEmbedding`, pinned artifact manager, owner-only `/v1/embedding-model`, `model_artifact` egress class | 582 Python tests with fakes |
| P5 | Extracted key labels, `key_embedding_refresh` job, semantic key retrieval, semantic merge suggestions | 698 Python and 125 client tests |
| P6 | Sidecar packaging, first real artifact run, model download UI, owner key label API and UI, documentation | `pnpm check` and `pnpm check:all`; 739 Python tests plus 12 opt-in real-model tests |

## What step P6 added

- **Packaging.** `onnxruntime`, `tokenizers`, and `numpy` are pinned in `uv.lock`
  through the optional `soulmate-daemon[embeddings]` extra, so a plain install is
  unchanged while the desktop sidecar bundles them. The sidecar grew from 42.6 MB
  to 74.7 MB; its build now fails above a 220 MB budget and smoke-tests that the
  bundled runtimes import inside the packaged one-file binary.
- **Diagnostics.** `soulmate embedding-model` reports the model, its size, its
  memory need, the artifact directory, and the runtime versions without
  downloading or loading anything. `soulmate embedding-model --verify` loads an
  installed model once, embeds a synthetic probe, and exits non-zero when that
  fails, which is how a packaged build can be proven to work on a new platform.
  The rebuilt sidecar was run that way against the downloaded artifact and
  returned a 1024-dimension vector in 974 ms including the load.
- **Owner control of the model.** The desktop `EmbeddingModelPanel` and the web
  `EmbeddingModel` screen expose the P4 API: model name and license, download
  size, memory need, progress, stop, removal, discarding a partial download, and
  an explanation when the privacy mode refuses the download.
- **Owner names for keys.** A new owner-only API (`GET`/`POST /v1/key-labels`,
  `POST /v1/key-labels/remove`) stores the owner's own wording for a key.
  Extraction may never overwrite it, a label is accepted only for a key evidence
  already uses, naming or clearing a key advances the evidence revision so the
  refresh job re-embeds it, and the audit log records only the shape of the
  change. Both clients can edit it.

## Measured result

Retrieval on the packaged `synthetic-key-retrieval-v1` dataset (168 keys, 84
Vietnamese and English messages, 27 opposite pairs), macOS arm64:

| Ranking | Vietnamese recall inside the 50-key budget |
|---|---|
| Word overlap (step A) | 27.3% |
| `bge-m3` int8, key text only | 97.7% |
| `bge-m3` int8 with owner labels | 100% |

The real artifact costs 568 MB on disk, about 1.9 GB of resident memory while
loaded, 0.37 s to load, and about 9 ms per text once warm. It is released after
`embedding.idle_release_seconds` and never runs on the chat path.

## What the first real run changed

P6 was the first step to download and execute the pinned artifact. Both SHA-256
pins matched the published files exactly, and the P0 numbers reproduced. Two
things did not survive contact with the real runtime:

1. **Every `onnxruntime` exception derives directly from `Exception`, not from
   `RuntimeError`.** `LocalOnnxEmbedding` caught `(ImportError, OSError,
   RuntimeError, ValueError)`, so a corrupt or foreign model file would have
   escaped as an unhandled error instead of degrading to the lexical ranking the
   whole design depends on. Both handlers are now broad, with two non-opt-in
   regression tests using an `Exception` subclass.
2. **Peak resident memory is about 1.9 GB, not the 1.8 GB the P0 report
   recorded.** The owner-facing estimate is now 2.0 GB so the download dialog
   never understates it. The recorded file sizes are now the exact published
   ones, which also makes the progress bar exact.

## Privacy and data ownership

- `embedding.provider` still defaults to `none`. Nothing is embedded, suggested,
  or downloaded on a fresh installation.
- A download happens only when the owner presses the button. The egress policy
  permits it as a named `model_artifact` classification over HTTPS, refuses it in
  `offline` mode, and no job, scheduler, or retry may start one.
- Every file is verified against its pinned SHA-256 before activation and deleted
  on a mismatch. Manual import remains the offline fallback.
- Key names and owner labels are personal wording, so no audit record contains
  them; only the shape of a change is stored.
- Aliases and owner labels travel in portable exports because they cannot be
  derived again. Key vectors are derived data: excluded from portable exports,
  kept in local backups, rebuildable at any time. Model artifacts are excluded
  from archives entirely.
- Deleting evidence prunes the aliases and labels that no longer have a
  supporting key.

## Verification

`pnpm check` and `pnpm check:all` passed locally on macOS arm64 on 2026-09-18:
`ruff`, `ruff format`, strict `mypy`, 739 Python tests, 54 SDK, 39 desktop, 46
web, 27 mobile, and 7 Rust tests, plus the lockfile check, pre-commit hooks, the
Python build, the web build, and the desktop build.

The 12 opt-in real-model tests are deselected by default and were run separately
against the downloaded artifact:

```sh
SOULMATE_TEST_MODEL_DIR="$DATA_DIR/models" uv run --locked pytest -m local_model
```

## Limitations

- **Remote CI is unverified.** Every result above is local.
- **Only macOS arm64 has run the real model.** Windows, Linux, and x64 remain
  unverified; the fallback to the lexical ranking on any load failure is what
  makes that acceptable, and `embedding-model --verify` exists to check a
  packaged build on those platforms.
- **`pytest-cov` is not installed,** so the increment has no coverage number.
- **`query_scores` uses pure Python dot products.** That is fine for the
  hundreds of keys measured; revisit it with a real key set in the thousands.
- **The semantic weight (3.0) and floor (0.3) in `KeySelectionPolicy` were tuned
  against a synthetic embedder**, not against real vectors. The retrieval
  measurements above score cosine similarity directly, so they do not validate
  that mix.
- **`tokenizers` pulls `huggingface-hub` transitively.** The product never
  imports it and loads the tokenizer from the verified local file only, so there
  is no second download path, but the package is present in the environment.
- **No client writes an owner merge.** `POST /v1/key-aliases` and
  `SoulmateClient.mergeKeys` exist, but the review panels only act on aliases
  that already exist. A "merge into another key" control in the preference drawer
  is the natural next step.
- **Download progress is in-memory only.** A daemon restart during a download
  loses the progress number but not the bytes; the `.part` file resumes. There is
  no durable job for it on purpose, because a download must never restart without
  the owner.
