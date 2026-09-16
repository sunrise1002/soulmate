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
evidence deletion, outcome deletion, import, backup, export, restore, and imported
source deletion are owner-only. Removing an outcome also removes its source event
and invalidates advice that may have used it.

Pairing tokens are 256-bit, single-use, and expire in five minutes; they are
claimed atomically so a token can never be redeemed twice. Only hashes of pairing
tokens and device credentials are stored, and failed authentication returns one
generic message. Revocation takes effect on the next request. Pairing token issue,
device pairing, and revocation are recorded as audit events.

External applications use a separate service-identity boundary even on loopback;
they never inherit owner authority. Each identity has explicit scopes and one or
more independently revocable high-entropy API keys. Only SHA-256 hashes of API-key
secrets are stored. The usable key is shown once, authentication failures remain
generic, and scope or revocation changes apply on the next request. External
responses omit raw memories, evidence, outcome history, and notes. Every external request
adds a local audit event containing identity, credential identifier, method, path,
and status only—never the key or request payload.

Backups use SQLite's online backup operation so committed WAL data is captured.
Every archive removes pairing tokens, paired-device credentials, API credentials,
and installation identity while preserving service identities and local audit
history. TLS private keys, provider secrets, logs, configuration, and existing
backups are excluded. Portable `.dtw` archives use scrypt key derivation and
AES-256-GCM authenticated encryption. Restore validates archive paths, checksums,
format and database versions, refuses non-fresh installations, migrates known
schemas, and rebuilds derived state from Evidence. See ADR-011.

Optional remote backup never uploads a live database or plaintext `.dtwb` file.
It creates the same credential-free snapshot, encrypts it locally as `.dtw`, and
then sends only ciphertext through a configured storage adapter. The first
adapter uses S3-compatible private buckets. It is disabled by default, external
HTTPS requires explicit hybrid mode, and its passphrase and access credentials
must come from the process environment for daemon/CLI use or the operating-system
credential store for Desktop use. The Desktop UI receives only secret-presence
flags and injects credentials directly into its managed daemon. Remote restore
remains owner-only and fresh-install-only; it does not merge two writable
installations. See ADR-015.

Connector discovery and management are owner-only. Each plugin must declare its
data, network, credential, and learning capabilities, and registration grants must
match that declaration exactly. Connector credentials use dedicated process
environment variables and are never persisted. Network-capable plugins receive a
host-allowlisted HTTP client behind the central privacy policy; offline mode denies
all connector network calls. Connector jobs persist only sanitized status and audit
metadata. Source removal deletes connector RawEvents and derivative Evidence before
rebuilding the model. Installed Python plugins execute as trusted owner-selected
code rather than inside a security sandbox; see ADR-012.

The service certificate is self-signed and generated locally with an owner-only
private key. Browsers show a warning until the owner accepts it, and mobile
transport pinning requires a native network configuration built from the stored
fingerprint. There is no per-address rate limit on pairing attempts. Remote
internet exposure is not supported.

Do not put personal data or secrets into issue reports, logs, fixtures, source
control, or CI artifacts. Use synthetic fixtures and keep runtime data outside
tracked source. See ADR-001, ADR-005, ADR-006, ADR-008, ADR-009, ADR-010,
ADR-011, ADR-012, and ADR-015.
