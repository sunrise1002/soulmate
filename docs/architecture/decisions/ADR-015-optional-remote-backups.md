# ADR-015: Optional encrypted remote backups behind a storage port

Status: Implemented as an owner-authorized cross-phase increment.

ADR-014 remains reserved for the planned Phase 13 trusted-provenance decision.

## Context

SQLite must remain the zero-configuration primary store, but an owner may want
automatic off-device recovery and a safe way to continue on a replacement
machine. Binding portability directly to Cloudflare R2 would make an open-source,
self-hosted project unnecessarily vendor-specific. Copying the live WAL database
to a network filesystem would also weaken SQLite consistency guarantees.

## Decision

Keep the live SQLite database and all database access local. Create a sanitized
portable archive using the existing SQLite online-backup boundary, encrypt and
authenticate the complete archive locally as `.dtw`, and only then send the
ciphertext to a `RemoteBackupStore` port owned by the daemon.

Ship one S3-compatible adapter. R2 is configured as an endpoint rather than
encoded as a product-specific backend, so AWS S3, Backblaze B2 S3, MinIO, and
compatible private stores can reuse it. Other protocols can implement the same
port without changing archive creation, scheduling, or restore validation.

Remote backup is disabled by default. External HTTPS storage requires explicit
`hybrid` privacy mode and complete credentials and passphrase. Daemon and CLI
deployments supply secrets through the process environment; Desktop stores them
in the operating-system credential store and passes them only to its managed
daemon. Automatic backup uses the existing durable job repository, records only
operational timestamps locally, and defaults to a 24-hour interval. Manual CLI,
owner-only REST, typed SDK, and desktop operations use the same service.

Restore downloads the newest versioned encrypted object and reuses the existing
fresh-install-only restore path. It does not merge databases, synchronize live
SQLite files, or support concurrent writers.

## Consequences

Local-only installations gain no network activity and preserve their current
behavior. Remote providers receive only encrypted credential-free archives and
object metadata, never a live SQLite file or the archive passphrase. Owners must
retain the passphrase separately; losing it makes every remote archive
unrecoverable.

The bucket must already exist and remain private. Retention and deletion are
provider policy, allowing self-hosters to choose their own lifecycle rules.
Moving to another machine is an explicit handoff: stop writing on the old
installation, create a final backup, restore into a fresh installation, and then
continue on the new machine. Bidirectional synchronization and conflict resolution
remain intentionally unsupported.
