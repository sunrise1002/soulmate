# Changelog

## Unreleased

### Added

- Phase 4 decision records, explicit decision/predict/resolve APIs, validated
  natural-option feature extraction, and restart-safe SQLite persistence.
- Provider-independent preference matching, V1 utility scoring, softmax ranking,
  confidence estimation, and deterministic similar-decision retrieval.
- Predict Me explanations with important and uncertain factors, supporting
  Evidence, similar decisions, and persisted model snapshot/algorithm versions.
- Resolution learning that records the actual choice as a RawEvent, creates
  high-value relative preference Evidence, and rebuilds the Personal Model.
- SQLite migration `0004_phase_4` for decision events, options, predictions, and
  resolutions with snapshot referential integrity.
- Phase 3 persistent conversations, `/v1/chat`, deterministic minimal context
  compilation, and restart-safe conversational history.
- Provider-neutral generation interfaces, deterministic fake provider, Ollama and
  OpenAI-compatible HTTP adapters, and centrally enforced privacy-mode egress.
- Pydantic-validated fact, preference, goal, and constraint proposals with
  low-risk review, extractor model/version provenance, source-message links, and
  automatic model rebuilds.
- SQLite migration `0003_phase_3` for conversations, messages, and extraction
  provenance.
- Phase 2 evidence, provenance, derived Fact/Preference/Goal/Constraint records,
  deterministic versioned aggregation, and model rebuild service.
- SQLite migration `0002_phase_2` with evidence revision tracking, derived-state
  tables, immutable model snapshots, and Phase 1 upgrade coverage.
- `rebuild-model` CLI command and local API endpoints for model summaries,
  contextual preferences, corrections, and supporting evidence.
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

No embeddings, evaluation/calibration learning, Advise Me, desktop/mobile clients,
MCP integration, or later-phase features have been implemented.
