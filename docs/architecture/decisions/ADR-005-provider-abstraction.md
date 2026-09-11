# ADR-005: LLM provider abstraction

Status: Accepted and implemented in Phase 3.

## Context

Users need local inference and replaceable optional external providers. LLMs are
extraction and reasoning tools, not the authoritative model (sections 28–32, 35).

## Decision

Keep generation and structured-output protocols in the infrastructure-side
`soulmate-llm-providers` package so the kernel has no LLM dependency. Add embedding
support only when a phase requires it. Place HTTP calls in adapters, validate
structured output before accepting evidence, use deterministic fake providers in
tests, and route every outbound call through a central egress policy.

`strict_local` and `offline` permit literal loopback endpoints. `hybrid` also
permits external HTTPS endpoints. Non-loopback plaintext HTTP is always denied.

## Consequences

Provider replacement does not rewrite domain logic. Context compilation minimizes
data disclosure. Privacy-mode configuration alone is insufficient: adapters must
enforce policy. No provider SDK or inference runtime is installed in Phase 0.
