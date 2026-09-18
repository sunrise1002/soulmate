# Key consistency increment — working notes (temporary)

Delete this file when the increment finishes (after P6) or when it is abandoned.
It exists only to hand work over between sessions; it is not maintained
documentation. Authoritative documents stay
[the plan](key-consistency-increment-plan.md), `CHANGELOG.md`, and
`docs/phase-status.md`.

## Done

### P1 (2026-09-17) — kernel only

- `soulmate_core.keys.normalize_key` plus `KEY_NORMALIZER_VERSION`
  (`key-normalizer-v1`).
- `TargetKeyAlias`, `TargetKeyAliasMethod`, `TargetKeyAliasStatus` in
  `soulmate_core.domain.models`.
- `KeyAliasMap` / `ResolvedKey`: active-only, chain-following, cycle-safe.
- `aggregate_evidence(evidence, strategy, aliases=())`.
- Tests: `tests/unit/test_key_normalization.py`, `tests/unit/test_key_aliases.py`,
  alias cases in `tests/unit/test_evidence_aggregation.py`.

### P2 (2026-09-17) — persistence

- Migration `0011_key_consistency` creates `target_key_aliases`,
  `target_key_catalog`, and `target_key_embeddings` (`0012` is reserved for
  Phase 13).
- `soulmate_storage_sqlite/key_aliases.py`: `SqliteTargetKeyAliasRepository`
  (`upsert`, `get`, `list_for_profile(profile_id, status=None)`, `remove`) as
  `Repositories.key_aliases`, plus shared `bump_evidence_revision` and
  `prune_unsupported_keys`.
- Port `TargetKeyAliasRepository`; `ModelRebuilder(evidence, models, aliases=None)`.
- `portability.py`: aliases and catalog count as owner data; encrypted exports
  drop `target_key_embeddings`; backups keep everything.
- Tests: `tests/integration/test_key_alias_persistence.py`,
  `tests/integration/test_key_alias_deletion.py`, fixtures in
  `tests/integration/key_alias_support.py` (imported relatively).

### P3 (2026-09-18) — wiring, owner API, review UI

- Kernel: `soulmate_core/keys/proposals.py` with `propose_normalized_aliases`
  (+ `normalized_or_none`). Groups used keys by normalized form; canonical key =
  the target an existing **active** alias in the group already uses, else the
  normalized form when it is itself used, else the first used key. Keys that
  already have an alias row of **any** status are skipped, so rejections stick.
- Kernel: `DecisionPredictor.predict(..., aliases: KeyAliasMap | None)`
  canonicalizes current and historical option features (`_feature_resolver`,
  `_canonical_option`) before matching, pairwise learning, and similarity;
  unknown keys fall back to normalized equality with a model key, and keys that
  collapse together are averaged. `DECISION_ALGORITHM_VERSION` now ends with
  `:canonical-features-v1:key-normalizer-v1`.
- Kernel: `ModelRebuilder.algorithm_version` is
  `personal-model-v1:evidence-weights-v1` without aliases and
  `...:key-aliases-v1` with them; `_fresh_snapshot` compares it, so toggling the
  flag invalidates snapshots. `ModelRebuilder.alias_map(profile_id)` gives the
  predictor its map.
- Daemon: `soulmate_daemon/key_aliases.py` holds `alias_repository`,
  `model_rebuilder` (the factory every rebuild site now uses),
  `register_normalized_aliases`, `KeyAliasService`, `KeyAliasReviewAction`, and
  `KeyAliasError`. `soulmate_daemon/key_alias_api.py` holds the owner-only
  router; `security.py` lists `/v1/key-aliases` under `OWNER_ONLY_RULES`.
- Daemon: `ConversationService`, `DecisionService`, and `ActiveLearningService`
  take a **required** `aliases` keyword (may be `None`) and build one internal
  rebuilder. Aliases are registered after chat extraction review, decision
  resolution learning, and `POST /v1/preferences/corrections`.
