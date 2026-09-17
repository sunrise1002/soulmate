# Key consistency increment plan — canonical keys and local multilingual retrieval

## Status and authorization

This plan was recorded on 2026-09-17 as an owner-requested cross-phase increment.
Planning is recorded; implementation has not started and requires a separate,
explicit owner instruction. The open decisions in
[Owner decisions required](#owner-decisions-required) must be answered before P2
(persistence) begins. This plan does not start Phase 13 or authorize Phase 14.

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
- The latest migration is `0010_phase_12`. The Phase 13 plan reserves
  `0011_phase_13_decision_io` and ADR-014; this increment therefore uses ADR-016.
- `privacy.mode` defaults to `strict_local`, and `EgressPolicy` denies every
  non-loopback endpoint in that mode. A model download needs an explicit design.
- `Settings` already reserves `embedding.provider = "local"` and
  `vector.backend = "sqlite_vec"`, but no code uses them.
- The macOS arm64 desktop sidecar is about 43 MB. `numpy`, `onnxruntime`, and
  `tokenizers` are not in `uv.lock`.
- Reference sizes on 2026-09-17: `onnxruntime` 1.30 macOS arm64 wheel about 22 MB;
  `tokenizers` 0.23 about 3 MB; `intfloat/multilingual-e5-small` ONNX weights
  470 MB (fp32), 235 MB (O4), 118 MB (int8 AVX-512 VNNI, x86 only). An arm64-safe
  int8 artifact must be produced or selected.
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
   - download only through an explicit owner action (see decision 2), with
     progress reporting, and a manual file import alternative;
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
| P0 | ADR-016 and spike: choose model and quantization for macOS arm64, x64, Windows, and Linux; measure recall@50 and antonym false-merge rate on a synthetic Vietnamese/English key set; measure latency, RAM, and size | Spike report; owner confirms the model |
| P1 | Core `normalize_key`, alias domain model, alias-aware aggregation (pure, no I/O) | Unit tests without an LLM |
| P2 | Migration, repositories, revision bump, export and restore | Migration test from a real `0010` schema, restart and deletion tests |
| P3 | Wire C: automatic normalized aliases, predictor and pairwise mapping, owner API and review UI | Integration and client tests |
| P4 | Embedding port, null and ONNX adapters, model manager and egress handling | Tests for failed download, SHA mismatch, offline and strict modes using fakes |
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
| RAM and CPU use | Small model, lazy loading, idle release, background job execution |
| Migration number collision with Phase 13 | Decision 1 |
| Vietnamese quality of a small model | Measured in P0 before product code is written |
| Embedding model change invalidates vectors | Vectors store `model_id` and `text_hash`; mismatches are recomputed by a job |

## Rollback

- Feature flags: `embedding.provider = "none"` (default) and
  `key_aliases.enabled`. Disabling aliases rebuilds the model from original keys,
  because evidence is never rewritten.
- The migration provides a downgrade that drops the three new tables. Run
  `soulmate backup` before upgrading.
- Model artifacts live only in `DATA_DIR/models`; deleting that directory removes
  them.

## Owner decisions required

| # | Decision | Recommendation |
|---|---|---|
| 1 | Migration number: take `0011` and move Phase 13 to `0012` (updating the Phase 13 plan), or take `0012` and wait for Phase 13 | Take `0011`; Phase 13 has not started |
| 2 | Model acquisition under `strict_local`: allow an owner-initiated download, or manual import only | Owner-initiated download with SHA-256 pinning, plus manual import |
| 3 | Merge policy: automatic only for normalized matches with semantic matches reviewed, or automatic above a similarity threshold | Normalized-only automatic merges |
| 4 | Default model: `multilingual-e5-small` int8 (about 120 MB) or a larger model (about 0.5–1.2 GB) for accuracy | `multilingual-e5-small` int8, confirmed by the P0 spike |
