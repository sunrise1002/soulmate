# Privacy and security boundaries

The daemon binds loopback by default and includes no telemetry. Configuration error
messages identify fields without printing their rejected values.

Persistence and audit logs stay local, provider secrets live in the operating-system
credential store, provider output is validated, and network egress passes a central
policy.

Access from other devices is off until the owner enables it. When enabled, the
daemon keeps its loopback listener and adds a TLS listener on one explicit address;
wildcard binds are rejected. Every request passes one authorization boundary before
any handler sees personal data: loopback callers are the owner, and every other
caller needs a bearer credential issued by pairing. Health and pairing completion
are the only public API paths. Pairing, device listing, revocation, network status,
evidence deletion, and outcome deletion are owner-only. Removing an outcome also
removes its source event and invalidates advice that may have used it.

Pairing tokens are 256-bit, single-use, and expire in five minutes; they are
claimed atomically so a token can never be redeemed twice. Only hashes of pairing
tokens and device credentials are stored, and failed authentication returns one
generic message. Revocation takes effect on the next request. Pairing token issue,
device pairing, and revocation are recorded as audit events.

The service certificate is self-signed and generated locally with an owner-only
private key. Browsers show a warning until the owner accepts it, and mobile
transport pinning requires a native network configuration built from the stored
fingerprint. There is no per-address rate limit on pairing attempts. Remote
internet exposure is not supported.

Do not put personal data or secrets into issue reports, logs, fixtures, source
control, or CI artifacts. Use synthetic fixtures and keep runtime data outside
tracked source. See ADR-001, ADR-005, ADR-006, ADR-008, ADR-009, and ADR-010.
