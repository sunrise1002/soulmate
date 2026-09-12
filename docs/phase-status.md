# Phase status

This is the phase index and authorization gate. Read the linked full report for
the previous phase before planning or implementing the current phase.

## Authorized scope

Phase 8 — Active Learning & Outcome Intelligence is complete locally. Phase 9 is
not authorized. Stop at the Phase 8 boundary until the user explicitly requests
the next phase.

## Reports

| Phase | State | Report | Important open issue |
| --- | --- | --- | --- |
| Phase 0 | Complete locally | [Phase 0 report](phases/phase-0-report.md) | Remote CI unverified |
| Phase 1 | Complete locally | [Phase 1 report](phases/phase-1-report.md) | Remote CI unverified; deferred diagnostics documented |
| Phase 2 | Complete locally | [Phase 2 report](phases/phase-2-report.md) | Remote CI unverified; extraction intentionally deferred |
| Phase 3 | Complete locally | [Phase 3 report](phases/phase-3-report.md) | Remote CI and real provider availability unverified |
| Phase 4 | Complete locally | [Phase 4 report](phases/phase-4-report.md) | Remote CI, real provider extraction, and calibration unverified |
| Phase 5 | Complete locally | [Phase 5 report](phases/phase-5-report.md) | Remote CI and external-dataset calibration unverified |
| Phase 6 | Complete locally | [Phase 6 report](phases/phase-6-report.md) | Remote cross-platform installers, signing, and real providers unverified |
| Phase 7 | Complete locally | [Phase 7 report](phases/phase-7-report.md) | Remote CI, native mobile builds, and browser trust of the self-signed certificate unverified |
| Phase 8 | Complete locally | [Phase 8 report](phases/phase-8-report.md) | Remote CI, richer question generation, native mobile builds, and external outcome calibration unverified |

## Phase 8 exit criteria

Passed locally on macOS arm64. Soulmate ranks uncertain preferences, asks
context-preserving trade-off questions, learns from answers, records decision
outcomes and regret, and can recommend a different option from its behavioral
prediction without changing Predict Me semantics. Phase 8 records and source data
survive restart; the owner can delete an outcome and its derived advice.

## Next action

Wait for explicit Phase 9 authorization. Before planning it, read the complete
[Phase 8 report](phases/phase-8-report.md) and inspect current repository state.

## Repository governance

Phase-neutral contribution governance was standardized on 2026-09-11. Local
quality gates, Git metadata policy, CI enforcement, templates, security guidance,
and maintainer repository settings are documented under the
[contributor guide](contributor-guide/README.md). This does not alter the authorized
phase boundary above. Remote CI and GitHub ruleset activation remain unverified.
