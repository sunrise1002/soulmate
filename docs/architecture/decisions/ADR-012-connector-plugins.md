# ADR-012: Permissioned connector plugins outside the kernel

Status: Implemented in Phase 11.

## Context

Optional calendar, notes, email, browser, and service integrations have different
dependencies and privacy risks. Shipping their clients in the Personalization
Kernel would reverse the dependency boundary, let external systems mutate owner
state, and make every installation carry unused credentials and network code.
Connector synchronization must also remain restart-safe and deletable through the
same provenance rules as imported data.

## Decision

Define a dependency-free `soulmate-connector-sdk` package containing immutable
manifests, validated event envelopes, synchronization inputs and outputs, and a
repository protocol. Discover independently installed Python distributions through
the `soulmate.connectors` entry-point group. The daemon is the composition root;
the kernel has no dependency on the SDK or any connector.

Every manifest exactly declares data read, network access, credential access, and
RawEvent learning permissions. Registration requires the owner to grant the exact
declaration. Secrets are read from connector-specific process environment variables
only when a sync runs and are never stored in connector configuration or SQLite.
Network-enabled connectors receive a bounded HTTP client that restricts destinations
to declared hosts and applies the central privacy-mode egress policy. Offline mode
denies connector networking completely.

Run synchronization as a durable SQLite job. The daemon assigns local event IDs,
atomically persists only previously unseen external item identities, records a
cursor and sanitized status, and attaches every event to a dedicated Source.
Connectors emit RawEvents only; they cannot submit Evidence or mutate derived model
state. Removing a registration deletes its RawEvents and derivative Evidence,
advances evidence revision when necessary, and rebuilds the Personal Model.

## Consequences

Connector packages can version and release independently while the core remains
provider-neutral. Permission changes in a newly installed connector stop existing
registrations until the owner reviews them. Audits contain identifiers, counts, and
error codes rather than payloads, paths, credentials, or remote responses.

Python entry points are trusted code selected and installed by the owner; the SDK is
not a sandbox and cannot prevent a malicious package from bypassing its context.
Only reviewed connector packages should be installed. The current release supports
one registration per connector type, manual synchronization, environment-provided
credentials, and cooperative in-process plugins. Package signing, an isolated
plugin host, scheduled sync, richer credential-store integration, and a public
connector registry require later authorization.