- Config: `key_aliases.enabled` (default `true`), documented in
  `config.example.toml`.
- Clients: `packages/sdk-typescript` gained `KeyAlias*` types and `keyAliases`,
  `mergeKeys`, `reviewKeyAlias`, `removeKeyAlias`;
  `apps/desktop/src/components/DuplicateKeysPanel.tsx` and
  `apps/web/src/screens/DuplicateKeys.tsx` render the review list (web only when
  `session.actor === "owner"`, because the API is owner-only).
- Tests: `tests/unit/test_key_alias_proposals.py`,
  `tests/unit/test_key_alias_service.py`, alias cases in
  `tests/unit/test_decision_predictor.py` and `tests/unit/test_access_boundary.py`,
  `tests/integration/test_key_alias_api.py`, plus client tests in
  `DuplicateKeysPanel.test.tsx`, `DuplicateKeys.test.tsx`, `client.test.ts`, and
  `apps/web/src/App.test.tsx`.

### P4 (2026-09-18) — embedding port, local adapter, model manager

- Kernel: `soulmate_core/embeddings/port.py` (`EmbeddingProvider` protocol with
  `model_id`, `dimensions`, `ready`, `embed`, `release`; `NullEmbedding`;
  `EmbeddingUnavailableError`; `EmbeddingVector = tuple[float, ...]`). The kernel
  stays dependency-free: adapters satisfy the protocol structurally, so nothing
  outside imports a runtime.
- Daemon: `soulmate_daemon/model_artifacts.py` holds `ModelFile`,
  `ModelArtifact`, the pinned `BGE_M3_INT8` artifact, `MODEL_ARTIFACTS`,
  `ModelArtifactStore` (paths, `status`, `activate`, `import_file`, `remove`) and
  `ArtifactDownloader` (`authorize`, resumable `download`). Files live in
  `DATA_DIR/models/<model_id>/`, downloads stream into `<name>.part` and are only
  renamed after the pinned SHA-256 matches.
- Daemon: `soulmate_daemon/embeddings.py` holds `artifact_for`, `artifact_store`,
  `LocalOnnxEmbedding` (lazy load, idle release, injectable `loader` and `clock`),
  the default `onnx_session_loader` (imports `numpy`, `onnxruntime`, `tokenizers`
  inside `_OnnxSession`, CLS pooling and L2 normalization as P0 measured), and
  `embedding_provider(settings)`.
- Daemon: `soulmate_daemon/embedding_models.py` holds `EmbeddingModelService`
  (`state`, `start_download`, `wait`, `shutdown`, `cancel`, `import_file`,
  `remove`) plus the audit action constants. It runs at most one download task,
  records `model.embedding_*` audits with no key names, and lives in `AppState`
  as `embedding_models`; `app.py` awaits `shutdown()` on lifespan exit.
- Daemon: `soulmate_daemon/embedding_api.py` is the owner-only router
  (`GET /v1/embedding-model`, `POST /v1/embedding-model/download`, `/cancel`,
  `/import`, `/remove`); `security.py` lists `/v1/embedding-model` under
  `OWNER_ONLY_RULES`.
- Egress: `MODEL_ARTIFACT_CLASSIFICATION = "model_artifact"` in
  `soulmate_llm_providers.policy`. `EgressPolicy.can_send` now reads
  `data_classification`: an artifact endpoint passes in `strict_local` and
  `hybrid` when it uses HTTPS (or loopback) and is refused in `offline`; personal
  data keeps the old rules.
- Config: `embedding.provider` now accepts `"none"` (new default) and `"local"`,
  plus `embedding.model_id` and `embedding.idle_release_seconds` (30–3600);
  `Settings.models_directory` resolves `DATA_DIR/models`. `config.example.toml`
  documents all three.
- Portability: `ARCHIVE_DIRECTORIES` no longer contains `models`, so a 568 MB
  artifact cannot break the 512 MB archive cap. Restore rejects `models/` entries.
