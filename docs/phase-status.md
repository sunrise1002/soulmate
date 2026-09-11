# Phase status

This is the phase index and authorization gate. Read the linked full report for
the previous phase before planning or implementing the current phase.

## Authorized scope

Phase 1 — Local Daemon and Persistence is complete locally. Phase 2 is not
authorized. Stop at the Phase 1 boundary until the user explicitly requests the
next phase.

## Reports

| Phase | State | Report | Important open issue |
| --- | --- | --- | --- |
| Phase 0 | Complete locally | [Phase 0 report](phases/phase-0-report.md) | Remote CI unverified |
| Phase 1 | Complete locally | [Phase 1 report](phases/phase-1-report.md) | Remote CI unverified; deferred diagnostics documented |

## Phase 1 exit criteria

Passed locally. `decision-twin serve` provides a healthy loopback service,
persistent SQLite storage, successful restart, and automatic migrations. The full
report records implementation details, checks, limitations, and Phase 2 handoff.

## Next action

Wait for explicit Phase 2 authorization. Before planning it, read the complete
[Phase 1 report](phases/phase-1-report.md) and inspect current repository state.

## Repository governance

Phase-neutral contribution governance was standardized on 2026-09-11. Local
quality gates, Git metadata policy, CI enforcement, templates, security guidance,
and maintainer repository settings are documented under the
[contributor guide](contributor-guide/README.md). This does not alter the authorized
phase boundary above. Remote CI and GitHub ruleset activation remain unverified.
