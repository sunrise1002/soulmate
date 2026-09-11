# Phase status

This is the phase index and authorization gate. Read the linked full report for
the previous phase before planning or implementing the current phase.

## Authorized scope

Phase 4 — Decision MVP is complete locally. Phase 5 is not authorized. Stop at the
Phase 4 boundary until the user explicitly requests the next phase.

## Reports

| Phase | State | Report | Important open issue |
| --- | --- | --- | --- |
| Phase 0 | Complete locally | [Phase 0 report](phases/phase-0-report.md) | Remote CI unverified |
| Phase 1 | Complete locally | [Phase 1 report](phases/phase-1-report.md) | Remote CI unverified; deferred diagnostics documented |
| Phase 2 | Complete locally | [Phase 2 report](phases/phase-2-report.md) | Remote CI unverified; extraction intentionally deferred |
| Phase 3 | Complete locally | [Phase 3 report](phases/phase-3-report.md) | Remote CI and real provider availability unverified |
| Phase 4 | Complete locally | [Phase 4 report](phases/phase-4-report.md) | Remote CI, real provider extraction, and calibration unverified |

## Phase 4 exit criteria

Passed locally. An owner can submit structured or natural-language A/B/C options,
receive a persisted Predict Me ranking with probabilities, confidence, factors,
supporting evidence, similar decisions, and the exact model snapshot version,
resolve the actual choice into high-value Evidence, restart, and observe the next
prediction use the updated model. The full report records limitations and the
Phase 5 handoff.

## Next action

Wait for explicit Phase 5 authorization. Before planning it, read the complete
[Phase 4 report](phases/phase-4-report.md) and inspect current repository state.

## Repository governance

Phase-neutral contribution governance was standardized on 2026-09-11. Local
quality gates, Git metadata policy, CI enforcement, templates, security guidance,
and maintainer repository settings are documented under the
[contributor guide](contributor-guide/README.md). This does not alter the authorized
phase boundary above. Remote CI and GitHub ruleset activation remain unverified.
