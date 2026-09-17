# Changelog

## Unreleased

### Added

- Accuracy spike for the key consistency increment (step P0): a packaged
  synthetic `synthetic-key-retrieval-v1` dataset (168 dotted keys with Vietnamese
  owner labels, 84 Vietnamese and English messages, 27 opposite key pairs) and a
  deterministic `soulmate_core.evaluation.key_retrieval` harness that measures
  recall inside the shared key budget, mean reciprocal rank, and the rate at which
  opposite keys would be merged automatically. Measured on macOS arm64, today's
  word-overlap ranking shares the right key for 27.3% of Vietnamese messages
  against 97.7% for a local `bge-m3` int8 model, and 100% once owner labels are
  included; every opposite key pair scored closer to its opposite than a typical
  correct match, so semantic merges stay owner-reviewed. ADR-016 records the
  embedding port, the owner-initiated pinned download, and the owner-confirmed
  `bge-m3` int8 default; `scripts/key_embedding_spike.py` reproduces the numbers
  from a throwaway environment. No product code loads a model, and `onnxruntime`,
  `tokenizers`, and `numpy` are still not dependencies.
- Key consistency wiring for the key consistency increment (step P3): reviewed
  evidence now creates active `normalized` aliases automatically when two used
  keys share one `key-normalizer-v1` form, so `ui.theme.dark_mode` reinforces
  `ui.theme.dark` instead of splitting the model. Evidence keeps its original
  key. The decision predictor and its pairwise learner map option feature keys
  through active aliases and, for keys the model does not know, through
  normalization, so a decision extracted under a variant key uses the learned
  preference instead of returning 50/50. Every daemon workflow builds its
  `ModelRebuilder` through one factory, and snapshots record whether aliases were
  applied, so turning `key_aliases.enabled` off rebuilds the model from the
  original keys on the next read. A new owner-only API (`GET /v1/key-aliases`,
  `POST /v1/key-aliases`, `/review`, `/remove`) lists, merges, approves, rejects,
  inverts, and undoes aliases, records audits without key names, and returns the
  rebuilt snapshot version; the desktop and web Model screens gained a
  "Duplicate keys" review list, and the TypeScript SDK gained the matching
  methods. Semantic suggestions, key labels, and embeddings remain unimplemented.
- Persistence for the key consistency increment (step P2): migration
  `0011_key_consistency` adds `target_key_aliases`, `target_key_catalog`, and
  `target_key_embeddings` with a downgrade that drops them;
  `SqliteTargetKeyAliasRepository` behind the new `TargetKeyAliasRepository` port
  rejects active alias cycles at write time and advances the evidence revision on
  every change; `ModelRebuilder` optionally applies active aliases. Evidence
  deletion (single evidence, import removal, connector removal) prunes aliases,
  labels, and embeddings that no remaining evidence supports. Local and remote
  backups include all three tables; encrypted portable exports drop the derived
  embeddings; restore treats stored aliases or labels as owner data. The daemon
  does not pass aliases to model rebuilds yet, and nothing creates aliases.
- Infrastructure-free key canonicalization core for the key consistency
  increment (step P1): a versioned `key-normalizer-v1` `normalize_key`, a
  `TargetKeyAlias` domain record with polarity, review status, and provenance
  method, a cycle-safe `KeyAliasMap`, and alias-aware evidence aggregation that
  groups semantically equal keys under one canonical key and folds opposite
  preference keys into one signed axis. Evidence is never rewritten, only active
  aliases apply, and removing an alias restores the previous grouping. Nothing is
  persisted or wired into extraction, prediction, or clients yet.
- Provider capability negotiation for OpenAI-compatible endpoints: strict JSON
  Schema, JSON-object mode, and validated schema-guided JSON fallback, with the
  successful mode cached per configured provider instance; Ollama also gains a
  validated prompted-JSON fallback.
- A restricted portable Evidence-extraction schema that avoids recursive,
  unconstrained, and dynamic JSON Schema constructs that differ across GPT,
  Gemini, Claude compatibility, DeepSeek, GLM, Kimi, Ollama, and local runtimes.
- Separate chat and learning execution: successful replies and RawEvents persist
  before extraction, every extraction runs as a durable ID-only background job,
  and only validated/reviewed output can update the Personal Model. Failed jobs
  retry with bounded exponential backoff instead of immediately consuming model
  quota; the desktop bridge waits longer than the provider transport so it does
  not abandon a reply that the daemon may still persist.
- Pure desktop settings projection in native tests so capability/UI checks do not
  access the operating-system credential store during offline Rust tests.

- Desktop remote-backup setup for non-technical users, including R2/S3 endpoint,
  private bucket, schedule, and write-only keychain storage for access keys and
  the archive passphrase; no `.env` file is required for the managed daemon.
