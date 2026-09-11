# LLM providers

This package owns the provider-neutral generation protocol, deterministic fake,
central egress policy, and HTTP adapters for Ollama and OpenAI-compatible chat
completion endpoints. It does not belong to the Personalization Kernel.

Every HTTP request is checked immediately before sending. `strict_local` and
`offline` permit loopback model endpoints only. `hybrid` additionally permits
external HTTPS endpoints; plaintext external HTTP is always denied. Provider
errors intentionally omit prompts, response bodies, credentials, and endpoint
details.

Structured output is decoded by the adapter and validated by the daemon's Pydantic
extraction boundary before any Evidence is stored. The fake provider performs no
I/O and is used by the test suite.
