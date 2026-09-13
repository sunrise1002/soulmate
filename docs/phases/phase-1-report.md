# Phase 1 report — Local Daemon and Persistence

## Authorization and scope

Phase 1 was explicitly authorized on 2026-09-11. Work is limited to specification
tasks P1-01 through P1-06; Phase 2 is not authorized.

## Implementation plan

1. Add infrastructure-independent base entities and repository ports needed by
   Phase 1.
2. Implement the SQLite adapter, WAL/foreign-key enforcement, initial Alembic
   migration, and repositories for the six base tables.
3. Compose database initialization, installation identity, API routes, and the
   durable worker in the daemon lifecycle.
4. Implement `serve`, `status`, and `doctor` with safe local diagnostics.
5. Test migrations, constraints, API behavior, CLI behavior, durable-job restart,
   and persistence across daemon restarts.
6. Run all required checks and package builds, then record actual results and
   remaining limitations here and in the phase-status index.

## Delivered work

| Task | Result |
| --- | --- |
| P1-01 SQLite | SQLAlchemy 2 adapter, WAL, foreign keys, busy timeout, core ports, packaged Alembic environment |
| P1-02 Base Tables | `profiles`, `sources`, `raw_events`, `audit_events`, `jobs`, and `system_metadata` in migration `0001_phase_1` |
| P1-03 Daemon | Lifespan-managed persistence and `/v1/health`, `/v1/system/info` |
| P1-04 Local Security | Loopback-only configuration retained; stable non-secret installation identity and default owner profile |
| P1-05 CLI | `serve`, `status`, and `doctor` with machine-readable JSON diagnostics |
| P1-06 Durable Jobs | In-process polling worker, atomic claims, retry limits, leases, and interrupted-job recovery |

The kernel contains only standard-library domain records and repository protocols.
All SQLAlchemy and Alembic code remains in `soulmate-storage-sqlite`; the daemon is
the composition root. Startup migrates before exposing the API or starting the
worker. Raw-event persistence is only the Phase 1 envelope; evidence extraction
and Personal Model semantics remain Phase 2 or later.

## Verification

Local verification on macOS arm64 with Python 3.12.14:

| Check | Result |
| --- | --- |
| Locked Ruff lint | Passed |
| Locked Ruff formatting check | Passed; 64 files formatted |
| Strict mypy | Passed; 29 source files |
| Unit and integration tests | 37 passed (25 unit, 12 integration) |
| Migration/restart tests | Passed, including automatic migration, identity persistence, and worker recovery |
| Core, daemon, and SQLite source/wheel builds | Passed |
| Frozen pnpm installation | Passed |
| Isolated wheel installation | Passed; installed daemon migrated and served without a source checkout |
| Packaged migration inspection | Passed; Alembic environment and `0001_phase_1` are present in the wheel |
| Installed CLI smoke test | Passed; health, system info, status, doctor, and clean shutdown |

An initial integration run exposed an Alembic transaction issue where SQLite kept
DDL but rolled back the revision marker. The migration environment was corrected
to use an engine-managed transaction, and regression tests now pass across
restart. No daemon was left running after verification.

## Known issues and limitations

- Remote GitHub Actions execution remains unverified; local results are not a CI
  claim.
- Starlette's test client still emits two upstream compatibility deprecation
  warnings; all tests pass.
- The worker framework intentionally has no production job handlers yet because
  evidence extraction, embeddings, model rebuilds, imports, and backups belong to
  later phases. Unsupported job types remain untouched.
- `doctor` reports provider and vector checks as deferred. Provider diagnostics
  belong to Phase 3, and vector storage is not an active Phase 1 requirement.
- The API has no client authentication because it is restricted to loopback.
  Secure LAN access, pairing, and device credentials remain Phase 7.

## Phase 2 handoff

Phase 1 exit criteria pass locally: `soulmate serve` provides a healthy
loopback service, creates persistent SQLite storage, restarts with the same
installation identity, and automatically applies the current migration.

Phase 2 may add evidence/provenance schemas, derived-state ports, deterministic
aggregation, versioned snapshots, rebuild behavior, and explainability only after
explicit user authorization. Read this entire report—especially the limitations
above—before producing the Phase 2 plan. Do not reinterpret the Phase 1
`raw_events` envelope as implemented evidence semantics.