- Optional encrypted remote backups behind a vendor-neutral storage port, with an
  S3-compatible adapter for R2, S3, B2, MinIO, and compatible private stores;
  local SQLite remains the default and live database files are never uploaded.
- Durable opt-in daily remote-backup scheduling, owner-only manual/status/latest-
  restore APIs, `remote-backup` and `remote-restore-latest` CLI commands, typed SDK
  operations, and desktop Data & Privacy controls.
- Environment-only remote backup passphrase and S3 credentials, hybrid-mode
  egress enforcement for external endpoints, encrypted fresh-install machine
  handoff, and ADR-015 documenting the provider-neutral boundary.
- A source-checkout setup, build, and run guide covering toolchain and native OS
  prerequisites, locked workspace installation, explicit POSIX/PowerShell `.env`
  loading, local and compatible model providers, daemon/desktop/web/mobile run
  modes, build artifacts, verification, and troubleshooting.
- A recorded post-MVP roadmap and detailed Phase 13 Decision I/O and trusted
  provenance plan, including scope, architecture invariants, implementation
  increments, migration and compatibility requirements, test perspectives, exit
  criteria, and an explicit pre-implementation authorization gate.
- Consolidated single-page project guide at `docs/index.html` covering vision,
  core concepts, architecture, technology stack, setup, usage, configuration,
  API surface, external agents, connectors, portability, privacy, and status.
- `docs/README.md` documentation index describing every document and the
  precedence order between them.
- Phase 12 deterministic Policy Engine with owner-assigned low, medium, high, and
  safety-critical impact classes, enforced confidence floors, current-snapshot
  prediction binding, and 24-hour authorization expiry.
- Separate `agent:delegate` permissions, per-agent and per-action policies,
  idempotent durable delegation requests, mandatory owner confirmation for high
  and safety-critical actions, and approve/reject/complete lifecycle auditing.
- Owner and external delegation REST APIs, three MCP delegation tools, typed
  TypeScript SDK methods, desktop policy and approval workflows, migration
  `0010_phase_12`, and ADR-013.
- Phase 11 dependency-free Python connector SDK with immutable manifests,
  validated RawEvent output, declared data/network/credential/learning
  permissions, and independently installable `soulmate.connectors` entry points.
- Owner-consented connector registration, environment-only credentials,
  manifest-host and privacy-mode egress enforcement, durable idempotent sync jobs,
  sanitized local audits/status, and migration `0009_phase_11`.
- Independently packaged Local Notes reference connector with bounded UTF-8
  Markdown/text ingestion and no network access.
- Owner-only connector REST and CLI discovery surfaces, typed TypeScript SDK,
  desktop Connections screen, provenance-complete removal and model rebuild, and
  ADR-012 for the trusted plugin boundary.
- Phase 10 consistent SQLite backups, encrypted `.dtw` portable exports using
  scrypt and AES-256-GCM, fresh-install restore with schema migration and a
  deterministic Personal Model rebuild, and credential-free archive manifests.
- Static chat history imports for generic JSON, Markdown, plain text, ChatGPT,
  and Claude exports, with source-linked conversations and RawEvents.
- Owner-only source deletion that atomically removes imported conversations,
  RawEvents, and derivative Evidence before rebuilding the Personal Model.
- `backup`, `export`, `restore`, and `import` CLI commands, owner-only data APIs,
  typed SDK operations, a desktop Data & Privacy screen, migration
  `0008_phase_10`, and ADR-011 for the portability boundary.
- Phase 9 external service identities with independent revocable credentials,
  five least-privilege scopes, hash-only API-key persistence, and owner-controlled
  credential rotation and permission changes.
- Privacy-minimal external intelligence endpoints for model and preference
  summaries, prediction, ranking, similar decisions, decision recording, and
  outcome recording, with local metadata-only auditing for every request.
- A stdio MCP adapter with `predict_choice`, `rank_options`,
  `get_preference_summary`, `find_similar_decisions`, `record_decision`, and
  `record_outcome`, available through `soulmate mcp` and the packaged daemon
  sidecar.
- Desktop External Agents permission UI, typed TypeScript external-access SDK,
  and SQLite migration `0007_phase_9` for identities, scopes, and API-key hashes.
- Phase 8 deterministic uncertainty ranking, heuristic information-gain question
  selection, persistent pairwise questions, and evidence-backed answers.
- Restart-safe decision outcomes with satisfaction, regret, optional notes, and a
  typed API shared by desktop, web, and mobile clients.
- A separate wellbeing-aware Advise Me model that combines behavioral probability,
  similar reported outcomes, and matching goals or constraints while preserving
  Predict Me as a descriptive model.
