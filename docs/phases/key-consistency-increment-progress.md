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

- P5: extraction `label`/`aliases` fields, catalog and embedding repositories and
  domain records, backfill job, semantic scoring, **semantic alias suggestions**
  (the review UI already renders `suggested` aliases and sends
  approve/invert/reject, so P5 only has to create the rows). Nothing calls
  `embedding_provider(settings)` yet — P4 only built it.
- P6: sidecar packaging (`onnxruntime`, `tokenizers`, `numpy` in `uv.lock`), size
  check, smoke test against the real artifact, final documentation. **No client
  UI exists for the model yet**: the API is complete and owner-only, but the
  TypeScript SDK has no `embeddingModel*` methods and no screen shows the
  download button, size, memory warning, or progress. That UI is unassigned in
  the plan; P5 or P6 should take it.

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
- Catalog and embedding rows still have no repository or domain record. P5 should
  use the existing `0011` columns; amend `0011` only if no user database has it
  yet — otherwise stop and ask the owner, because `0012` belongs to Phase 13.
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
- `pytest-cov` is not installed, so P0 to P4 still have no coverage number.
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

Result for P4: `pnpm check` passed locally (582 Python tests, 50 SDK, 18 desktop,
27 web, 27 mobile client tests, 7 Rust tests), with `ruff`, `ruff format`, and
strict `mypy` clean. `pnpm check:all` (lockfile check, pre-commit, builds) was
not run in P3 or P4.
