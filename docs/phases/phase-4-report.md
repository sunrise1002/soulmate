# Phase 4 report — Decision MVP

## Authorization and scope

Phase 4 was explicitly authorized on 2026-09-11. Work is limited to specification
tasks P4-01 through P4-10. Evaluation learning, confidence calibration, desktop or
mobile clients, MCP, outcome intelligence, Advise Me, and later integrations are
not authorized.

## Implementation plan

1. Add infrastructure-independent decision records, persistence ports, and a
   packaged SQLite migration for decisions, options, predictions, and resolutions.
2. Add validated explicit decision input with optional provider-assisted natural
   option feature extraction.
3. Implement deterministic preference matching, utility scoring, softmax ranking,
   confidence estimation, and similar resolved-decision retrieval in the kernel.
4. Persist every prediction with its algorithm and Personal Model snapshot version,
   and expose evidence-backed Predict Me explanations.
5. Convert an actual resolution into provenance-bearing high-value Evidence,
   rebuild the model, and verify that subsequent predictions use it after restart.
6. Run all local quality gates and record actual limitations without advancing
   into Phase 5.

## Delivered work

| Task | Result |
| --- | --- |
| P4-01 Decision schema | Validated `DecisionEvent`, `DecisionOption`, `DecisionPrediction`, and `DecisionResolution` records plus SQLite repositories and migration `0004_phase_4` |
| P4-02 Decision detection | Explicit `POST /v1/decisions` API; chat auto-detection remains intentionally deferred |
| P4-03 Feature extraction | Caller-supplied normalized features or strict Pydantic-validated structured extraction from natural option descriptions |
| P4-04 Preference matching | Deterministic exact/canonical feature-key matching with domain-context preference selection |
| P4-05 Utility scoring | Provider-independent weighted V1 utility with a bounded similar-choice prior |
| P4-06 Probability ranking | Stable softmax probabilities with deterministic tie ordering |
| P4-07 Confidence | Initial estimator combining probability margin, model coverage/quality, consistency, extraction confidence, and historical similarity |
| P4-08 Similar decisions | Deterministic domain, lexical-question, structured-feature, and chosen-option vector similarity over resolved history |
| P4-09 Explanation | Predict Me response includes predicted choice, ranking, confidence, important and uncertain factors, supporting Evidence, similar decision IDs, and snapshot/algorithm versions |
| P4-10 Resolution | `POST /v1/decisions/{id}/resolve` persists the chosen option and RawEvent, creates relative `actual_choice` Evidence, and rebuilds the model |

The decision scorer is entirely inside `soulmate-core` and uses only the standard
library. Provider calls occur only when a submitted option omits structured
features, pass through the existing egress policy, receive only the current
decision payload, and cannot write decision or model state directly. Structured
options and all prediction steps work without an LLM.

Every prediction references an existing immutable `UserModelSnapshot` through a
database foreign key. The service rebuilds a missing or stale snapshot before
scoring. Predict Me is explicit in the response and no advice/recommendation mode
is implemented.

## Verification

Local verification on macOS arm64 with Python 3.12.4:

| Check | Result |
| --- | --- |
| Locked Ruff lint | Passed |
| Locked Ruff formatting check | Passed |
| Strict mypy | Passed; 50 source files |
| Unit and integration tests | 83 passed (56 unit, 27 integration) |
| Phase 1/2/3 to Phase 4 migration | Passed with prior records preserved |
| Decision/restart behavior | Passed with prediction snapshot, resolution Evidence, rebuilt preferences, and similar history preserved |
| Natural feature extraction | Passed offline with a deterministic fake provider and strict structured validation |
| Core decision algorithms | Passed without a provider, network, database, or framework |

Local results do not imply remote GitHub Actions passed. Remote CI has not yet been
observed for this phase.

## Known issues and limitations

- V1 feature values use a documented normalized `[-1, 1]` contract. Provider
  extraction is validated structurally but not evaluated against a real model.
- Semantic similarity is a deterministic local lexical/structured approximation;
  embeddings and a vector backend remain deferred.
- Utility weights, confidence, and the similar-choice prior are initial heuristics.
  Phase 5 must evaluate and calibrate them before accuracy claims are made.
- Resolution learning creates relative feature Evidence from the chosen option
  against the mean alternatives. Features with no option differentiation create
  no preference Evidence because the choice supplies no directional signal.
- Feature extraction and model rebuild remain synchronous. Chat decision
  auto-detection, decision history APIs, outcomes/regret, and Advise Me are not
  part of this phase.
- The two upstream Starlette test-client compatibility warnings remain unchanged.
- Remote CI and real configured provider availability remain unverified.

## Phase 5 handoff

Phase 4 exit criteria pass locally. The complete talk/learn/submit/predict/resolve/
learn loop now exists, predictions are reproducible against stored snapshots, and
resolved choices influence later predictions across restart.

Phase 5 may add preference-learning evaluation only after explicit authorization.
It should create synthetic evaluation datasets and reproducible metrics, compare
specified baselines, evaluate pairwise/contextual learning, calibrate confidence,
and version material algorithm changes. Do not begin client, MCP, active-learning,
outcome, or delegated-agent phases as part of that work.
