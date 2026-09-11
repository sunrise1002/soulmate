# Quality gates

Quality checks are layered so failures are reported early while CI remains the
authoritative merge gate.

## Local commands

After installing the locked workspace and hooks, run the fast gate during normal
development:

```sh
pnpm check
```

Before requesting review, run the complete gate:

```sh
pnpm check:all
```

The complete gate verifies lockfiles, lint, formatting, strict types, unit and
integration tests, all pre-commit checks, and Python package builds. It must remain
cross-platform; do not hide repository checks in a developer-specific shell script.

Use focused commands while iterating:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest tests/unit
uv run --locked pytest tests/integration
uv build --all-packages
```

Do not claim a check passed unless it ran successfully in the environment being
reported. Local results do not imply that remote CI passed.

## Git hooks

Install every repository hook type:

```sh
uv run --locked pre-commit install --install-hooks \
  --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

- `pre-commit` checks file integrity, accidental credentials, Ruff, formatting,
  mypy, and the kernel architecture boundary.
- `commit-msg` enforces Conventional Commits.
- `pre-push` validates the branch name and runs the complete Python test suite.

Hooks are a fast local safety net, not a substitute for CI. Do not use `--no-verify`
to bypass a failure. If a hook itself is broken, preserve its output, open an issue,
and make a focused tooling fix.

## Continuous integration

GitHub Actions runs the Python gate across supported operating systems and Python
versions, validates the pnpm lockfile, runs repository hygiene hooks, and checks PR
branch names, titles, and every commit message. The exact required job names are
listed in [repository settings](repository-settings.md).

Any new runtime, language, or generated artifact must arrive with its formatter,
linter, type checker where applicable, tests, locked dependencies, and CI job in
the same PR. Do not add a documented check that CI cannot reproduce.

## Exceptions and suppressions

Prefer fixing the cause. A suppression is allowed only when the rule is incorrect
for a specific line or a safe boundary cannot otherwise be represented. Keep it
narrow, name the exact rule, and add a short explanation. Project-wide exclusions
require a documented rationale and maintainer review.

Never suppress architecture, privacy, migration, secret-detection, or failing-test
checks merely to merge. If a required gate is temporarily unavailable, the PR must
remain unmerged unless maintainers document an emergency decision and follow-up.
