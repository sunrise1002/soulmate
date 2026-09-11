# Phase 0 report — Repository and Architecture Foundation

## Outcome

Phase 0 is implemented locally. The repository has installable uv packages, a pnpm
workspace, an infrastructure-independent kernel boundary, typed configuration, an
empty loopback daemon shell, architecture records, local checks, hooks, and CI
configuration.

## Delivered work

| Task | Result |
| --- | --- |
| P0-01 Repository | uv/pnpm workspace, builds, license, repository layout |
| P0-02 Core Domain Package | Dependency-free package and empty module boundaries |
| P0-03 Configuration | Typed TOML and environment loading with `DATA_DIR` |
| P0-04 ADRs | ADR-001 through ADR-008 recorded |
| P0-05 CI | Cross-platform GitHub Actions workflow configured |

## Verification

Local verification on macOS arm64 with Python 3.12.14:

| Check | Result |
| --- | --- |
| Locked uv workspace installation | Passed |
| Frozen pnpm lockfile installation | Passed |
| Ruff lint and formatting | Passed |
| Strict mypy | Passed |
| Unit and integration tests | 27 passed (24 unit, 3 integration) |
| Core and daemon source/wheel builds | Passed |
| Isolated core wheel installation | Passed without infrastructure dependencies |
| Installed CLI startup and cleanup | Passed; loopback returned 404 and created no storage |
| Git pre-commit hooks | Installed and passed |

## Known issues and limitations

- Remote GitHub Actions execution was not verified.
- Starlette's test client emitted two upstream compatibility deprecation warnings.
- The Phase 0 daemon intentionally had no product endpoints or persistence.
- uv 0.12.13 was installed at `~/.local/bin`; that directory must be on the invoking
  environment's `PATH`.

## Phase 1 handoff

Implement SQLite with WAL and foreign keys, Alembic migrations, required core
repository ports and base tables, health/system endpoints, installation identity,
`serve`/`status`/`doctor`, and a durable local worker. Verify automatic migration
and restart persistence. Do not implement Phase 2 evidence semantics.
