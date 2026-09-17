# Phase status

This is the phase index and authorization gate. Read the linked full report for
the previous phase before planning or implementing the current phase.

## Authorized scope

Phase 12 — Delegated Decision Agent is complete locally. Phase 13 — Decision I/O
and trusted provenance has a recorded plan, but implementation has not started and
requires a separate explicit owner instruction. No Phase 14 or later work is
defined or authorized for implementation.

An owner-authorized cross-phase portability increment for optional encrypted
remote backup is complete locally. It keeps SQLite as the local primary store,
adds a provider-neutral storage port with an S3-compatible adapter, durable daily
and manual uploads, and fresh-install latest restore. It does not start Phase 13
or authorize a later phase. See the
[remote backup increment report](phases/remote-backup-increment-report.md).

The owner authorized the key consistency increment on 2026-09-17, and step P1 of
its [plan](phases/key-consistency-increment-plan.md) is implemented locally:
`normalize_key`, the `TargetKeyAlias` domain record, and alias-aware aggregation
inside the kernel, with no persistence, no wiring, and no new dependency. Steps
P0 and P2 to P6 are not implemented. This does not start Phase 13 or authorize a
later phase. Step P2 (migration `0011`, alias repository, revision bump, deletion
cleanup, and archive coverage) followed on the same day; steps P0 and P3 to P6 are
not implemented.

## Reports

| Phase | State | Report | Important open issue |
| --- | --- | --- | --- |
| Phase 0 | Complete locally | [Phase 0 report](phases/phase-0-report.md) | Remote CI unverified |
| Phase 1 | Complete locally | [Phase 1 report](phases/phase-1-report.md) | Remote CI unverified; deferred diagnostics documented |
| Phase 2 | Complete locally | [Phase 2 report](phases/phase-2-report.md) | Remote CI unverified; extraction intentionally deferred |
| Phase 3 | Complete locally; compatibility maintenance verified | [Phase 3 report](phases/phase-3-report.md) | Remote CI and broad live-provider coverage unverified |
| Phase 4 | Complete locally | [Phase 4 report](phases/phase-4-report.md) | Remote CI, real provider extraction, and calibration unverified |
| Phase 5 | Complete locally | [Phase 5 report](phases/phase-5-report.md) | Remote CI and external-dataset calibration unverified |
| Phase 6 | Complete locally | [Phase 6 report](phases/phase-6-report.md) | Remote cross-platform installers, signing, and real providers unverified |
| Phase 7 | Complete locally | [Phase 7 report](phases/phase-7-report.md) | Remote CI, native mobile builds, and browser trust of the self-signed certificate unverified |
| Phase 8 | Complete locally | [Phase 8 report](phases/phase-8-report.md) | Remote CI, richer question generation, native mobile builds, and external outcome calibration unverified |
| Phase 9 | Complete locally | [Phase 9 report](phases/phase-9-report.md) | Remote CI, remote MCP transport, cross-platform packaged MCP smoke tests, and native mobile builds unverified |
| Phase 10 | Complete locally | [Phase 10 report](phases/phase-10-report.md) | Remote CI, cross-platform restore, large archives, and native mobile builds unverified |
| Phase 11 | Complete locally | [Phase 11 report](phases/phase-11-report.md) | Remote CI, plugin sandboxing/signing, scheduled sync, real service connectors, and cross-platform packaged discovery unverified |
| Phase 12 | Complete locally | [Phase 12 report](phases/phase-12-report.md) | Remote CI, broad real-world confidence calibration, external action verification, notifications, and cross-platform packaged behavior unverified |
| Phase 13 | Planned; not started | [Phase 13 plan](phases/phase-13-plan.md) | Implementation requires explicit owner instruction; ADR and contracts are not yet accepted |

## Phase 12 exit criteria

Passed locally on macOS arm64. An approved external identity can request a fresh
prediction-bound action, receive automatic authority only inside exact owner-set
low/medium impact and confidence limits, wait for owner confirmation otherwise,
and complete one durable authorization without receiving raw Personal Model data.

