# Repository settings

Some protections live in GitHub rather than source control. A maintainer should
apply this checklist to the `main` branch ruleset and revisit it whenever workflow
job names change.

## Main branch ruleset

- Require a pull request before merging and at least one approving review.
- Dismiss stale approvals when new commits are pushed.
- Require review from Code Owners when a real ownership map is added.
- Require all conversations to be resolved.
- Require the branch to be up to date and require these status checks:
  - `Contribution policy`
  - every `Python <version> / <operating-system>` matrix result
  - `Repository hygiene`
  - `pnpm workspace`
- Block force pushes, branch deletion, and direct pushes.
- Require linear history and signed commits when every active contributor has a
  viable signing setup; do not enable signing ad hoc for only some contributors.
- Allow bypass only for the smallest maintainer group and audit every use.

## Pull requests and merging

- Enable squash merging and disable merge commits.
- Disable rebase merging if squash is the project-wide policy.
- Use the PR title as the squash commit subject.
- Automatically delete merged head branches.
- Enable private vulnerability reporting.
- Keep Actions permissions read-only by default and grant write scopes only to a
  job with a documented need.

## Periodic audit

At least before each public release, confirm that required checks still match the
workflow names, branch protection applies to administrators, no secrets are stored
as plain repository variables, and abandoned collaborators or deploy keys have
been removed. Repository configuration is not verified by local tests, so record
the audit in the release notes or maintainer issue.
