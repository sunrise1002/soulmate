# Phase 5 report — Preference Learning & Evaluation

## Authorization and scope

Phase 5 was explicitly authorized on 2026-09-12. Work is limited to specification
tasks P5-01 through P5-07. Desktop and mobile clients, MCP, active learning,
outcomes/regret, Advise Me, embeddings, and later integrations are not authorized.

## Implementation plan

1. Add a versioned synthetic decision fixture and a strict offline loader.
2. Implement reproducible classification, scoring-rule, and calibration metrics.
3. Compare random, frozen LLM-only, memory-only, Personal Model, and sequential
   Decision Model baselines without network calls.
4. Add deterministic online Bradley-Terry/logistic learning over resolved choices.
5. Combine global, domain-specific, and contextual Personal Model and learned
   weights during Predict Me scoring.
6. Version the complete prediction algorithm and expose an offline evaluation CLI.
7. Run every local quality gate and document measured results and limitations.

## Delivered work

| Task | Result |
| --- | --- |
| P5-01 Evaluation dataset | Packaged `synthetic-owner-v1` fixture with 12 chronological two- and three-option choices across travel, career, and software contexts |
| P5-02 Metrics | Top-1 accuracy, Top-2 accuracy, mean log loss, multiclass Brier score, top-label expected calibration error, and populated confidence bins |
| P5-03 Baselines | Reproducible random, frozen LLM-only, memory-only, Personal Model, and sequential Decision Model evaluation; no provider calls |
| P5-04 Pairwise learning | Online regularized Bradley-Terry/logistic SGD over chosen-versus-alternative feature differences, with bounded deterministic weights |
| P5-05 Contextual preferences | Explicit relative `0.2/0.3/0.5` global/domain/context scope weights for evidence-derived and pairwise preferences |
| P5-06 Confidence calibration | Evaluation reports observed accuracy and mean confidence per populated bin plus aggregate expected calibration error |
| P5-07 Algorithm versioning | New predictions persist `decision-predictor-v2:contextual-v1:bradley-terry-online-v1:confidence-v2` in the existing version column |

`decision-twin evaluate` defaults to the packaged dataset, accepts an optional
validated `--dataset` JSON path, emits stable machine-readable JSON, and accesses
neither owner persistence nor the network. Evaluation is chronological: each
decision is predicted before its choice updates the online learner.

The runtime reconstructs pairwise weights deterministically from persisted
resolved history. This keeps the kernel independent of storage and makes learned
behavior restart-safe without a new persistent schema. Existing immutable
prediction rows retain their original algorithm version.

## Verification

Local verification on macOS arm64 with Python 3.12.4:

| Check | Result |
| --- | --- |
| Locked Ruff lint | Passed |
| Locked Ruff formatting check | Passed |
| Strict mypy | Passed; 56 source files |
| Unit, integration, and evaluation tests | Passed; 90 total (60 unit, 27 integration, 3 evaluation) |
| Packaged offline evaluation command | Passed; 12 decisions and five baselines |
| Python package builds | Passed; packaged synthetic dataset verified in the core wheel |
| Frozen pnpm install and repository hooks | Passed |

On `synthetic-owner-v1`, the sequential Decision Model reached `0.666667` Top-1
accuracy and `0.627092` mean log loss, compared with `0.583333` and `0.657339` for
the fixed Personal Model. These values validate the benchmark loop, not general
prediction quality. Local results do not imply remote GitHub Actions passed.

## Known issues and limitations

- The 12-decision synthetic dataset is deliberately small and is not evidence of
  real-owner accuracy or population-level calibration.
- LLM-only results are frozen synthetic probabilities so evaluation remains
  offline and reproducible; real-provider quality and availability are unverified.
- Expected calibration error is descriptive. No post-hoc calibration curve is
  fitted from this small dataset, and external datasets are still needed before
  interpreting an `80%` confidence value as empirically calibrated.
- Pairwise weights are reconstructed in memory from all resolved decisions for
  each prediction. This is deterministic and restart-safe but scales linearly with
  decision history until a measured need justifies persisted learned state.
- Context matching is exact for non-domain keys; hierarchical, semantic, and
  similarity-based context generalization remain deferred.
- The two upstream Starlette test-client compatibility warnings remain unchanged.
- Remote CI has not yet been observed for this phase.

## Phase 6 handoff

Phase 5 exit criteria pass locally: every material decision-learning change can be
compared through one reproducible command, resolved history trains contextual
pairwise weights, and predictions identify the full learning algorithm used.

Phase 6 may begin only after explicit authorization. It may build the desktop
product around the existing daemon contract, but must not silently broaden into
mobile, pairing, MCP, active-learning, outcome, or delegated-agent work.
