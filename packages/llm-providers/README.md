# LLM providers

This package owns the provider-neutral generation protocol, deterministic fake,
central egress policy, capability negotiation, and HTTP adapters for Ollama and
OpenAI-compatible chat completion endpoints. It does not belong to the
Personalization Kernel.

Every HTTP request is checked immediately before sending. `strict_local` and
`offline` permit loopback model endpoints only. `hybrid` additionally permits
external HTTPS endpoints; plaintext external HTTP is always denied. Provider
errors intentionally omit prompts, response bodies, credentials, and endpoint
details.

Structured output is decoded by the adapter and validated by the daemon's Pydantic
extraction boundary before any Evidence is stored. The fake provider performs no
I/O and is used by the test suite.

OpenAI-compatible structured generation negotiates strict JSON Schema, JSON-object
mode, then schema-guided JSON text and caches the successful mode for the provider
instance. Ollama similarly falls back from its native schema format to guided JSON.
This supports different capability subsets without vendor checks in application
code. Authentication and rate-limit failures do not trigger negotiation fallback.
