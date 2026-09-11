## Summary

Describe the concrete problem and resulting behavior. Link the issue and identify
the authorized phase or explain why this is phase-neutral maintenance.

## Scope

List what is intentionally included and excluded. Call out architecture-boundary,
API, compatibility, persistence, migration, privacy, and data-ownership impact.

## Validation

List exact commands actually run, their results, and any environment or remote-CI
limitations. Include a regression test for a bug fix.

## Documentation

Link relevant docs, changelog, phase-status, and ADR updates. Explain any item
marked not applicable below.

## Checklist

- [ ] The branch and PR title follow the contribution workflow.
- [ ] The change stays inside the authorized phase and contains no unrelated work.
- [ ] Tests cover success and relevant failure behavior with synthetic data.
- [ ] `pnpm check:all` passes locally, or failures are documented above.
- [ ] No credentials, private prompts, personal data, or local configuration are included.
- [ ] Persistence changes include a migration and restart coverage, or are not applicable.
- [ ] Documentation, `CHANGELOG.md`, and `docs/phase-status.md` are updated as applicable.
- [ ] Significant architecture decisions have an ADR, or no ADR is needed.