- `pyproject.toml` gained a mypy override so `numpy`, `onnxruntime`, and
  `tokenizers` may be missing; they are still **not** in `uv.lock`.
- Tests: `tests/unit/test_model_artifacts.py` (19), `test_embedding_provider.py`
  (11), `test_embedding_model_service.py` (12),
  `tests/integration/test_embedding_model_api.py` (7), plus new cases in
  `test_config.py`, `test_access_boundary.py`, and `test_portability.py`. All use
  fakes: `httpx.MockTransport` for downloads, a fake session loader for the
  adapter, and a synthetic artifact pinned into `MODEL_ARTIFACTS` by monkeypatch.

### P5 (2026-09-18) — labels, key vectors, semantic retrieval and suggestions

- Kernel: `soulmate_core/keys/semantics.py` with `key_embedding_text`
  (dotted segments as words, then `" | "` and the owner label and catalog
  aliases), `key_text_hash`, `cosine_similarity`, `semantic_key_scores`,
  `EmbeddedKey`, `SemanticAliasProposal`, and `propose_semantic_aliases`
  (`SEMANTIC_ALIAS_VERSION = "semantic-alias-v1:key-text-v1"`,
  `DEFAULT_SEMANTIC_ALIAS_THRESHOLD = 0.85`, limit 20). Suggestions are always
  `suggested` with polarity `+1`; the earlier-used key is canonical; a key with an
  alias row of **any** status is skipped; pairs with equal normalized forms are
  left to the normalized rule; each key takes part in at most one suggestion per
  run; target types are never crossed.
- Kernel: `select_known_keys(..., semantic_scores=Mapping[str, float] | None)`
  adds `semantic_weight * similarity` (weight 3.0, floor 0.3, both on
  `KeySelectionPolicy`) to the existing recency (4), word overlap (2), and domain
  (1) signals. Scores are floats now. An empty mapping reproduces step A exactly.
- Kernel: `TargetKeyLabel` + `TargetKeyLabelSource` and `TargetKeyEmbedding`
  (with a derived `dim`) in `domain/models.py`; `TargetKeyCatalogRepository` and
  `TargetKeyEmbeddingRepository` ports (`replace_many`, `list_for_model`,
  `remove_other_models`).
- Storage: `soulmate_storage_sqlite/key_metadata.py` with
  `SqliteTargetKeyCatalogRepository` and `SqliteTargetKeyEmbeddingRepository` as
  `Repositories.key_catalog` and `Repositories.key_embeddings`, over the existing
  `0011` tables (**no migration change**). Vectors are `struct.pack("<{n}f")`, so
  a database file stays portable. An `extracted` label never replaces an `owner`
  label, and `created_at` is preserved across upserts.
- Daemon: `soulmate_daemon/extraction.py` gained `LabelledProposal` with optional
  `label` and comma-separated `aliases` (both required strings in the portable
  wire schema, both may be empty), `KEY_LABEL_RULES` in the extraction prompt, and
  `ReviewedEvidence.labels`. Labels travel only with accepted evidence, so a
  rejected sensitive claim leaves no wording behind; at most 5 aliases, trimmed
  and deduplicated, and an alias equal to the label is dropped.
- Daemon: `soulmate_daemon/key_semantics.py` with `KeySemanticsService`
  (`ready`, `model_id`, `query_scores`, `refresh`), `key_semantics_service`,
  `enqueue_key_embedding_refresh`, `refresh_from_payload`,
  `KEY_EMBEDDING_REFRESH_JOB`, and `KEY_EMBEDDING_INTERVAL_SECONDS`.
  `refresh` embeds only keys whose text hash changed, in batches of 32, then calls
  `remove_other_models` and proposes suggestions. Every
  `EmbeddingUnavailableError` (and a provider returning the wrong number of
  vectors) results in zero writes, a `release()`, and no raised error.
