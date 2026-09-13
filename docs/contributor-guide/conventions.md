# Engineering conventions

This document defines the rules for implementation. The
[contributor guide index](README.md) links the Git workflow, executable quality
gates, repository settings, and configuration reference. Humans and AI agents
must use those documents together rather than infer conventions from nearby code.

## Language and naming

Communicate with AI agents in any language chosen by the user. All code uses
English, including identifiers, comments, docstrings, test names, API/schema keys,
and developer-facing messages. Technical documentation and commit messages use
English. Preserve original user content; translations and multilingual fixtures
are permitted where they are the data under test.

Use `snake_case` for Python modules/functions/variables, `PascalCase` for classes,
and `UPPER_SNAKE_CASE` for constants. Use `camelCase` for TypeScript variables and
functions, `PascalCase` for components/types, and `kebab-case` for package names.
The product is Soulmate; Python packages use `soulmate-*` distributions and
`soulmate_*` imports. Use `soulmate` for the CLI and `soulmate.db` for the default
database filename. Do not rename the original specification.

## Boundaries

Keep domain rules independent of transports, storage, provider SDKs, and agent
runtimes. Phase 0 core uses only the standard library. Architecture tests enforce
that baseline; future computational dependencies require a documented deliberate
change, while infrastructure dependencies remain forbidden. Do not bypass the
boundary using dynamic imports or service locators.

Core defines needed ports; adapters implement them. The daemon is the composition
root. Avoid global initialized clients, import-time I/O, speculative base classes,
and business logic in routes. Configuration belongs outside the kernel.

## Python and TypeScript

Use Python 3.12 syntax, explicit public type annotations, strict mypy, Ruff linting,
and Ruff formatting with 100-column lines. Prefer standard-library tools. Use
Pydantic v2 to validate external inputs; keep provider output validation at adapter
boundaries. Catch specific expected exceptions and expose clear errors without
private values. Do not suppress type/lint errors without explaining why.

Prefer small functions with one responsibility and explicit dependencies. Public
APIs require concise docstrings when names and types do not fully communicate the
contract. Use immutable values for domain records where practical. Avoid boolean
parameters that obscure intent, wildcard imports, hidden I/O, bare `except`, and
mutable default arguments.

Client packages use strict TypeScript configurations and include their compiler,
linter, formatter, and tests with actual source. Native desktop code uses Rust
formatting, Clippy with warnings denied, and offline unit tests. Keep webview IPC
typed and narrow; never expose arbitrary filesystem, shell, or network access.

## Data and algorithms

Use timezone-aware UTC timestamps and explicit stable IDs when entities arrive.
Never confuse confidence, uncertainty, strength, and preference value. Preserve
evidence provenance and contradictory evidence. Version algorithms and model
snapshots; make rebuild and scoring deterministic for fixed inputs and versions.
Keep prediction separate from advice. Every persisted schema change has a
migration. Do not store credentials in plaintext persistence or source control.

Treat logs, exceptions, fixtures, screenshots, and test snapshots as possible data
egress. Log identifiers and operational metadata only when required; do not log
raw conversations, prompts, credentials, tokens, or Personal Model payloads by
default. Redact at the boundary rather than relying on callers to remember.

## Tests and dependencies

Name tests after observable behavior. Test invalid inputs and failure behavior as
well as the success path. Keep unit tests offline and provider-independent. Use
temporary storage and deterministic fakes in integration tests. Keep fixtures
synthetic or pseudonymous. Add dependencies only for a current requirement and
keep `uv.lock` and `pnpm-lock.yaml` synchronized.

Follow Arrange–Act–Assert when it improves readability, and assert observable
behavior instead of private implementation details. A bug fix includes a regression
test. Tests must be deterministic across supported platforms and must clean up
processes, ports, files, and environment changes they create.

## Changes and documentation

Use the branch, commit, PR, review, and release rules in [workflow.md](workflow.md).
Use the exact local and CI commands in [quality-gates.md](quality-gates.md). Do not
mix refactoring, formatting, generated output, or dependency updates into an
unrelated functional change.

Update public documentation when behavior, configuration, commands, APIs, or
limitations change. Update `CHANGELOG.md` and `docs/phase-status.md` with factual
results; create an ADR for a significant or difficult-to-reverse architecture
decision. Documentation, examples, and error messages must not contain personal
data, local absolute paths, credentials, or machine-specific assumptions.
