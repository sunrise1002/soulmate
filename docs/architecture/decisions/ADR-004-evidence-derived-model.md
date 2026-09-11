# ADR-004: Evidence-based derived Personal Model

Status: Accepted for architecture; model implementation starts in Phase 2.

## Context

Conversation history alone cannot represent contextual preferences, uncertainty,
contradictions, or explain why a belief exists (specification sections 5–6, 14–18,
27–28, 34).

## Decision

Normalize learning input into RawEvent and validated provenance-bearing Evidence.
Derive preferences, facts, goals, constraints, and versioned snapshots. Preserve
contradictions and record corrections as evidence. Keep rebuilding deterministic
for fixed evidence and algorithm versions. Predictions record the model version.

## Consequences

Beliefs can cite supporting evidence and be rebuilt after source deletion.
Immutable source history is preferred where practical, while user deletion must
remain possible. Extractors and connectors cannot mutate derived beliefs directly.
