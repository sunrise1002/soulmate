# Changelog

## Unreleased

### Added

- Phase 1 SQLite adapter with WAL, foreign keys, six base tables, repositories, and
  packaged Alembic migration `0001_phase_1`.
- Persistent local installation identity and default owner profile.
- `/v1/health` and `/v1/system/info` loopback service endpoints.
- `status` and `doctor` CLI commands with JSON output and local diagnostics.
- In-process durable job worker with retry leases and interrupted-job recovery.
- Per-phase reports and an agent handoff rule requiring the previous report to be
  read before planning the next phase.
- Phase 0 uv/pnpm monorepo with installable core and daemon packages.
- Typed TOML/environment configuration and a loopback-only empty daemon shell.
- Ruff, strict mypy, pytest, pre-commit, and a GitHub Actions matrix.
- Architecture dependency checks and configuration/process integration tests.
- ADR-001 through ADR-008, contributor conventions, and a Phase 1 stop gate.
- Agent rule allowing conversation in any language while code uses English.
- Repository-wide contribution policy with expanded Ruff rules, hygiene and Git
  hooks, Conventional Commit and branch validation, CI enforcement, issue/PR
  templates, security guidance, and documented GitHub ruleset settings.

No evidence-derived Personal Model behavior, provider integrations, vector search,
or later-phase features have been implemented.
