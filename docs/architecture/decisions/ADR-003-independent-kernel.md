# ADR-003: Personalization Kernel independent of agent runtime

Status: Accepted; package boundary established in Phase 0.

## Context

Agents, model providers, and user interfaces may change while the owner's Personal
Model remains the core asset (specification sections 4, 62–63, 76).

## Decision

Place domain rules, application services, deterministic algorithms, and required
ports in `soulmate-core`. Keep framework, database, provider, and client imports
outside the kernel. The daemon wires adapters to core ports. Phase 0 core has no
runtime dependencies; automated import and metadata checks enforce this baseline.

## Consequences

Core installs independently and can be tested without services or an LLM. Small
explicit interfaces are introduced when needed. Future numerical libraries may
be justified deliberately without allowing infrastructure imports into core.
