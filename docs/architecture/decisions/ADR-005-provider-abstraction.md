# ADR-005: LLM provider abstraction

Status: Accepted for architecture; provider adapters start in Phase 3.

## Context

Users need local inference and replaceable optional external providers. LLMs are
extraction and reasoning tools, not the authoritative model (sections 28–32, 35).

## Decision

Introduce core-facing provider ports for generation, structured output, and
embeddings when required. Place provider SDK calls in adapters. Validate structured
output before accepting evidence. Use deterministic fake providers in tests and
route outbound calls through a central egress policy respecting privacy mode.

## Consequences

Provider replacement does not rewrite domain logic. Context compilation minimizes
data disclosure. Privacy-mode configuration alone is insufficient: adapters must
enforce policy. No provider SDK or inference runtime is installed in Phase 0.
