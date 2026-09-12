# ADR-008: REST and MCP external integration

Status: Implemented in Phase 9.

## Context

Clients and external agents need access to personal decision intelligence without
receiving the owner's full database (specification sections 33, 45–50).

## Decision

Expose versioned REST under `/v1` and a stdio MCP adapter backed by the same daemon
application services. Give external services separate identities, independently
revocable hash-only credentials, explicit minimal permission scopes, and local
metadata-only auditing. External intelligence responses omit raw evidence,
memories, outcome notes, and stored credentials. Raw-memory access and delegated
actions require future, distinct permissions.

## Consequences

Transports remain replaceable without changing the kernel. MCP runs over local
stdio and uses a scoped API key to call the daemon, so the adapter never opens the
database. API/MCP schemas require versioning and validation. Remote MCP transport
is deferred. Delegated action policies belong to Phase 12 after prediction and
calibration are reliable; protocol access alone grants no autonomy.
