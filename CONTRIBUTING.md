# Contributing

Read the technical specification, [agent rules](AGENTS.md),
[conventions](docs/contributor-guide/conventions.md), and
[current phase status](docs/phase-status.md) first. Before planning a phase, also
read the complete report linked for the immediately preceding phase so its actual
verification, limitations, and handoff state inform the plan.

## Environment

Use Python 3.12 via `uv`, Node.js 24, and pnpm 11.21.0. Install dependencies and the
local Git hook using the README commands. Both lockfiles belong in Git. Prefer
`uv add --package <name> <dependency>` for Python changes and `pnpm --filter <name>
add <dependency>` once client packages exist. Review lockfile changes.

## Required checks

Run from the repository root:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
uv build --all-packages
pnpm install --frozen-lockfile
```

`pnpm check` wraps the first four checks. Format Python with
`uv run --locked ruff format .`. The pre-commit hook uses the same locked tools;
`uv` must be available on the PATH inherited by Git and your editor.

Unit tests must avoid network and real LLMs. Integration tests currently start a
temporary loopback daemon and clean it up. Use synthetic data and temporary
directories. Add relevant migration/restart tests when persistence is introduced.
Evaluation and client test tooling will be added with their owning phases.

## Changes and review

Implement only the authorized phase. Keep increments small and cohesive. Name
branches `feat/<topic>`, `fix/<topic>`, or `chore/<topic>` and write concise English
commit messages such as `chore: initialize phase 0 workspace`.

A pull request should explain the problem, resulting behavior, verification, and
material limitations. Update the changelog and phase status. Write an ADR for a
significant architecture decision. Every feature requires implementation, useful
tests, error handling, documentation, and consideration of data ownership and
privacy; test restart persistence wherever relevant.

Do not advance to the next phase automatically. Phase 3 requires explicit user
authorization after the Phase 2 report.