- SQLite migration `0006_phase_8` for active questions, answers, outcomes, and
  versioned advice records, plus ADR-010 documenting the behavioral/wellbeing split.
- Phase 7 opt-in access from other devices: a second TLS listener on an explicit
  LAN address, a self-signed service certificate with renewal, and a rejection of
  wildcard binds in both configuration and address resolution.
- One-time, short-lived, high-entropy QR pairing with atomically claimed tokens,
  hashed device credentials, owner-only device listing and revocation, and audit
  events for token issue, pairing, and revocation.
- A single authorization boundary in front of every route: loopback callers are the
  owner, other callers need a paired device credential, and device management, LAN
  status, and evidence deletion stay owner-only.
- `@soulmate/sdk` typed REST client and pairing payload rules shared by clients,
  `@soulmate/web` browser client served from the daemon root, and `@soulmate/mobile`
  Expo React Native client with QR scanning, secure credential storage, and pinned
  service identity.
- Desktop Devices screen for enabling access from other devices, creating pairing
  codes, and revoking paired devices.
- SQLite migration `0005_phase_7` for paired devices and pairing tokens.
- Phase 6 installable Tauri 2 desktop product with a React/TypeScript interface for
  Chat, Decide, My Model, Decision History, and Settings.
- Target-specific PyInstaller daemon sidecar builds, native lifecycle and health
  management, bounded logs, and macOS/Windows/Linux installer CI jobs.
- Desktop Ollama and OpenAI-compatible provider setup, OS credential-store secret
  handling, and strict-local, hybrid, and offline privacy controls.
- Conversation and decision history API reads plus evidence deletion with a
  deterministic Personal Model rebuild.
- Phase 5 synthetic decision benchmark and offline `soulmate evaluate`
  command with reproducible random, frozen LLM-only, memory-only, Personal Model,
  and Decision Model comparisons.
- Top-1 and Top-2 accuracy, log loss, multiclass Brier score, and populated-bin
  expected calibration error metrics.
- Deterministic online Bradley-Terry/logistic updates over resolved choices with
  global, domain-specific, and contextual weights.
- Context-weighted Personal Model preference matching and a versioned V2 decision
  algorithm recorded on every new prediction.
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

No embeddings, real-provider evaluation, remote MCP transport,
signing/notarization, automatic updates, plugin sandbox, or live third-party
service connector has been implemented. Delegation grants authorization but does
not execute or verify third-party side effects. Imported and connector sources are
normalized locally but do not automatically invoke an LLM or create derived
Evidence.

### Changed

- Natural-language decision feature extraction now sends the current Personal
  Model preference keys (keys only, no values) to the provider and asks it to
  reuse them, so options such as `ui.theme.dark` match preferences learned from
  chat instead of near-duplicate keys like `ui.theme.dark_mode` that left
  predictions at chance. Existing decisions keep their stored features.
- Conversation evidence extraction now receives known fact, preference, goal,
  and constraint keys (keys only) and shared key rules: reuse a matching known
  key, otherwise prefer a listed namespace, and model opposites as one signed
  axis, so repeated statements reinforce one Personal Model entry.
- Deterministic local known-key selection (`select_known_keys`): models with at
  most 100 keys are shared whole; larger models share every key namespace plus
  the 50 highest-scoring keys, ranked by use earlier in the same conversation
  (or in resolved decisions of the same domain), word overlap with the message,
  earlier user turns, or option text, and domain match, then by confidence and
  recency. Word overlap cannot bridge languages, so a missed key falls back to
  its listed namespace.
  `ModelRebuilder.current()` and the read-only `current_model()` replace
  duplicated snapshot-freshness checks; learning does not persist extra snapshots.
- Corrected managed desktop daemon restart and exit cleanup for the PyInstaller
  one-file sidecar: the shell now requests graceful shutdown over a private stdin
  control pipe, waits for the complete sidecar process to exit before restarting,
  rejects an already occupied port before spawning, and smoke-tests two
  consecutive packaged start/stop cycles.
- Expanded the configuration reference with every supported TOML/environment
  field, precedence, valid values, defaults, purpose, security behavior, and
  runnable examples; made `.env.example` safe when `config.toml` does not exist.
- Corrected the browser development instructions to use a daemon-served bundle
  for end-to-end flows, documented native installer output, clarified the Docker
  and mobile limitations, and removed links to a nonexistent translated guide.
- Standardized the remaining legacy product identifiers on Soulmate across the
  CLI executable, default database filename, connector credential variables,
  packaged desktop sidecar, tests, configuration examples, and documentation.
  Existing installations must rename their default database file and update
  connector credential environment variables before upgrading.
- Shortened `README.md` to orientation, quick start, CLI, device access,
  repository map, and a documentation index; the per-phase narrative now lives in
  `docs/index.html` and the phase reports.