## Next action

When the owner explicitly authorizes implementation, execute only the recorded
[Phase 13 plan](phases/phase-13-plan.md), beginning with ADR-014 and the contract
freeze. Follow specification section 74, validate the complete phase, update its
report and this status, then stop. Do not infer authorization for agent hooks,
Git observation, shadow prediction, later autonomous execution, notifications,
policy expansion, or safety-critical behavior.

## Repository governance

Phase-neutral contribution governance was standardized on 2026-09-11. Local
quality gates, Git metadata policy, CI enforcement, templates, security guidance,
and maintainer repository settings are documented under the
[contributor guide](contributor-guide/README.md). This does not alter the authorized
phase boundary above. Remote CI and GitHub ruleset activation remain unverified.

## Repository maintenance

On 2026-09-17, model-provider compatibility was strengthened without starting a
new phase. OpenAI-compatible endpoints now negotiate strict schema, JSON-object,
and validated prompted-JSON strategies; Ollama has a native-to-prompt fallback;
Evidence extraction uses a portable wire schema; and successful chat is retained
and returned before a durable ID-only learning job runs behind the same
validation/review boundary. Failed jobs use bounded exponential backoff instead of
immediately consuming all retries and provider quota. The existing
Gemini configuration completed a synthetic extraction through negotiated
`json_object` mode. `pnpm check:all` passed locally with 310 Python, 87 TypeScript,
and seven Rust tests, seven Python package builds, a clean macOS arm64 PyInstaller
sidecar build, repository hooks, and web and desktop production builds. Remote CI,
broad live-provider interoperability, and packaged Windows/Linux behavior remain
unverified. No migration was required. Phase 13 scope, ordering, persistence plan,
and explicit authorization gate are unchanged; its plan records this impact
review.

Also on 2026-09-17, extraction key consistency was improved without starting a
new phase. Chat evidence extraction and natural decision option extraction now
receive known target keys plus namespaces and are asked to reuse them, so learned
preferences and decision features share keys instead of near-duplicates that left
predictions at chance. Models above 100 keys are filtered locally and
deterministically to 50 keys by conversation or same-domain decision history,
word overlap, domain, confidence, and recency; only key names leave the device.
`pnpm check` passed locally, including 340 Python tests; `pnpm check:all`, coverage
collection (pytest-cov is not installed), and live-provider behavior were not
verified. No migration was required. Cross-language key matching (multilingual
key labels or local embeddings) and post-extraction key canonicalization remain
unimplemented; their persistence plan is recorded in the
[key consistency increment plan](phases/key-consistency-increment-plan.md) and
records the owner decisions of 2026-09-17 (migration `0011` for this increment and
`0012` for Phase 13, owner-initiated model download, reviewed semantic merges, and an
accuracy-first embedding model).

On 2026-09-17 the owner authorized that plan and step P1 was implemented: the
kernel gained the versioned `key-normalizer-v1` `normalize_key`, a `TargetKeyAlias`
record carrying polarity, review status, method, similarity, and algorithm version,
a cycle-safe `KeyAliasMap` that follows only active aliases, and
`aggregate_evidence(..., aliases=...)`, which groups aliased keys under one
canonical key and inverts opposite preference values. Evidence is never rewritten,
so removing an alias and rebuilding restores the previous grouping. `ruff check`,
`ruff format --check`, strict `mypy`, and 398 Python tests passed locally;
`pnpm check:all`, coverage collection (pytest-cov is still not installed), and
client behavior were not verified. No migration, dependency, persistence, API, or
client change was made; the alias tables, extraction and predictor wiring, owner
review API and UI, embeddings, and the P0 model spike remain unimplemented.

