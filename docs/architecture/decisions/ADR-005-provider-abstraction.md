# ADR-005: LLM provider abstraction

Status: Accepted and implemented in Phase 3; amended by the 2026-09-17 provider
compatibility maintenance increment.

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

Structured generation uses capability negotiation rather than assuming that all
models behind one HTTP shape implement the same JSON Schema dialect. Adapters
advertise ordered structured-output modes and remember the first successful mode
for the life of the configured provider instance. The OpenAI-compatible family
tries strict JSON Schema, JSON-object mode, and finally schema-guided JSON text;
Ollama tries its native schema mode and then schema-guided JSON text. Authentication,
rate-limit, and policy errors are not treated as capability mismatches.

The daemon owns a deliberately restricted portable extraction schema: no recursive
references, unconstrained JSON values, or dynamic object properties cross the
provider boundary. Adapter output remains an untrusted proposal and must pass the
same Pydantic validation and evidence-review policy regardless of the transport
strategy used.

A successful conversational response and successful learning extraction are
separate executions. Once text generation succeeds, the conversation and its
RawEvent are retained and the API returns the reply with a sanitized
pending-learning state. Extraction always continues through a durable job that
contains only profile, RawEvent, and message IDs. No failed output is accepted. A
job may update the Personal Model only after the same validation and review
boundary; retries use bounded exponential backoff and never duplicate the private
message content. Provider-specific failures must not delay or make a successful
reply appear to vanish.

## Consequences

Provider replacement does not rewrite domain logic. Context compilation minimizes
data disclosure. Privacy-mode configuration alone is insufficient: adapters must
enforce policy. No provider SDK or inference runtime is installed in Phase 0.

OpenAI-compatible endpoints cover a broad family, including hosted GPT, Gemini,
Claude compatibility, DeepSeek, GLM, Kimi, and self-hosted compatible runtimes,
without claiming identical features. Native adapter families may still be added
when a provider lacks a compatible endpoint or requires a capability unavailable
through it; doing so does not alter the kernel or evidence workflow. Prompted JSON
is a portability fallback, not a trust shortcut, and can still fail on models that
cannot reliably follow JSON instructions.
