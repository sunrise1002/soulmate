# Architecture

Soulmate is a local-first modular monolith with inward dependencies:

```text
Clients / REST / future MCP
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
Tauri desktop shell. The webview talks only through a fixed loopback native proxy;
mobile, web, MCP, and SDK directories remain documented placeholders.

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