Step P2 was implemented later on 2026-09-17. Migration `0011_key_consistency`
creates `target_key_aliases` (natural key `profile_id`, `target_type`,
`alias_key`, with database checks mirroring the domain rules),
`target_key_catalog`, and `target_key_embeddings`; its downgrade drops only those
tables. `SqliteTargetKeyAliasRepository` implements the new
`TargetKeyAliasRepository` port, rejects active aliases that would close a direct
or transitive cycle, keeps the first `created_at`, and advances the evidence
revision on every upsert and removal, so `ModelRebuilder.current()` rebuilds.
`ModelRebuilder` accepts an optional alias repository and applies only active
aliases. Deleting evidence, an import, or a connector prunes aliases, catalog
labels, and embeddings whose keys no remaining evidence supports (active aliases
carry support onto their canonical key; suggested and rejected aliases need both
keys supported). Local and remote backups keep all three tables, encrypted
portable exports drop embeddings, and restore refuses targets holding aliases or
labels. Migration from a real `0010` schema, downgrade, restart, cycle
rejection, deletion, backup, export, and restore tests were added. `ruff check`,
`ruff format --check`, strict `mypy`, `pre-commit run --all-files`, and 430 Python
tests passed locally; `pnpm check:all` and coverage were not run. Limitations: the
daemon still constructs `ModelRebuilder` without aliases, catalog and embedding
tables have no repositories yet, and no code creates aliases.

On 2026-09-16, desktop daemon restart and application-exit cleanup were corrected
for the PyInstaller one-file sidecar. The shell now uses a private graceful
shutdown pipe, waits for full process termination before restart, rejects an
occupied port before spawn, and packages a two-cycle restart smoke test. This
maintenance does not change the public API, persistence, privacy boundary, or
authorized phase scope. `pnpm check:all`, 304 Python tests, 87 TypeScript tests,
seven native Rust tests, a clean macOS arm64 sidecar build with two managed
restart cycles, package builds, repository hooks, and web/desktop production
builds passed locally. Remote CI and packaged Windows/Linux behavior remain
unverified; details are recorded in the Phase 6 report.

On 2026-09-16, the Desktop remote-backup workflow was expanded for non-technical
owners. Settings now captures R2/S3-compatible connection details and scheduling,
stores access keys and the encryption passphrase in the operating-system
credential store, injects them only into the managed daemon, and keeps remote
backup disabled by default. Python lint, formatting, strict typing, and 302 tests;
TypeScript lint, formatting, strict typing, and 87 tests; plus six native Rust
tests, formatting, and Clippy with warnings denied passed on macOS arm64. Live R2
interoperability, packaged cross-platform behavior, and remote CI remain
unverified.

On 2026-09-16, optional encrypted remote backup was added as an explicitly
authorized portability increment. Local-only SQLite remains the default; external
storage is behind a vendor-neutral port, with R2 represented through the included
S3-compatible adapter. Manual and durable daily backup plus latest fresh-install
restore are available through CLI, owner-only REST, typed SDK, and desktop
surfaces. Python lint, formatting, strict typing, 302 tests, seven package builds,
TypeScript lint/formatting/typing and 86 tests, documentation hooks, and web and
desktop frontend builds passed locally on macOS arm64. Rust was unavailable, so
native desktop checks, a live R2 request, packaged cross-platform behavior, and
remote CI remain unverified. See ADR-015 and the increment report.

On 2026-09-15, source onboarding documentation was expanded with explicit
prerequisites, `.env` loading semantics, complete configuration meanings,
provider and runtime recipes, build outputs, and troubleshooting. Python lint,
formatting, strict typing, 285 tests, seven Python package builds, TypeScript
lint/formatting/typing and 86 tests, web/desktop frontend builds, configuration
tests, documentation hooks, and a daemon-served web smoke test passed locally on
macOS arm64. `pnpm check:all` could not complete because Rust was not installed in
the verification environment, so native Rust checks, sidecar/installer builds,
and remote CI remain unverified for this maintenance change. No product phase or
runtime behavior changed.

On 2026-09-14, remaining legacy product identifiers were standardized on
Soulmate across runtime defaults, packaging, tests, configuration, and
documentation. `pnpm check:all` passed locally on macOS arm64; remote CI remains
unverified. This maintenance does not define or authorize a later product phase.
