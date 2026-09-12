# Agent instructions

## Read first

Read the root technical specification, `docs/phase-status.md`, and
`docs/contributor-guide/conventions.md` before changing the project. Before
planning a phase, follow the phase-status link to the complete report for the
previous phase and read its delivered work, verification results, limitations,
and handoff notes. Significant architecture decisions live in
`docs/architecture/decisions/`.

## Language

Users and AI agents may communicate in any language. Reply in the user's chosen
language unless asked otherwise. All code must be in English: identifiers,
comments, docstrings, test names, developer-facing messages, and API/schema keys.
Keep maintained technical documentation and commit messages in English as well.
Preserve user content in its original language; localization resources and
multilingual test fixtures may contain other languages. Never translate personal
data merely to satisfy this code convention.

## Phase boundary

Phase 6 desktop product is complete locally. Phase 7 is not authorized; do not
implement mobile/web clients or secure pairing until the user explicitly requests
it. Remote CI verification for completed phases remains unconfirmed.
For every later phase, follow specification section 74: plan only the current
phase, implement small increments, validate, update documentation and phase status,
then stop unless the user has authorized continuation. Explicit user instructions
take precedence over this recorded phase gate.

## Architecture and privacy

- Keep the Personalization Kernel independent of frameworks, databases, clients,
  agent runtimes, and model providers. Dependencies point inward.
- Put domain rules and ports in `packages/core-python`; wire concrete adapters in
  the daemon. Add interfaces only when the current phase needs them.
- Treat evidence as the source of derived beliefs. Preserve provenance and
  contradictions; corrections create evidence, and derived state is rebuildable.
- Record snapshot and algorithm versions with predictions. Keep Predict Me and
  Advise Me conceptually separate. Algorithms must be testable without an LLM.
- Validate structured model output. Providers and connectors never directly
  mutate the Personal Model.
- Default to local storage, loopback binding, strict-local privacy, and no
  telemetry. Future external calls must pass a central egress policy.
- Never commit personal data, credentials, local configuration, databases, or
  private prompts. Use synthetic fixtures. Do not log private payloads by default.
- Every persistent schema change requires a migration. Test restart behavior when
  persistence is introduced. Do not add services or future-phase integrations
  without an active requirement.

## Workflow

Use `uv` for Python and `pnpm` for TypeScript. Keep lockfiles in version control.
Use the commands in `CONTRIBUTING.md`; run lint, formatting checks, strict typing,
unit tests, and relevant integration tests before reporting completion. Update
`CHANGELOG.md` and `docs/phase-status.md` with actual results and limitations.
Do not claim remote CI passed based solely on local checks.