- Daemon: `create_app(..., embeddings=EmbeddingProvider | None)` injects a
  provider for tests; `AppState` gained `key_semantics` (None when
  `embedding.provider == "none"` and no provider was injected). A
  `soulmate-key-embedding-scheduler` task calls `enqueue_key_embedding_refresh`
  every 60 s; the job id is
  `job_key_embeddings_{profile}_{model_id}_{evidence_revision}`, so new evidence
  and a newly installed or changed model each queue exactly one refresh and a
  repeated check is free. Nothing is queued while no model is installed, so
  polling can never trigger a download.
- Daemon: `ConversationService` gained `catalog` and `semantics` keywords (both
  optional, both default `None`); it writes `reviewed.labels` and passes semantic
  scores into `select_known_keys`. `DecisionService` gained `semantics` for the
  natural-decision path.
- Config: `key_aliases.semantic_threshold` (default 0.85, 0.5–1.0), documented in
  `config.example.toml`.
- Clients: `DuplicateKeysPanel` and the web `DuplicateKeys` screen now state why a
  semantic pair was suggested ("similar wording, 92% alike"); nothing else
  changed, because P3 already rendered `suggested` aliases with
  approve/invert/reject.
- Tests: `tests/key_embedding_support.py` (a deterministic concept embedder shared
  by unit and integration tests; `tests/__init__.py` was added so both packages can
  import it and mypy resolves one module name), `tests/unit/test_key_semantics.py`
  (42), `tests/unit/test_key_semantics_service.py` (31),
  `tests/integration/test_key_metadata_persistence.py` (19), label cases in
  `test_extraction.py`, semantic cases in `test_key_selection.py`, three cases in
  `tests/integration/test_key_selection_flow.py` (including the P5 verification),
  and client cases in `DuplicateKeysPanel.test.tsx` and `DuplicateKeys.test.tsx`.

### P0 (2026-09-18) — spike, ADR-016, owner decision

Full detail in the [P0 spike report](key-consistency-p0-spike-report.md); only
what P4/P5 must act on is repeated here.

- Kernel: `soulmate_core/evaluation/key_retrieval.py` plus the packaged dataset
  `evaluation/data/synthetic-key-retrieval-v1.json` (168 keys with Vietnamese
  labels, 84 vi/en messages, 27 antonym pairs). `evaluate_key_retrieval(dataset,
  scorer, *, include_labels, merge_threshold)` takes any
  `Callable[[str, Sequence[str]], Sequence[float]]`, so P5 can score the real
  provider with it. `lexical_scores` is the step-A word-overlap baseline.
- `scripts/key_embedding_spike.py` is the ONNX runner. It is dev-only and imports
  `onnxruntime`/`tokenizers`/`numpy`, which are still **not** in `uv.lock`; ruff
  checks it, mypy does not (`scripts/` is outside `tool.mypy.files`).
- Tests: `tests/evaluation/test_key_retrieval_evaluation.py` (29 cases, marked
  `evaluation`, no model and no network).
- ADR-016 records the embedding port, the owner-initiated pinned download, and the
  default model.

## Not done

- P6: sidecar packaging (`onnxruntime`, `tokenizers`, `numpy` in `uv.lock`), size
  check, smoke test against the real artifact, final documentation. **No client
  UI exists for the model yet**: the API is complete and owner-only, but the
  TypeScript SDK has no `embeddingModel*` methods and no screen shows the
  download button, size, memory warning, or progress. P5 left this to P6 on
  purpose, because it needs the real artifact to be meaningful.
- P6 also owns the **owner-editable key label**: `target_key_catalog` accepts
  `label_source = "owner"` and the repository protects such a label from later
  extraction, but no API or screen writes one yet. Only extraction fills labels
  today, and labels are a quality improvement, not a prerequisite (P0 decision 4).
- Not planned in this increment: `numpy` brute-force scoring. `query_scores` uses
  pure Python dot products, which is fine for the hundreds of keys measured here;
  revisit it only with a real model and a key set in the thousands.

