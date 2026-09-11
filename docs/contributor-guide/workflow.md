# Contribution workflow

Soulmate uses a short-lived-branch GitHub flow. `main` is the single integration
branch and must remain releasable. Do not create long-lived `develop`, phase, or
environment branches.

## Before starting

1. Read the root specification, `AGENTS.md`, engineering conventions, current phase
   status, and the complete previous-phase report.
2. Confirm that the issue belongs to the authorized phase. Repository maintenance
   may proceed without advancing product behavior.
3. Search existing issues and ADRs. Open or confirm an issue before a material
   change so scope and acceptance criteria are visible.
4. Branch from an up-to-date `main`. Do not mix unrelated cleanup with the change.

## Branches

Use `<type>/<kebab-case-topic>`:

```text
feat/model-summary
fix/daemon-shutdown
docs/privacy-boundary
chore/update-ruff
```

Allowed types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, `release`, `revert`, and `test`. Automated `dependabot/*` and
`renovate/*` branches are also accepted. Delete a branch after merge.

## Commits

Use Conventional Commits with a lowercase, imperative summary:

```text
feat(api): add model summary endpoint
fix(storage): preserve migration revision
docs: clarify local-only privacy defaults
```

The allowed commit types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`,
`perf`, `refactor`, `revert`, `style`, and `test`. Keep the header at or below 100
characters, omit the final period, and separate an optional body with a blank line.
Use `!` and a `BREAKING CHANGE:` footer only for an intentional breaking change.

Each commit should represent one reviewable idea and leave relevant checks passing.
Do not include generated local data, secrets, unrelated formatting, or another
contributor's working-tree changes. Temporary `fixup!` commits are acceptable only
while developing and must be autosquashed before opening or updating the PR.

## Pull requests

Open a draft PR early for non-trivial work. Its title follows the same format as a
commit header because merges use the squash strategy. Complete the PR template with:

- the concrete problem and resulting behavior;
- the current phase and explicit scope boundaries;
- tests and exact commands run;
- privacy, persistence, migration, and compatibility impact;
- documentation, changelog, phase-status, and ADR updates;
- known limitations or follow-up work.

Keep PRs small enough to review as one coherent change. Reviewers check behavior,
architecture boundaries, failure paths, test value, privacy, migration safety, and
documentation—not only style. Resolve discussions or record a deliberate follow-up
before merge.

## Merge and release

Required checks and review must pass. Rebase on `main` when needed, then squash
merge using the validated PR title. Force pushes and direct pushes to `main` are
disabled by repository rules except for documented emergency maintainer recovery.

Releases are cut from `main` with an annotated SemVer tag. Release preparation uses
`release/<version>`, updates the changelog and version metadata, runs the complete
quality gate, and contains no unrelated feature work. Until an automated release
process exists, maintainers must record the exact build and verification commands.
