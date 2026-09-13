# Phase 11 report — Connector Ecosystem

## Authorization and scope

Phase 11 was explicitly authorized on 2026-09-12. Work is limited to the connector
SDK, plugin discovery and lifecycle, permission and egress boundaries, durable
RawEvent synchronization, one local reference connector, and owner product
surfaces. Delegated decisions, a Policy Engine, automatic external actions, cloud
synchronization, and a hosted connector registry are not authorized.

## Implementation plan

1. Define a dependency-free connector SDK with immutable manifests, validated
   event/sync records, network and credential context contracts, and Python entry
   point discovery.
2. Persist owner-approved registrations, permission/configuration snapshots,
   cursors, sanitized sync state, and external item idempotency keys in SQLite.
3. Compose connectors only in the daemon, enforce exact permission consent,
   environment-only credentials, manifest host allowlists, privacy-mode egress,
   durable jobs, local audits, and RawEvent-only ingestion.
4. Preserve source provenance so removing a connector atomically deletes its
   RawEvents and derivative Evidence before a deterministic model rebuild.
5. Ship an independently packaged, bounded, offline Local Notes connector and add
   owner-only REST, CLI discovery, typed SDK, packaged-sidecar, and desktop
   Connections workflows.
6. Cover invalid manifests/output, file boundaries, privacy denial, consent,
   idempotency, failure redaction, restart persistence, authorization, migration,
   packaging, and deletion behavior.

## Delivered work

| Area | Result |
| --- | --- |
| Connector SDK | `soulmate-connector-sdk` defines manifest, permissions, credentials, network context, event limits, synchronization, persistence protocol, and `soulmate.connectors` discovery contracts without dependencies |
| Plugin packaging | Installed Python distributions register independent entry points; `soulmate connectors` reports loaded plugins and sanitized load failures |
| Consent | Registration requires all and only the manifest's declared data-read, network, credential, and RawEvent-learning permissions; permission drift stops synchronization |
| Credentials and egress | Connector secrets come from dedicated process variables and are never persisted; network calls use a 5 MiB bounded, no-redirect, declared-host client behind the privacy policy, with all connector networking denied in offline mode |
| Durable sync | Owner requests enqueue restart-safe SQLite jobs; accepted external identities are idempotent, cursors and sanitized status persist, and audit events contain only identifiers, counts, and error codes |
| Provenance | Every accepted connector item becomes a daemon-assigned RawEvent linked to a dedicated Source; plugins cannot submit Evidence or derived model state |
| Local Notes | The independently packaged reference connector reads owner-selected UTF-8 `.md`, `.markdown`, and `.txt` files, follows no symlinks, uses no network, and enforces file/count/total size bounds |
| Product surfaces | Owner-only REST lifecycle, typed TypeScript SDK, desktop Connections screen, migration `0009_phase_11`, sidecar plugin metadata, and ADR-012 are implemented |
| Removal | Connector removal deletes its item identities, RawEvents, Source, and derivative Evidence, advances evidence revision when required, and rebuilds the Personal Model |

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result |
| --- | --- | --- | --- |
| P11-T01 | Manifest omits a capability permission | Contract | SDK rejects the inconsistent declaration |
| P11-T02 | Naive timestamp, non-JSON value, oversized event/cursor/batch | Invalid output | Connector output is rejected before persistence |
| P11-T03 | Independently installed entry point | Discovery | CLI and daemon load its manifest without a direct kernel dependency |
| P11-T04 | Missing or extra owner grants | Consent | Registration is refused |
| P11-T05 | Credential requirement | Secret boundary | Only the documented environment key is supplied at sync time; no secret is persisted or returned |
| P11-T06 | Undeclared host or offline privacy mode | Egress | Request is denied before network I/O |
| P11-T07 | Valid Local Notes directory | Normal | Bounded files become sensitive, source-linked RawEvents |
| P11-T08 | Symlink, unsupported suffix, non-UTF-8 or oversized file | Filesystem boundary | Unsafe or unsupported input is skipped or rejected without partial sync state |
| P11-T09 | Same external items synchronized twice | Idempotency | Second job succeeds without duplicate RawEvents |
| P11-T10 | Connector error contains a private path | Redaction | Registration, job, API, and audit expose only a stable error code/message |
| P11-T11 | Daemon restart after successful sync | Persistence | Registration, cursor, status, source, and RawEvents remain available |
| P11-T12 | Paired device invokes connector route | Authorization | Single boundary denies every connector-management operation |
| P11-T13 | Connector source has derivative Evidence | Provenance deletion | Removal deletes source graph and rebuilt model no longer uses the belief |
| P11-T14 | Packaged daemon sidecar | Packaging | Frozen CLI discovers and imports the bundled entry-point connector |

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24, pnpm 11.21.0,
and the workspace Rust toolchain passed on 2026-09-12:

| Gate | Result |
| --- | --- |
| Frozen lockfiles | Passed |
| Ruff lint and formatting | Passed; 169 Python files checked |
| Strict mypy | Passed; 108 source files checked |
| Python unit, integration, and evaluation tests | Passed; 274 tests, with 7 upstream/deprecation warnings |
| TypeScript tests | Passed; 85 SDK, desktop, mobile, and web tests |
| Rust tests | Passed; 4 tests |
| Repository hooks | Passed |
| Python package builds | Passed; seven packages |
| Web and desktop production builds | Passed |
| Clean PyInstaller sidecar build and packaged connector discovery smoke | Passed on macOS arm64 |

Remote GitHub Actions verification remains unconfirmed.

## Known issues and limitations

- Python connector entry points are trusted owner-installed code, not a sandbox.
  The SDK cannot prevent a malicious plugin from opening files or network clients
  outside the supplied context; only reviewed packages should be installed.
- The current lifecycle supports one registration per connector type, manual sync,
  process-environment credentials, and cooperative in-process execution. Scheduled
  sync, multiple accounts, OS credential-store management, package signing, plugin
  isolation, and a public registry are not implemented.
- Local Notes is the only shipped connector. Real calendar, notes-provider, email,
  browser, GitHub, and other network integrations remain future plugin work.
- Connector sync creates RawEvents only. It does not automatically call an LLM or
  create Evidence, avoiding hidden bulk egress; later owner-approved extraction
  workflows would need separate authorization and review.
- Packaged connector discovery was verified only on macOS arm64. Remote CI,
  Windows/Linux sidecars, third-party packages, native mobile builds, and live
  service APIs remain unverified.

## Phase 12 handoff

Phase 11 exit criteria pass locally: an independently packaged connector can be
discovered, declare its full capabilities, receive explicit owner consent,
synchronize idempotent source-linked RawEvents through a durable job, survive a
restart, and be removed with derivative Evidence and model state rebuilt.

Phase 12 may begin only after explicit authorization. Delegated actions must add a
separate Policy Engine, impact classification, confidence thresholds, agent
permissions, and owner approval workflows. No Phase 12 work has started.