## Decisions that later steps must honor

- From P0 (owner-confirmed 2026-09-18): the default artifact is **`bge-m3` int8**,
  `Xenova/bge-m3` `onnx/model_int8.onnx` (568 MB, MIT), SHA-256
  `a206e10e995aa2a833924bcd725ba5dd6c3425cd34bac3cf2b5677cd2a1c51d6`, with
  `tokenizer.json` SHA-256
  `6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790`. Use CLS
  pooling, L2 normalization, no instruction prefix, 128-token truncation, and key
  text = dotted segments split into words, plus `" | "` and the owner label when
  the catalog has one. Re-verify both hashes when P4 pins them.
- From P0: semantic similarity may never merge keys automatically. Every one of
  the 27 antonym pairs scored higher against its own opposite than the median
  correct message-to-key match scored, under every model measured, so no threshold
  separates them. This is now measured, not cautionary.
- From P0: `multilingual-e5` was rejected. Its int8 exports are AVX-512 VNNI
  (x86-only) and its similarity range is so compressed that every antonym pair
  exceeded 0.85. Do not swap it in as a "smaller alternative" without redoing the
  antonym measurement.

- From P4: the pinned artifact is the single source of truth for what may be
  downloaded. `EgressPolicy` only allows `data_classification="model_artifact"`
  over HTTPS or loopback and never in `offline` mode; do not add a second network
  path for models. Downloads are started by an owner request only — no job, no
  scheduler, and no automatic retry may call `start_download`.
- From P4: `ModelArtifactStore.activate` is the only way a file becomes usable,
  and it deletes anything that fails the SHA-256 check. An interrupted transfer
  keeps its `.part` file on purpose so the next attempt sends a range request.
- From P4: `LocalOnnxEmbedding` raises `EmbeddingUnavailableError` for every
  failure (not installed, runtime missing, inference failed). P5 must catch it
  and fall back to the step-A lexical ranking instead of surfacing an error.
- From P4: the artifact hashes were copied from the P0 spike report, not
  re-verified by downloading 568 MB in this session.
  `test_default_artifact_pins_match_the_recorded_spike_measurements` keeps the
  code and the report in sync; P6 must download the real files once and confirm
  both hashes before release.

- From P5: the embedded text of a key is
  `key_embedding_text(key, label, aliases)` and its `text_hash` decides whether a
  vector is stale. Changing that function invalidates every stored vector, so bump
  `KEY_EMBEDDING_TEXT_VERSION` and let the job recompute instead of migrating rows.
- From P5: embedding work is queued, never inline. Only
  `enqueue_key_embedding_refresh` creates the job, it refuses to queue while no
  model is installed, and the job id carries the evidence revision and the model
  id. Do not call `KeySemanticsService.refresh` from a request handler.
- From P5: `query_scores` and `refresh` must stay silent on failure. Both return
  empty results on `EmbeddingUnavailableError`, which is what keeps step A as the
  fallback; do not turn either into an HTTP error.
- From P5: semantic aliases are written only as `suggested`, and only
  `KeyAliasService` (owner review) may make one active. `propose_semantic_aliases`
  never sets polarity `-1`; the owner's "merge as opposite" action does.

- From P1/P2: evidence is never rewritten; polarity `-1` only for preferences; a
  `semantic` alias needs `similarity`; `upsert` rejects active cycles, keeps the
  first `created_at`, and bumps the evidence revision on every write; pruning
  rules as recorded in P2.
- From P3: only equal normalized forms merge automatically, and only between keys
  that evidence already uses. An alias row of any status blocks re-proposal, so
  "undo" of an automatic merge is **reject**, not delete (the UI does this; the
  API `remove` endpoint deletes and lets the next extraction re-propose).
- Alias writes go through `KeyAliasService`, and every rebuild goes through
  `model_rebuilder(repositories, settings)`. Do not construct `ModelRebuilder`
  directly in new daemon code, or snapshots will flip between grouped and
  ungrouped models.
