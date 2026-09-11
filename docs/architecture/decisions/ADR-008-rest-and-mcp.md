# ADR-008: REST and MCP external integration

Status: Accepted; Phase 1 health/system REST is implemented, MCP remains Phase 9.

## Context

Clients and external agents need access to personal decision intelligence without
receiving the owner's full database (specification sections 33, 45–50).

## Decision

Expose versioned REST under `/v1` and a later MCP adapter backed by the same
application services. Give external services separate identities, revocable
credentials, minimal permission scopes, and local auditing. Raw-memory access and
delegated actions require distinct permissions.

## Consequences

Transports remain replaceable without changing the kernel. API/MCP schemas require
versioning and validation. Delegated action policies belong to Phase 12 after
prediction and calibration are reliable; protocol access alone grants no autonomy.
