# Phase 10 report — Import, Backup & Portability

## Authorization and scope

Phase 10 was explicitly authorized on 2026-09-12. Work is limited to specification
tasks P10-01 through P10-06. Live connectors, cloud synchronization, model-provider
imports, and delegated decisions are not authorized.

## Implementation plan

1. Add consistent, credential-free SQLite backups that include current WAL data
   and the local object, index, and model directories when present.
2. Define and authenticate a versioned encrypted portable archive with explicit
   manifest, schema, checksum, KDF, and cipher metadata.
3. Restore only into a fresh installation, migrate known older database schemas,
   create a destination installation identity, and rebuild derived model state.
4. Normalize generic JSON, Markdown, text, ChatGPT, and Claude histories into
   source-linked conversations, messages, and RawEvents without hidden egress.
5. Delete an imported provenance source and its conversations, RawEvents, and
   derivative Evidence atomically, then rebuild the model.
6. Expose owner-only API, CLI, typed SDK, and desktop Data & Privacy workflows and
   cover migration, restart, authentication, corruption, and deletion behavior.

## Delivered work

| Task | Result |
| --- | --- |
| P10-01 Backup | `soulmate backup`, `POST /v1/data/backups`, and the desktop action use SQLite online backup for a consistent local `.dtwb` archive |
| P10-02 Restore | CLI restore and desktop staged restore accept only a fresh installation; restart applies the archive, migrates it, assigns a new installation identity, and rebuilds the model |
| P10-03 Encrypted Export | `.dtw` encrypts and authenticates the versioned ZIP payload with AES-256-GCM and a scrypt-derived key; wrong passphrases and modified archives fail generically |
| P10-04 Chat Import | Auto-detected or explicit generic JSON, Markdown, plain text, ChatGPT, and Claude exports normalize locally into source-linked conversations, messages, and RawEvents |
| P10-05 Source Deletion | Owner-only deletion atomically removes imported messages, conversations, RawEvents, and derivative Evidence, advances evidence revision when needed, and rebuilds the model |
| P10-06 Model Migration | Restore rejects unknown future schemas, upgrades known older Alembic revisions to `0008_phase_10`, and creates a current algorithm snapshot from authoritative Evidence |

Migration `0008_phase_10` adds a nullable source link to conversations so imported
conversation data follows the same provenance boundary as RawEvents and Evidence.
Existing native conversations retain a null source and are unaffected.

Every archive keeps service identities, scopes, and audit history but removes API
credentials, paired-device credentials, one-time pairing tokens, and installation
identity. TLS keys, provider secrets, logs, configuration, and prior backups are
outside the archive. After restore, the owner re-pairs devices and issues new API
keys.

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result |
| --- | --- | --- | --- |
| P10-T01 | Live WAL database | Consistency | SQLite online backup contains committed current data without copying WAL files |
| P10-T02 | Backup with service identity and API credential | Credential privacy | Identity and scopes survive; authentication credentials and installation identity do not |
| P10-T03 | Correct export passphrase | Normal | Encrypted archive authenticates and restores |
| P10-T04 | Wrong passphrase or modified ciphertext | Authentication | Restore fails without revealing archive content |
| P10-T05 | Older known schema | Migration | Restore upgrades to the current Alembic head and rebuilds a current snapshot |
| P10-T06 | Unknown format/schema or unsafe archive member | Invalid input | Restore is rejected before destination data changes |
| P10-T07 | Non-fresh destination | Ownership safety | Restore refuses to overwrite owner-created data |
| P10-T08 | Generic JSON/Markdown/text | Static import | Supported roles and Unicode content become conversations and RawEvents |
| P10-T09 | ChatGPT/Claude export | Compatibility | Common assistant structures are detected and normalized |
| P10-T10 | Unsupported, empty, or oversized import | Invalid input | Import fails atomically with no partial source |
| P10-T11 | Imported source with derivative Evidence | Provenance deletion | Source graph is removed and the rebuilt model no longer contains that belief |
| P10-T12 | Paired device calls `/v1/data/*` | Authorization | The single boundary denies every data-management operation |
| P10-T13 | Desktop backup/import/restore | Product workflow | Owner can run Phase 10 actions without a terminal |
| P10-T14 | CLI backup/export/import/restore | Operational workflow | Machine-readable commands complete without a cloud service |

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24, pnpm 11.21.0,
and the workspace Rust toolchain passed on 2026-09-12:

| Gate | Result |
| --- | --- |
| Frozen lockfiles | Passed |
| Ruff lint and formatting | Passed; 154 Python files checked |
| Strict mypy | Passed; 97 source files checked |
| Python unit and integration tests | Passed; 260 tests, with 7 upstream/deprecation warnings |
| TypeScript tests | Passed; 84 SDK, desktop, mobile, and web tests |
| Rust tests | Passed; 4 tests |
| Repository hooks | Passed |
| Python package builds | Passed; five packages |
| Web and desktop production builds | Passed |
| Clean PyInstaller sidecar build and packaged backup/export/restore smoke | Passed on macOS arm64 |

Remote GitHub Actions verification remains unconfirmed.

## Known issues and limitations

- Static history import never invokes a model provider automatically. It preserves
  conversations and RawEvents as authoritative local source material; automatic
  evidence extraction from imported history remains intentionally absent to avoid
  hidden bulk egress.
- The current archive implementation supports up to 512 MiB of uncompressed data.
  Desktop restore accepts an archive upload up to 64 MiB; larger supported
  archives use the CLI. Streaming multi-gigabyte archives are not implemented.
- Restore is intentionally fresh-install only. Merging two existing Personal
  Models, selective restore, and conflict resolution are not implemented.
- Generic JSON accepts documented role/content message structures. Provider
  exports can change, so unsupported future ChatGPT or Claude variants require a
  parser update.
- Backups are local files and are not scheduled, replicated, or synchronized.
- Remote CI, cross-platform packaged restore, native mobile builds, and a physical
  machine-to-machine transfer remain unverified.

## Phase 11 handoff

Phase 10 exit criteria pass locally: an owner can back up machine A, restore to a
fresh machine B installation, and retain the Personal Model and decision history
without a Soulmate cloud service.

Phase 11 may begin only after explicit authorization. Connector plugins must emit
RawEvents, declare data/network/credential/learning permissions, and use the same
source provenance and owner-only deletion boundary. No Phase 11 work has started.
