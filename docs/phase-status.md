# Phase status

This is the phase index and authorization gate. Read the linked full report for
the previous phase before planning or implementing the current phase.

## Authorized scope

Phase 12 — Delegated Decision Agent is complete locally. Phase 13 — Decision I/O
and trusted provenance has a recorded plan, but implementation has not started and
requires a separate explicit owner instruction. No Phase 14 or later work is
defined or authorized for implementation.

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
| Phase 9 | Complete locally | [Phase 9 report](phases/phase-9-report.md) | Remote CI, remote MCP transport, cross-platform packaged MCP smoke tests, and native mobile builds unverified |
| Phase 10 | Complete locally | [Phase 10 report](phases/phase-10-report.md) | Remote CI, cross-platform restore, large archives, and native mobile builds unverified |
| Phase 11 | Complete locally | [Phase 11 report](phases/phase-11-report.md) | Remote CI, plugin sandboxing/signing, scheduled sync, real service connectors, and cross-platform packaged discovery unverified |
| Phase 12 | Complete locally | [Phase 12 report](phases/phase-12-report.md) | Remote CI, broad real-world confidence calibration, external action verification, notifications, and cross-platform packaged behavior unverified |
| Phase 13 | Planned; not started | [Phase 13 plan](phases/phase-13-plan.md) | Implementation requires explicit owner instruction; ADR and contracts are not yet accepted |

## Phase 12 exit criteria

Passed locally on macOS arm64. An approved external identity can request a fresh
prediction-bound action, receive automatic authority only inside exact owner-set
low/medium impact and confidence limits, wait for owner confirmation otherwise,
and complete one durable authorization without receiving raw Personal Model data.

## Next action

When the owner explicitly authorizes implementation, execute only the recorded
[Phase 13 plan](phases/phase-13-plan.md), beginning with ADR-014 and the contract
freeze. Follow specification section 74, validate the complete phase, update its
report and this status, then stop. Do not infer authorization for agent hooks,
Git observation, shadow prediction, later autonomous execution, notifications,
policy expansion, or safety-critical behavior.

## Repository governance

Phase-neutral contribution governance was standardized on 2026-09-11. Local
quality gates, Git metadata policy, CI enforcement, templates, security guidance,
and maintainer repository settings are documented under the
[contributor guide](contributor-guide/README.md). This does not alter the authorized
phase boundary above. Remote CI and GitHub ruleset activation remain unverified.

## Repository maintenance

On 2026-09-14, remaining legacy product identifiers were standardized on
Soulmate across runtime defaults, packaging, tests, configuration, and
documentation. `pnpm check:all` passed locally on macOS arm64; remote CI remains
unverified. This maintenance does not define or authorize a later product phase.
