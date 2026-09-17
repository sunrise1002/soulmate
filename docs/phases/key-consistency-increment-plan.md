# Key consistency increment plan — canonical keys and local multilingual retrieval

## Status and authorization

This plan was recorded on 2026-09-17 as an owner-requested cross-phase increment.
Planning is recorded and the owner answered all open decisions on 2026-09-17
(see [Owner decisions](#owner-decisions)). On 2026-09-17 the owner authorized
implementation; steps P1 and P2 are complete locally, and steps P3, P0, and P4
are complete locally on 2026-09-18. Step P0 produced
[ADR-016](../architecture/decisions/ADR-016-local-multilingual-key-embeddings.md)
and the [P0 spike report](key-consistency-p0-spike-report.md), and the owner
confirmed `bge-m3` int8 as the default model and quantization on 2026-09-18.
Steps P5 and P6 have not started and each still stops for verification. This plan does not start
Phase 13 or authorize Phase 14. Temporary hand-over notes for the next session live in
[working notes](key-consistency-increment-progress.md); delete that file when the
increment finishes.

Parts B (multilingual labels and local embeddings) and C (key canonicalization and
aliases) change persistence, add native runtime dependencies, and introduce a
network download. They are therefore treated as critical changes: each step below
ends with a verification checkpoint before the next step starts.

## Problem

Evidence extraction, decision option extraction, and resolution learning all
produce free-form dotted target keys. The Personal Model aggregates by exact
`(target_type, target_key, context)`, and the decision predictor matches option
features by exact key or identical token set. Semantically equal keys therefore
fail to reinforce each other:

- chat learned `ui.theme.dark` while a decision extracted `ui.theme.dark_mode`,
  so the prediction had no matched preference and returned 50/50;
- two statements about the same topic can create two weak entries instead of one
  stronger entry, and contradictions under different keys are never compared;
- one concept is often split into opposite keys (`ui.theme.dark` and
  `ui.theme.light`) instead of one signed axis.

## Delivered before this plan (step A, no persistence change)

Recorded in `CHANGELOG.md` and `docs/phase-status.md` on 2026-09-17:

- chat and natural decision extraction receive known key names (never values) and
  shared key rules: reuse a matching known key, otherwise prefer a listed
  namespace, and model opposites as one signed axis;
- `select_known_keys` in `soulmate_core.context` shares every key for models with
  at most 100 keys; larger models share all namespaces plus 50 keys ranked by use in
  the same conversation or same-domain resolved decisions, word overlap, domain,
  confidence, and recency;
- `ModelRebuilder.current()` and read-only `current_model()` replace duplicated
  snapshot-freshness checks.

Remaining gaps: word overlap cannot bridge languages (Vietnamese message versus
English key), the provider may ignore the reuse rule, and existing near-duplicate
keys stay separate.

## Current-state findings

- Aggregation lives in `soulmate_core/preferences/aggregation.py` and groups by
  exact key. Evidence is immutable, so key mapping can be applied at aggregation
  time without rewriting provenance.
- The latest migration is `0010_phase_12`. By owner decision this increment uses
  migration `0011`, and the Phase 13 plan moved to `0012_phase_13_decision_io`.
  ADR-014 stays reserved for Phase 13; this increment uses ADR-016.
- `privacy.mode` defaults to `strict_local`, and `EgressPolicy` denies every
  non-loopback endpoint in that mode. A model download needs an explicit design.
- `Settings` already reserves `embedding.provider = "local"` and
  `vector.backend = "sqlite_vec"`, but no code uses them.
- The macOS arm64 desktop sidecar is about 43 MB. `numpy`, `onnxruntime`, and
  `tokenizers` are not in `uv.lock`.
- Reference sizes on 2026-09-17: `onnxruntime` 1.30 macOS arm64 wheel about 22 MB;
  `tokenizers` 0.23 about 3 MB. MIT-licensed multilingual ONNX weights:

  | Model | fp32 | fp16 / O4 | int8 |
  |---|---|---|---|
  | `BAAI/bge-m3` (ONNX exports in `Xenova/bge-m3`) | 2267 MB | 1134 MB | 568 MB |
  | `intfloat/multilingual-e5-large` | 2235 MB | — | 562 MB (AVX-512 VNNI, x86 only) |
  | `intfloat/multilingual-e5-base` | 1110 MB | 555 MB | 278–279 MB |
  | `intfloat/multilingual-e5-small` | 470 MB | 235 MB | 118 MB (AVX-512 VNNI, x86 only) |

  The license and redistribution terms of any third-party ONNX export must be
  confirmed in P0 before pinning it.
- `fastembed` was considered and rejected as the default: it adds `pillow`,
  `huggingface-hub`, `loguru`, and other dependencies, and downloads models itself,
  bypassing the central egress policy and artifact pinning.

## Design

### C — canonicalization and aliases

1. `normalize_key()` in the core, versioned as `key-normalizer-v1`: casefold, trim,
   convert spaces, `-`, and `/` to `_`, collapse repeated dots, and drop a short
   filler list (`mode`, `preference`, `setting`, `level`) from the final segment.
   Example: `ui.theme.dark_mode` becomes `ui.theme.dark`.
2. Table `target_key_aliases`: `profile_id`, `target_type`, `alias_key`,
   `canonical_key`, `polarity` (+1 or -1), `method` (`normalized`, `semantic`,
   `owner`), `similarity`, `status` (`active`, `suggested`, `rejected`),
   `algorithm_version`, and timestamps.
3. `aggregate_evidence(evidence, aliases)` maps each evidence key to its canonical
   key and multiplies preference values by the alias polarity. Evidence keeps its
   original key. Removing an alias and rebuilding restores the previous grouping.
4. Every alias change advances the profile evidence revision so
   `ModelRebuilder.current()` rebuilds.
5. The decision predictor and pairwise learner map option feature keys through
   active aliases before matching.
6. Merge policy after extraction review:
   - normalized keys are equal: create an `active` alias automatically;
   - semantic similarity only: create a `suggested` alias for owner review
     (merge, merge inverted, reject). Embeddings place antonyms such as `dark` and
     `light` close together, so semantic matches never merge automatically;
   - otherwise: keep a new key.
7. Owner-only API to list, approve, reject, invert, and undo aliases, plus a
   "possible duplicate keys" review list in the desktop and web Model screens.

### B — multilingual labels and local embeddings

1. Core port `EmbeddingProvider` with adapters:
   - `NullEmbedding`, the default until the owner enables embeddings;
   - `LocalOnnxEmbedding`, using `onnxruntime`, `tokenizers`, and `numpy`, loaded
     lazily and released after an idle period.
2. Model manager:
   - pinned artifact URL and SHA-256, stored under `DATA_DIR/models`;
   - download only when the owner presses a download button in the client, which
     shows the model name, download size, disk and memory needs, and progress; the
     request passes the central egress policy as an explicit owner-initiated
     `model_artifact` download, which is permitted even in `strict_local` mode and
     never happens automatically;
   - resumable download, SHA-256 verification before activation, and removal of
     partial files on failure; manual file import remains an offline fallback;
   - disabled in `offline` mode; any load failure falls back to step A.
3. Table `target_key_catalog`: owner-editable label and aliases in the owner's
   language per key. The extraction wire schema gains optional `label` and
   `aliases` string fields, keeping the portable schema simple.
4. Table `target_key_embeddings`: `key`, `text_hash`, `model_id`, `dim`, `vector`.
   It is derived and rebuildable, excluded from portable exports, and fully
   recomputed by a durable background job when the model changes.
5. `select_known_keys` adds a semantic score from cosine similarity between the
   message and each key plus label. Search is brute force with `numpy`, sufficient
   for tens of thousands of keys; `sqlite-vec` stays deferred until needed.
   Embeddings are computed inside the existing background learning job, so chat
   latency is unchanged.
6. Data ownership: database backups include the new tables; portable exports
   include owner alias decisions and owner-edited labels because they cannot be
   derived from evidence; evidence deletion removes aliases and embeddings that no
   longer have supporting keys.

## Increments

Each increment stops for verification before the next one starts.

| Step | Scope | Verification |
|---|---|---|
| P0 | ADR-016 and accuracy-first spike: compare `bge-m3` (fp16 and int8) with `multilingual-e5-large` and `multilingual-e5-base`; measure recall@50 and antonym false-merge rate on a synthetic Vietnamese/English key set, plus latency, RAM, and size — complete on 2026-09-18 | [Spike report](key-consistency-p0-spike-report.md): measured on macOS arm64 only; owner confirmed `bge-m3` int8. x64, Windows, and Linux move to P6 |
| P1 | Core `normalize_key`, alias domain model, alias-aware aggregation (pure, no I/O) — complete on 2026-09-17 | Unit tests without an LLM: passed locally (398 Python tests, strict typing, lint) |
| P2 | Migration, repositories, revision bump, export and restore — complete on 2026-09-17 | Migration test from a real `0010` schema, restart and deletion tests: passed locally (430 Python tests, strict typing, lint) |
| P3 | Wire C: automatic normalized aliases, predictor and pairwise mapping, owner API and review UI — complete on 2026-09-18 | Integration and client tests: passed locally (`pnpm check`, 500 Python tests and 122 client tests) |
| P4 | Embedding port, null and ONNX adapters, model manager and egress handling — complete on 2026-09-18 | Tests for failed download, SHA mismatch, offline and strict modes using fakes: passed locally (`pnpm check`, 582 Python tests). The real ONNX runtime and the real artifact are still unexercised; they belong to P6 |
| P5 | Extraction labels, embedding and backfill job, semantic scoring, semantic alias suggestions | "giao diện tối" retrieves `ui.theme.dark` in an integration test with a fake embedder |
| P6 | Sidecar packaging with `onnxruntime`, size check, smoke test; documentation, changelog, phase status | `pnpm check:all` and a sidecar build |

Unit tests continue to avoid network access and real models; the ONNX adapter is
exercised by an opt-in test marker and the P6 smoke test.

## Risks

| Risk | Mitigation |
|---|---|
| Wrong merges, especially antonyms | Only normalized matches merge automatically; semantic matches need owner review; every alias can be undone |
| Model download conflicts with `strict_local` | Download only on explicit owner action with SHA-256 verification, or manual import |
| Native runtime differences on Windows and Linux | P0 spike and P6 smoke test; fall back to step A when loading fails |
| RAM, CPU, and disk use of an accuracy-first model (roughly 0.6–1.2 GB on disk and more in memory) | Lazy loading, idle release, background job execution, size and memory shown before download, P0 measurements; int8 is used when its accuracy loss is negligible |
| Large download on slow or metered connections | Owner-initiated only, resumable, cancellable, with manual import |
| Migration number collision with Phase 13 | Decision 1 |
| Vietnamese retrieval quality | Measured in P0 before product code is written |
| Embedding model change invalidates vectors | Vectors store `model_id` and `text_hash`; mismatches are recomputed by a job |

## Rollback

- Feature flags: `embedding.provider = "none"` (default) and
  `key_aliases.enabled`. Disabling aliases rebuilds the model from original keys,
  because evidence is never rewritten.
- The migration provides a downgrade that drops the three new tables. Run
  `soulmate backup` before upgrading.
- Model artifacts live only in `DATA_DIR/models`; deleting that directory removes
  them.

## Owner decisions

Recorded on 2026-09-17.

| # | Question | Decision |
|---|---|---|
| 1 | Migration number relative to Phase 13 | This increment takes `0011`; Phase 13 moves to `0012_phase_13_decision_io` and its plan was updated |
| 2 | Model acquisition under `strict_local` | Allowed only when the owner presses the download button, with SHA-256 pinning; manual import stays available as an offline fallback |
| 3 | Merge policy | Automatic aliases only for equal normalized keys; semantic matches are suggestions that require owner review |
| 4 | Default model | Accuracy first: `bge-m3` is the leading candidate (about 1.13 GB fp16 or 568 MB int8), compared in P0 with `multilingual-e5-large` and `multilingual-e5-base`; `multilingual-e5-small` is not the default |
| 5 | Model and quantization confirmed after the P0 measurements (2026-09-18) | `bge-m3` int8 (568 MB): equal retrieval quality to fp16 at half the size and a third of the latency, the only candidate with a portable non-x86 int8 export, and the widest separation between opposite keys |
