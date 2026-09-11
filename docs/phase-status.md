# Phase status

## Authorized scope

Phase 0 — Repository & Architecture Foundation only. The user requested setup
and a report before Phase 1. Phase 1 has not started and requires the user's next
instruction. Do not advance automatically.

## Phase 0 implementation plan

1. Read the specification and inspect the initial repository.
2. Create uv and pnpm workspaces with core/daemon package boundaries.
3. Implement typed configuration and the minimal empty daemon startup shell.
4. Record conventions, agent language rules, and ADR-001 through ADR-008.
5. Configure checks, Git hooks, and CI; verify install, startup, and boundaries.
6. Record verification and report to the user before Phase 1.

## Task status

| Task | Status |
| --- | --- |
| P0-01 Repository | Implemented; local workspace installation and package builds passed |
| P0-02 Core Domain Package | Implemented; dependency-free package and empty module boundaries |
| P0-03 Configuration | Implemented; TOML, environment overrides, DATA_DIR |
| P0-04 ADRs | ADR-001 through ADR-008 recorded |
| P0-05 CI | Workflow configured; remote execution pending |

## Verification

Local checks on macOS arm64 with Python 3.12.14:

| Check | Result |
| --- | --- |
| Locked uv workspace installation | Passed |
| Frozen pnpm lockfile installation | Passed |
| Ruff lint and formatting | Passed |
| Strict mypy | Passed |
| Unit and integration tests | 27 passed (24 unit, 3 integration) |
| Core and daemon source/wheel builds | Passed |
| Isolated core wheel installation | Passed; imports without FastAPI or SQLAlchemy installed |
| Installed CLI startup and cleanup | Passed; loopback HTTP responds 404, no storage created |
| Git pre-commit hooks | Installed; lint, format, typing, architecture hooks passed |

The test dependencies emit two upstream deprecation warnings in Starlette's test
client (`httpx` compatibility and AnyIO's `BlockingPortal` alias); current tests
pass, and the warnings remain visible. Revisit test-client compatibility when
adding Phase 1 API tests.

The repository uses `main`, with `origin` configured as
`git@github.com:sunrise1002/soulmate.git`. GitHub Actions is configured for
Linux/macOS/Windows with Python 3.12 and 3.14, plus a pnpm lockfile job.
Remote CI has not been verified; its exit criterion remains pending.
Phase 0 preparation is implemented locally, with remote CI verification pending.

On this machine, uv 0.12.13 was installed at `~/.local/bin/uv` without changing
shell startup files. Ensure `~/.local/bin` is on PATH (see README). Node 24.19.0
and pnpm 11.21.0 were already available. No daemon remains running after tests.

## Phase 1 handoff — not started

The next phase covers SQLite/WAL/foreign keys, migrations, required repository
ports, base tables, health/system endpoints, installation identity, expanded CLI
commands, and durable jobs. Produce a phase-specific implementation plan only
after the user instructs the agent to begin.

Phase 0's `serve` command only hosts an empty app to meet the foundation startup
criterion. It returns 404 on all paths and does not create the database. Reserved
folders do not represent implementation of future phases.

## Repository governance

Phase-neutral contribution governance was standardized on 2026-09-11. Local
quality gates, Git metadata policy, CI enforcement, templates, security guidance,
and maintainer repository settings are documented under the
[contributor guide](contributor-guide/README.md). This does not alter the authorized
phase boundary above. Remote CI and GitHub ruleset activation remain unverified.
