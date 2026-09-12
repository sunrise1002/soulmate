# Architecture

Soulmate is a local-first modular monolith with inward dependencies:

```text
Clients / REST / MCP
             |
Daemon composition root + adapters
             |
Core application services and ports
             |
Core domain and deterministic algorithms
```

The Personalization Kernel is independent of agent runtimes and infrastructure.
Its future evidence pipeline is `RawEvent -> Evidence -> derived Personal Model
-> versioned snapshot`. Predictions record the version used. Conversation is an
input channel; it is not the authoritative model.

Phase 1 added infrastructure-independent base records and repository ports to
`soulmate-core`; SQLAlchemy models, repositories, and packaged Alembic migrations
live in `soulmate-storage-sqlite`. The daemon composes that adapter with the
FastAPI lifecycle, installation bootstrap, local diagnostics, and durable worker.
Phase 3 added conversation and message ports to the kernel, deterministic minimal
context compilation, and concrete provider adapters outside the kernel. The daemon
owns prompts, Pydantic proposal validation, review policy, and composition. Model
providers can only propose Evidence; they cannot mutate derived Personal Model
state. Phase 6 packages the daemon as a platform-specific sidecar managed by the
Tauri desktop shell. The webview talks only through a fixed loopback native proxy.
Phase 7 added device pairing ports and rules to the kernel, an opt-in TLS listener
on an explicit LAN address, a single authorization boundary in front of every
route, and web and React Native clients built on a shared TypeScript SDK. Phase 8
added deterministic active learning plus outcome-aware advice while keeping
behavioral prediction and wellbeing recommendation as separate versioned models.
Phase 9 added service identity and API-credential ports, SQLite adapters, scoped
external REST operations, metadata-only request auditing, and a stdio MCP adapter
that consults the daemon without reading local persistence directly. The Python
SDK remains a documented placeholder. Phase 10 added source-linked import
provenance, consistent sanitized SQLite snapshots, authenticated encrypted
archives, fresh-install restore, forward schema migration, and deterministic
model rebuilding. Archive and import orchestration remain outside the kernel;
provider-neutral parsing and repository contracts point inward.
Phase 11 adds a separate dependency-free connector SDK, independently installed
Python entry-point discovery, explicit owner consent, durable sync orchestration,
and source-linked RawEvent ingestion. The SQLite adapter persists connector state,
but the Personalization Kernel does not import the SDK or any plugin. See ADR-012.

ADRs below record decisions from specification section 65. Each ADR status states
whether the decision is architectural only or already implemented.

| ADR | Decision |
| --- | --- |
| [001](decisions/ADR-001-local-first.md) | Local-first architecture |
| [002](decisions/ADR-002-sqlite.md) | SQLite as default persistence |
| [003](decisions/ADR-003-independent-kernel.md) | Independent Personalization Kernel |
| [004](decisions/ADR-004-evidence-derived-model.md) | Evidence-based derived Personal Model |
| [005](decisions/ADR-005-provider-abstraction.md) | LLM provider abstraction |
| [006](decisions/ADR-006-no-default-telemetry.md) | No cloud telemetry by default |
| [007](decisions/ADR-007-desktop-daemon.md) | Desktop daemon model |
| [008](decisions/ADR-008-rest-and-mcp.md) | REST and MCP integration |
| [009](decisions/ADR-009-lan-pairing.md) | LAN access through owner-approved device pairing |
| [010](decisions/ADR-010-behavioral-wellbeing.md) | Separate behavioral prediction from wellbeing advice |
| [011](decisions/ADR-011-portable-archives.md) | Credential-free authenticated portable archives |
| [012](decisions/ADR-012-connector-plugins.md) | Permissioned connector plugins outside the kernel |
