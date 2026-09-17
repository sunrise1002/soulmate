# Owner-authorized increment report — Encrypted remote backup

## Authorization and scope

The owner explicitly authorized this cross-phase portability increment on
2026-09-16. It does not implement Phase 13 or define Phase 14. Scope is limited to
keeping SQLite local while adding optional encrypted off-device backup, daily and
manual triggers, and fresh-machine recovery from the newest remote archive.

The owner additionally required an open-source-friendly design that does not bind
Soulmate to R2. Local-only remains the default, R2 is represented as one
S3-compatible endpoint, and alternative providers depend on a storage port rather
than changing the Personalization Kernel or archive format.

## Implementation plan

1. Reuse the consistent sanitized Phase 10 archive and encrypt it before egress.
2. Add a daemon-owned `RemoteBackupStore` port and an S3-compatible adapter.
3. Add opt-in typed configuration with environment-only secrets and central
   privacy-mode enforcement.
4. Reuse the durable SQLite job worker for interval-based automatic backup.
5. Add manual upload, status, and latest fresh-install restore through CLI, REST,
   typed SDK, and desktop surfaces.
6. Verify encryption, adapter behavior, restart scheduling, authorization,
   portability, configuration, and offline tests; document limitations.

## Delivered work

| Area | Result |
| --- | --- |
| Local default | `remote_backup.backend` defaults to `disabled`; the primary store remains local SQLite |
| Provider boundary | `RemoteBackupStore` separates archive orchestration from providers; the included adapter uses the S3 protocol rather than an R2-specific API |
| Encryption | Every remote object is a credential-free `.dtw` archive encrypted locally with the existing scrypt and AES-256-GCM format |
| Manual operation | CLI, owner-only REST, typed SDK, and desktop actions create an immediate encrypted upload |
| Automatic operation | An opt-in durable job is enqueued immediately when no prior run exists and then once per configured interval, defaulting to 24 hours |
| Machine handoff | CLI/API download the newest remote version and reuse fresh-install validation, migration, new installation identity, and deterministic model rebuild |
| Privacy | External storage requires explicit hybrid mode and HTTPS; loopback S3-compatible storage remains possible under strict-local mode |
| Secrets | Archive passphrase, access identifier, and secret key are rejected in TOML; daemon/CLI accepts process environment overrides and Desktop uses the operating-system credential store |
| Product surface | Desktop Settings configures an R2/S3-compatible endpoint, private bucket, secure credentials, encryption passphrase, and schedule; Data & Privacy reports status/last success and offers Upload now and Restore latest controls |
| Architecture | ADR-015 records local SQLite ownership, pre-egress encryption, provider neutrality, and non-merge semantics; ADR-014 remains reserved for Phase 13 |

No persistent schema migration was required. Durable scheduling uses the existing
jobs table and system metadata repository.

## Test perspectives

| Case | Perspective | Result |
| --- | --- | --- |
| Remote archive content | Confidentiality | Upload source begins with the authenticated encrypted archive magic; no plaintext `.dtwb` is sent |
| Storage replacement | Portability | An in-memory adapter exercises create/upload/latest/download without provider code |
| S3 compatibility | Adapter | Versioned object keys, pagination, `.dtw` filtering, latest selection, metadata, and bounded download are tested with a deterministic client |
| Daily schedule | Restart safety | First start enqueues/uploads once; restart inside 24 hours does not create a duplicate |
| Fresh machine | Recovery | New installation downloads, stages, restarts, migrates, and serves restored imported data |
| Privacy mode | Egress | External S3-compatible endpoint is denied until hybrid mode is explicit |
| Configuration | Secret handling | Missing settings, invalid scheduling, and TOML secrets fail without disclosing secret values |
| Authorization | Owner boundary | Paired devices cannot call remote backup or latest-restore operations |
| Default CLI | Local-first | Both remote commands report disabled without configuration and emit no traceback |

## Verification

Local verification on macOS arm64 with Python 3.12.14, Node.js 24.19.0, and pnpm
11.21.0:

| Gate | Result |
| --- | --- |
| Frozen lockfiles | Passed |
| Ruff lint and formatting | Passed |
| Strict mypy | Passed; 116 source files checked |
| Python unit, integration, and evaluation tests | Passed; 302 tests with 7 upstream/deprecation warnings |
| TypeScript lint, formatting, and strict typing | Passed across desktop, SDK, web, and mobile |
| TypeScript tests | Passed; 87 tests |
| Repository hooks | Passed |
| Python package builds | Passed; seven packages |
| Web and desktop frontend production builds | Passed |
| Native Rust desktop checks | Passed; formatting, Clippy with warnings denied, and six tests on macOS arm64 |
| Live R2 request | Not run; no owner credentials or bucket were available and tests must remain offline |
| Remote CI | Unconfirmed |

## Known limitations and handoff

- This is versioned backup/restore, not live or bidirectional database sync. Only
  one installation should write at a time; moving machines requires a final
  upload followed by restore into a fresh target.
- Losing the owner-held passphrase makes all remote archives unrecoverable.
- Soulmate does not create buckets, delete remote versions, or impose retention;
  owners should configure private-bucket lifecycle rules.
- Automatic work occurs only while the daemon runs. An overdue backup is enqueued
  at the next start. A failed job retries three times through the current durable
  worker, then becomes eligible for a new scheduled job after the interval.
- Encrypted local copies are retained under `DATA_DIR/backups`; automatic pruning
  is not implemented.
- The Phase 10 512 MiB archive bound and fresh-install-only restore rule remain.
- The desktop proxy now uses a 75-second request timeout so model requests can
  finish before the local bridge gives up; larger or slower remote transfers
  should still use the CLI.
- Desktop users can configure remote backup without a terminal. Secrets are
  write-only from the UI and remain in the operating-system credential store;
  daemon/CLI deployments continue to use process environment variables.
- Real R2 interoperability, large archives, packaged cross-platform behavior, and
  remote CI remain unverified.

Phase 13 remains planned and unstarted. This increment does not authorize or
implement Decision I/O, trusted provenance, later agent integrations, or database
merge/conflict resolution.
