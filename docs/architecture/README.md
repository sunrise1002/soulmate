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

Phase 0 supplies installable `soulmate-core` and `soulmate-daemon` packages, empty
kernel module boundaries, typed configuration, and an inert FastAPI shell. All
other app/adapter directories are documented placeholders. SQLite, repositories,
migrations, routes, identities, and workers begin in their specified phases.

ADRs below record decisions from specification section 65; acceptance of a design
does not mean its implementation has started.

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
