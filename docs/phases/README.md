# Phase reports

Each phase has a durable report containing its plan, delivered work, verification,
known issues, and handoff state. `docs/phase-status.md` is the compact index and
authorization gate; it does not replace these reports.

Before starting a phase, contributors and AI agents must:

1. Read the root technical specification and current authorization in
   `docs/phase-status.md`.
2. Read the complete report for the immediately preceding phase, including open
   issues and handoff notes.
3. Inspect the repository rather than assuming the report is current.
4. Add the current phase plan to its report before implementation.
5. Record actual changes, check results, limitations, and unresolved issues before
   reporting completion.

Never mark remote CI as passed based on local checks. Never start the next phase
without explicit authorization.

Available reports:

- [Phase 0](phase-0-report.md)
- [Phase 1](phase-1-report.md)
- [Phase 2](phase-2-report.md)
- [Phase 3](phase-3-report.md)
- [Phase 4](phase-4-report.md)
- [Phase 5](phase-5-report.md)
- [Phase 6](phase-6-report.md)
