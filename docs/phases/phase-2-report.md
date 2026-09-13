# Phase 2 report — Evidence and Personal Model Foundation

## Authorization and scope

Phase 2 was explicitly authorized on 2026-09-11. Work is limited to specification
tasks P2-01 through P2-07; conversation, LLM extraction, decision prediction, and
later phases are not authorized.

## Implementation plan

1. Extend the infrastructure-independent kernel with validated evidence, derived
   state, snapshots, and only the repository ports required by Phase 2.
2. Implement deterministic, versioned aggregation with contextual grouping and
   provenance preservation, without an LLM or numerical dependency.
3. Add a new SQLite migration and repositories for evidence revisions, derived
   state, atomic replacement, and immutable snapshots.
4. Compose model rebuilds, preference corrections, summaries, and explainability
   in the local daemon and CLI.
5. Test contradictions, corrections, evidence removal, deterministic aggregation,
   snapshot versions, migration from Phase 1, restart persistence, and API input
   validation.
6. Run all local quality gates and package builds, then record actual results and
   limitations.

## Delivered work

| Task | Result |
| --- | --- |
| P2-01 RawEvent | Phase 1 envelope retained as the immutable provenance input for evidence |
| P2-02 Evidence | Validated target, value, strength, confidence, context, source type, source event, extractor version, and timestamp |
| P2-03 Derived State | Contextual `Fact`, `Preference`, `Goal`, and `Constraint` records with confidence and supporting evidence IDs |
| P2-04 Aggregation | Standard-library weighted aggregation grouped by exact canonical context; contradictions remain in evidence and reduce confidence |
| P2-05 Snapshot | Immutable SQLite snapshots record profile version, algorithm version, evidence revision, full model content, and creation time |
| P2-06 Rebuild | `soulmate rebuild-model` deterministically derives and atomically replaces current state before creating a snapshot |
| P2-07 Explainability | Local endpoints expose evidence details and all supporting preference evidence |

The default source reliability configuration is named `evidence-weights-v1`, and
the complete algorithm identifier is `personal-model-v1:evidence-weights-v1`.
Derived timestamps come from their evidence rather than wall-clock rebuild time,
so fixed evidence yields fixed aggregation content. Rebuild time and monotonically
increasing snapshot version remain snapshot metadata.

Preference corrections use `POST /v1/preferences/corrections`. Each correction
creates a RawEvent and high-reliability `user_correction` Evidence, then rebuilds
the profile model. Current summaries and preferences are available through
`GET /v1/model/summary` and `GET /v1/preferences`; evidence is available through
`GET /v1/evidence/{id}` and `GET /v1/preferences/{key}/evidence`.

## Verification

Local verification on macOS arm64 with Python 3.12.14:

| Check | Result |
| --- | --- |
| Locked Ruff lint | Passed |
| Locked Ruff formatting check | Passed |
| Strict mypy | Passed; 34 source files |
| Unit and integration tests | 67 passed (48 unit, 19 integration) |
| Phase 1 to Phase 2 migration | Passed with existing profile preservation |
| Rebuild/restart behavior | Passed, including evidence removal, snapshot increments, and installed CLI process execution |
| Full pre-commit suite | Passed |
| Core, daemon, and SQLite source/wheel builds | Passed |
| Packaged migration inspection | Passed; migrations `0001_phase_1` and `0002_phase_2` are present in the SQLite wheel |
| Frozen pnpm installation | Passed |

Local results do not imply remote GitHub Actions passed. Remote CI has not yet been
observed for this phase.

## Known issues and limitations

- Conversation ingestion and automatic evidence extraction remain Phase 3; Phase
  2 accepts correction evidence through the API and repository-level evidence from
  future validated extractors.
- Source reliability values are an explicit versioned V1 heuristic, not calibrated
  scientific constants. Phase 5 owns preference learning and evaluation.
- Context matching is exact canonical JSON in this phase. Hierarchical or similar
  context lookup belongs to later learning and context-compilation work.
- Rebuilds are synchronous and local. The durable worker is not yet connected to a
  model rebuild handler because Phase 2 data volumes do not require it.
- Evidence deletion is available through the kernel repository for privacy and
  rebuild tests, but no public deletion endpoint is introduced ahead of the source
  deletion workflow in Phase 10.
- The two upstream Starlette test-client compatibility warnings remain unchanged.
- Remote CI verification remains unconfirmed.

## Phase 3 handoff

Phase 2 exit criteria pass locally. The kernel can accept validated evidence and
rebuild a complete versioned Personal Model without infrastructure or an LLM. The
SQLite adapter preserves provenance and prior snapshots, while current derived
state is replaceable and reproducible from evidence.

Phase 3 may add conversation storage, a provider abstraction, structured evidence
proposal validation, extraction jobs, and conversational correction flows only
after explicit authorization. Providers and extractors must emit validated
Evidence and must never mutate derived state directly. Do not introduce decision
prediction, embeddings, or later-phase integrations as part of Phase 3 planning.