- Audit metadata for alias changes deliberately omits key names (they can reveal
  personal topics); keep it that way.
- The Tauri bridge rejects paths containing `?`, so alias endpoints take their
  arguments in POST bodies (`/v1/key-aliases/review`, `/v1/key-aliases/remove`)
  instead of query strings or path segments.

## Watch out

- Handled in P4: `ARCHIVE_DIRECTORIES` no longer includes `models`, so artifacts
  stay out of the 512 MB archive cap. An archive written before P4 that contains
  `models/` entries is now rejected on restore; no such archive should exist.
- Handled in P5: catalog and embedding rows now have repositories and domain
  records over the unchanged `0011` columns. `0011` was **not** amended, and `0012`
  still belongs to Phase 13.
- A decision option key that no evidence uses is matched by normalization at
  prediction time but stores no alias until the decision is resolved. If P5 wants
  the alias earlier, add it where options are created, and remember pruning
  deletes aliases whose alias key has no supporting evidence.
- The clients cannot create owner merges yet: `POST /v1/key-aliases` and
  `SoulmateClient.mergeKeys` exist, but no screen calls them (the panel only
  reviews existing aliases). A "merge into another key" control in the preference
  drawer is the natural next UI step.
- Tests that construct daemon services must pass `aliases=repositories.key_aliases`
  (the keyword is required); passing `None` produces snapshots with a different
  algorithm version, which the daemon then rebuilds.
- P5 added `tests/__init__.py`. Without it, mypy sees
  `tests/key_embedding_support.py` under two module names and stops checking.
- No real embedding model has run yet, in any step. Every P5 number comes from the
  P0 spike or from `FakeConceptEmbedding`, which is deliberately built so opposite
  concepts stay close; treat the semantic weight (3.0) and floor (0.3) in
  `KeySelectionPolicy` as unmeasured against real vectors, and re-run the P0
  harness in P6 before defending them.
- The real `_OnnxSession` in `soulmate_daemon/embeddings.py` has no automated
  test: `numpy`, `onnxruntime`, and `tokenizers` are not installed, so mypy skips
  them through a `pyproject.toml` override and every test injects a fake loader.
  P6 owns the first real execution; treat its pooling and padding code as
  unverified until then.
- `EmbeddingModelService` keeps download progress in memory only. A daemon
  restart during a download loses the progress number but not the bytes: the
  `.part` file resumes. There is no durable job for it on purpose — a download
  must never restart without the owner.
- P0 measured macOS arm64 only. Windows, Linux, and x64 are unverified and moved
  into P6; the step-A fallback on load failure is what makes that acceptable.
- Peak RSS with `bge-m3` int8 loaded was about 1.8 GB (whole process, mapped
  weights included). P4 loads lazily and releases after
  `embedding.idle_release_seconds`, and `GET /v1/embedding-model` returns
  `peak_memory_bytes` and `download_bytes`; the client dialog still has to show
  them before the owner presses download.
- P5 can ship semantic scoring before the label catalog UI: key text alone already
  reaches 97.7% Vietnamese recall inside the 50-key budget; labels take it to 100%
  and mainly improve rank 1.
- Re-run the harness whenever the scoring mix in `select_known_keys` changes;
  `lexical_scores` is committed precisely so the before/after gap stays visible.

## Verification commands

```bash
uv run --locked ruff check . && uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
pnpm check
```

Result for P5: `pnpm check` passed locally (698 Python tests, 50 SDK, 20 desktop,
28 web, 27 mobile client tests, 7 Rust tests), with `ruff`, `ruff format`, and
strict `mypy` clean. P4 passed the same gate with 582 Python tests.
`pnpm check:all` (lockfile check, pre-commit, builds) was not run in P3, P4, or
P5, and `pytest-cov` is still not installed, so the increment has no coverage
number.
