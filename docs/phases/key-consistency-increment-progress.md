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

- Migration `0011_key_consistency` (file `0011_key_consistency.py`) creates all
  three tables of the plan now, because `0012` is reserved for Phase 13:
  - `target_key_aliases`, PK `(profile_id, target_type, alias_key)`, checks for
    polarity, inversion only on preferences, method, status, similarity range,
    and `alias_key <> canonical_key`;
  - `target_key_catalog`, PK `(profile_id, target_type, key)`, columns `label`
    (nullable), `aliases_json`, `label_source` (`extracted` | `owner`);
  - `target_key_embeddings`, PK `(profile_id, target_type, key, model_id)`,
    columns `text_hash`, `dim > 0`, `vector` (BLOB).
- `soulmate_storage_sqlite/key_aliases.py`: `SqliteTargetKeyAliasRepository`
  (`upsert`, `get`, `list_for_profile(profile_id, status=None)`, `remove`),
  exposed as `Repositories.key_aliases`; shared `bump_evidence_revision` (the three
  duplicated inline bumps in `repositories.py` now use it) and
  `prune_unsupported_keys`.
- Port `TargetKeyAliasRepository` in `soulmate_core.domain.ports`.
- `ModelRebuilder(evidence, models, aliases=None)` applies only active aliases in
  `rebuild`, `current`, and `current_model`.
- `portability.py`: aliases and catalog count as owner data for the
  fresh-installation check; `encrypted_export` archives drop
  `target_key_embeddings`; `local_backup` and `remote_backup` keep everything.
- Tests: `tests/integration/test_key_alias_persistence.py`,
  `tests/integration/test_key_alias_deletion.py`, shared fixtures in
  `tests/integration/key_alias_support.py` (imported relatively, because mypy maps
  `tests/` without an `__init__.py`), an alias assertion in the connector removal
  test, and head-revision updates in older tests.

## Not done

- P0: ADR-016 and the embedding model spike (does not block P3).
- P3: automatic normalized aliases after extraction review, predictor and pairwise
  key mapping, owner alias API, desktop/web duplicate-key review, the
  `key_aliases.enabled` flag, and **daemon wiring of aliases into every
  `ModelRebuilder`** (see below).
- P4 to P6: embedding port, ONNX adapter and model manager, catalog and embedding
  repositories and domain records, semantic suggestions, sidecar packaging, final
  documentation.

## Decisions that later steps must honor

- From P1: `TargetKeyAlias` has no `id`; polarity `-1` only for preferences; a
  `semantic` alias needs `similarity`; aliases apply at aggregation time only and
  evidence is never rewritten.
- `upsert` builds a `KeyAliasMap` from the other active aliases plus the new one,
  so a direct or transitive active cycle raises `ValueError("... cycle ...")`
  before anything is written. Suggested/rejected rows are not cycle-checked;
  activating one later is. The P3 API should map this `ValueError` to a 409/422.
- `upsert` keeps the first `created_at` and returns the stored alias. Every
  `upsert` and successful `remove` bumps the evidence revision, even if the row is
  unchanged.
- Pruning rule (runs inside the same transaction as evidence deletion): a key is
  supported when evidence uses it, or when an active alias whose alias key is
  supported points to it (followed transitively). Active aliases survive when
  their alias key is supported; suggested/rejected aliases need both keys
  supported; catalog and embedding rows survive only for supported keys. This
  applies to `owner` aliases too, so a deleted topic does not leave key names.
- Catalog and embedding rows have no repository or domain record yet; P5 should
  add them against the existing columns rather than a new migration. If a column
  must change, amend `0011` only if no user database has it yet — otherwise stop
  and ask the owner, because `0012` belongs to Phase 13.

## Watch out

- The daemon constructs `ModelRebuilder(repositories.evidence,
  repositories.personal_models)` in about 13 places (`app.py`, `decisions.py`,
  `conversation.py`, `active_learning.py`, `data_api.py`, `connector_api.py`,
  `cli.py`, `portability.py`). None pass aliases yet; that is harmless only while
  nothing creates aliases. P3 must wire all of them at once (a small factory is
  suggested), otherwise snapshots flip between grouped and ungrouped models.
- `ARCHIVE_DIRECTORIES` in `portability.py` includes `models`, and archives are
  capped at 512 MB. P4 stores model artifacts under `DATA_DIR/models`
  (0.5–1.2 GB), which would make every backup fail; exclude or relocate them in P4.
- `normalize_key` still has no production caller; the first arrives in P3.
- The predictor and pairwise learner must reuse `KeyAliasMap`.
- Raw-SQL test inserts with `datetime` parameters emit Python 3.12
  `DeprecationWarning`s; existing tests do the same.
- `pytest-cov` is not installed, so no coverage number exists for P1 or P2;
  `pnpm check:all` was not run for P2 (no TypeScript change).

## Verification commands

```bash
uv run --locked ruff check . && uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
uv run --locked pre-commit run --all-files
```

Result for P2: all passed locally (430 Python tests).
