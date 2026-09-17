# Key consistency increment — working notes (temporary)

Delete this file when the increment finishes (after P6) or when it is abandoned.
It exists only to hand P1 over to the next working session; it is not maintained
documentation. Authoritative documents stay
[the plan](key-consistency-increment-plan.md), `CHANGELOG.md`, and
`docs/phase-status.md`.

## Done (P1, 2026-09-17)

- `soulmate_core.keys.normalize_key` plus `KEY_NORMALIZER_VERSION`
  (`key-normalizer-v1`).
- `TargetKeyAlias`, `TargetKeyAliasMethod`, `TargetKeyAliasStatus` in
  `soulmate_core.domain.models`, exported from `soulmate_core.domain`.
- `soulmate_core.keys.KeyAliasMap` / `ResolvedKey`: active-only, chain-following,
  cycle-safe, scoped by `(profile_id, target_type, alias_key)`.
- `aggregate_evidence(evidence, strategy, aliases=())` maps keys and inverts
  opposite preference values without rewriting stored evidence.
- Tests: `tests/unit/test_key_normalization.py`, `tests/unit/test_key_aliases.py`,
  and the alias cases appended to `tests/unit/test_evidence_aggregation.py`.

## Not done

- P0: ADR-016 and the embedding model spike (does not block P2 or P3).
- P2: migration `0011`, alias repository, evidence-revision bump on alias change,
  backup/export/restore coverage.
- P3: automatic normalized aliases after extraction review, predictor and pairwise
  key mapping, owner alias API, desktop/web duplicate-key review.
- P4 to P6: embedding port, ONNX adapter and model manager, key labels and
  semantic suggestions, sidecar packaging, final documentation.

## Decisions taken in P1 that later steps must honor

- `TargetKeyAlias` has no `id` field; its natural key is
  `(profile_id, target_type, alias_key)`. Give migration `0011` that unique
  constraint, or add an `id` field deliberately.
- Polarity `-1` is rejected for fact, goal, and constraint aliases, and a
  `semantic` alias must carry a `similarity`. The repository layer should not
  weaken these; persisted rows failing them will raise on load.
- `normalize_key` keeps a final segment made only of filler tokens
  (`notification.sound.level` stays), and converts `/` to `_` rather than to a dot.
  Both choices avoid merging distinct keys; revisit only with new evidence.
- `KeyAliasMap` raises `ValueError` on a cycle or on two active targets for one
  key. That fails a rebuild, so P2/P3 must reject such rows at write time
  (transitively, not only direct self-references).
- Aliases are applied at aggregation time only. Evidence rows keep their original
  key forever; never migrate or rewrite them.

## Watch out

- `ModelRebuilder` still calls `aggregate_evidence` without aliases. Wiring it is
  P2/P3 work, and every alias change must advance the profile evidence revision,
  otherwise `ModelRebuilder.current()` keeps serving a stale snapshot.
- `normalize_key` has no production caller yet; the first one arrives in P3.
- The predictor and the pairwise learner must reuse `KeyAliasMap` instead of
  matching keys themselves, or the model and the predictor will disagree.
- The `key_aliases.enabled` and `embedding.provider` flags from the plan's
  rollback section are not implemented yet.
- `pytest-cov` is not installed, so no coverage number exists for P1.

## Verification commands

```bash
uv run --locked ruff check . && uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
uv run --locked pre-commit run --all-files
```
