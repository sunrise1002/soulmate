# ADR-006: No cloud telemetry by default

Status: Accepted; no telemetry integration exists in Phase 0.

## Context

A user-owned Personal Model contains sensitive information. Operation must not
require reporting to project infrastructure (specification sections 32, 50, 57–58).

## Decision

Ship without analytics, tracking, or remote telemetry. Keep operational and audit
logs local and avoid raw prompts, conversations, secrets, and personal payloads by
default. Any future remote diagnostics require explicit opt-in and minimization.

## Consequences

Debugging depends on local diagnostics and intentionally shared reports. Future
observability libraries must not silently enable remote exporters. Development
dependency downloads are tooling activity, not application telemetry.
