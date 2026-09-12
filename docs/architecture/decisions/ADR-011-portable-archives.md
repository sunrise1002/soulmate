# ADR-011: Credential-free authenticated portable archives

Status: Implemented in Phase 10.

## Context

The owner's Personal Model must survive machine failure and move between
installations without a Soulmate cloud service. A live SQLite database may have
uncheckpointed WAL state, while copied authentication state could let existing
devices or external API-key holders reach the restored installation.

## Decision

Create backups from SQLite's online backup API, then sanitize the snapshot before
archiving it. Preserve Personal Model data, decisions, service identities, audit
records, and local object/model/index directories. Remove installation identity,
pairing state, and API credentials from every archive. Do not include TLS private
keys, provider secrets, logs, configuration, or the backups directory.

Use a versioned ZIP payload with a JSON manifest and database checksum. Local
`.dtwb` backups retain that payload directly. Portable `.dtw` exports encrypt and
authenticate the complete payload with AES-256-GCM and derive the key from an
owner passphrase using scrypt. Restore accepts only known archive and database
schema versions, rejects unsafe paths and modified content, and targets a fresh
installation. Startup applies a staged restore, migrates the schema forward, gives
the destination a new installation identity, and deterministically rebuilds the
Personal Model from Evidence.

## Consequences

Restored devices must pair again and external agents must receive new API keys.
Service identities and their scopes remain available for the owner to review.
Archive compatibility and database migration are explicit and testable, and
derived state can adopt the current algorithm without rewriting source Evidence.
The current in-memory encryption path bounds archive payloads to 512 MiB; larger
streaming archives require a later format-compatible implementation.
