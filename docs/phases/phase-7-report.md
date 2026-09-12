# Phase 7 report — Mobile/Web Clients & Secure Pairing

## Authorization and scope

Phase 7 was explicitly authorized on 2026-09-12. Work is limited to specification
tasks P7-01 through P7-07. Active learning, outcome and regret tracking, Advise Me,
MCP, remote internet exposure, installer signing, and automatic updates are not
authorized.

## Implementation plan

1. Add pairing tokens, paired devices, and their ports to the kernel with rules
   that are testable without a database or network.
2. Persist both through a new SQLite migration that keeps only hashed secrets.
3. Generate and renew a self-signed service certificate and resolve an explicit
   LAN address, never a wildcard.
4. Put one authorization boundary in front of every route and keep device
   management owner-only.
5. Expose pairing, device, session, and LAN status endpoints.
6. Serve a web client from the daemon and share one typed SDK with mobile.
7. Add a React Native client that scans the pairing QR code and pins the service.
8. Give the desktop shell a Devices screen for LAN access, pairing, and revocation.

## Delivered work

| Task | Result |
| --- | --- |
| P7-01 Web client | `@soulmate/web` React client with Connect, Chat, Decide, My Model, and History, built into the daemon package and served from the service root |
| P7-02 LAN mode | `network.lan_enabled` configuration, `SOULMATE_NETWORK__*` overrides, and a desktop toggle that restarts the service; wildcard binds are rejected by configuration and by the resolver |
| P7-03 Local TLS | Self-signed P-256 certificate with loopback and LAN subject names, `0600` private key, renewal inside a seven-day margin, and a `sha256:` fingerprint |
| P7-04 Pairing | One-time, five-minute, 256-bit pairing token created by the owner; QR deep link carries service URL, service identity, and fingerprint; the token is claimed atomically so it can never be redeemed twice |
| P7-05 Device credentials | Paired devices stored as hashes with last-contact timestamps, listed and revoked from the owner's machine, with audit events for issue, pair, and revoke |
| P7-06 Mobile client | `@soulmate/mobile` Expo React Native app with Connect (QR scan), Chat, Decide, My Model, and History, storing its credential in the OS secure store |
| P7-07 Certificate pinning | The phone stores the scanned fingerprint and service identity, verifies the identity before reading personal data, refuses any request to another origin, and refuses plaintext |

The daemon keeps its loopback plaintext listener for the desktop shell and adds a
second TLS listener only when LAN access is enabled. Both listeners share one
application instance and one database connection; the loopback listener owns the
lifespan and the process owns signal handling so every listener stops together.

`authorize` is the only place that decides access. Loopback callers are the owner.
Every other caller needs LAN access enabled plus a bearer credential; health and
pairing completion are the only public API paths; pairing start, device listing,
revocation, LAN status, and evidence deletion are owner-only. A paired device may
chat, decide, resolve, read its model, and record corrections.

`@soulmate/sdk` holds the typed REST client and the pairing payload rules shared by
the web and mobile clients, so neither can drift from the daemon contract.

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result | Notes |
| --- | --- | --- | --- | --- |
| P7-T01 | Owner issues a pairing token | Normal | Only the hash is stored; expiry is now + TTL | `test_device_pairing.py` |
| P7-T02 | Valid token, trimmed device name | Normal | Device created, token consumed, credential returned | |
| P7-T03 | Token replayed | Abnormal | `PairingError`, no second device | |
| P7-T04 | Storage cannot claim the token | External dependency failure | `PairingError`, no device created | Simulated race |
| P7-T05 | Redeem at TTL−1µs / TTL / TTL+1s | Boundary | Accepted / expired / expired | |
| P7-T06 | Empty, unknown, and 200-character tokens | Abnormal, boundary | `PairingError` with "invalid" | |
| P7-T07 | Token belonging to another profile | Abnormal | `PairingError` | |
| P7-T08 | Empty and whitespace device names | Boundary, empty | `PairingError` naming the field | |
| P7-T09 | Valid credential | Normal | Device returned and last contact recorded | |
| P7-T10 | `""`, `no-separator`, `.secret`, `device.`, `.` | Invalid format | `PairingError` | |
| P7-T11 | Unknown device id and wrong secret | Abnormal | `PairingError`, identical message | |
| P7-T12 | Revoked device | Abnormal | `PairingError`, revocation is idempotent | |
| P7-T13 | Unknown and foreign device revoked | Abnormal | `KeyError` | |
| P7-T14 | TTL of 0 and −1s | Boundary | `ValueError` | |
| P7-T15 | Certificate generation | Normal | Key mode `0600`, 64-hex fingerprint, expiry at lifetime | `test_service_certificate.py` |
| P7-T16 | Restart within lifetime | Normal | Fingerprint unchanged so pins keep working | |
| P7-T17 | Lifetime − margin ± 1 minute, lifetime + 1 day | Boundary | Renewal only inside the margin | |
| P7-T18 | LAN address changed | Abnormal | New certificate covering the new address | |
| P7-T19 | Missing key, empty and corrupt certificate | Abnormal | Regenerated silently | |
| P7-T20 | Loopback, `::1`, `[::1]`, `localhost`, IPv4-mapped | Normal | Treated as the owner | `test_access_boundary.py` |
| P7-T21 | `None`, `""`, LAN and external hosts | Abnormal, NULL | Not the owner | |
| P7-T22 | Every route class | Equivalence | Public, device, and owner classification | |
| P7-T23 | `/v1/devices-summary` | Boundary | Prefix match does not capture it | |
| P7-T24 | Remote request while LAN is off | Abnormal | 403 for every path | |
| P7-T25 | Paired device on owner-only routes | Abnormal | 403 | |
| P7-T26 | Missing, wrong-scheme, and empty bearer headers | Invalid format, empty | 401 | |
| P7-T27 | Unrecognized credential | Abnormal | 401 with a generic message | |
| P7-T28 | Wildcard and loopback LAN hosts | Abnormal | `NetworkConfigurationError` | |
| P7-T29 | Default configuration | Normal | LAN off, port 7433, TLS under the data directory | `test_config.py` |
| P7-T30 | `0.0.0.0`, `::`, `[::]`, `*` in TOML | Abnormal | Configuration error naming the field | |
| P7-T31 | Pairing TTL 29 / 0 / −1 / 3601 seconds | Boundary | Rejected | |
| P7-T32 | Pairing TTL 30 / 300 / 3600 seconds | Boundary | Accepted | |
| P7-T33 | Full pair, use, revoke flow over the API | Normal | Device reads the model, then loses access | `test_device_access.py` |
| P7-T34 | Database inspected after pairing | Security | Neither token nor credential appears in the file | |
| P7-T35 | Wrong, short, nameless, and missing-token pairing bodies | Abnormal | 401 or 422 and no device enrolled | |
| P7-T36 | Unpaired device on the network | Abnormal | 401 for personal data, 200 for health only | |
| P7-T37 | Service restart | Normal | Device credential still works | |
| P7-T38 | Web bundle present and absent | Normal, abnormal | Served at the root, or 404 with the API intact | |
| P7-T39 | Loopback and LAN listener configuration | Normal | Loopback has no TLS; LAN has TLS and `lifespan=off` | `test_serve_listeners.py` |
| P7-T40 | LAN preparation fails | External dependency failure | Loopback still serves | |
| P7-T41 | QR payload round trip | Normal | Every pinned field survives | `sdk` and `mobile` suites |
| P7-T42 | Damaged, foreign, versioned, and incomplete QR data | Abnormal, invalid format | Named, user-readable failures | |
| P7-T43 | Plaintext service URL and malformed fingerprints in QR data | Abnormal | Pairing refused | |
| P7-T44 | Expiry at −1s / exact / +1s and unparseable | Boundary, invalid format | Treated as expired from the expiry instant | |
| P7-T45 | Fingerprint or service identity changed during pairing | Abnormal | Connection not stored | |
| P7-T46 | Requests to another origin, port, or scheme | Abnormal | Rejected before any credential is sent | |
| P7-T47 | 401, 403, 404, 503, and detail-less error bodies | Abnormal | Typed errors; only 401/403 request re-pairing | |
| P7-T48 | Transport failure | External dependency failure | Original error surfaces | |
| P7-T49 | Damaged stored credentials on web and mobile | Abnormal, invalid format | Treated as unpaired | |
| P7-T50 | Settings saved before Phase 7 | Backward compatibility | LAN stays off | Rust suite |

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24, pnpm 11.21.0,
and Rust:

| Check | Result |
| --- | --- |
| Locked Ruff lint and formatting | Passed; 122 Python files |
| Strict mypy | Passed; 72 source files |
| Python unit, integration, and evaluation tests | Passed; 220 total with two unchanged upstream warnings |
| SDK, web, mobile, and desktop ESLint, Prettier, and TypeScript | Passed |
| SDK, web, mobile, and desktop tests | Passed; 81 client tests |
| Rust formatting, Clippy with warnings denied, native shell tests | Passed; 4 tests |
| Python package builds | Passed |
| Web client production build | Passed |
| PyInstaller daemon sidecar with the bundled web client | Passed; macOS arm64 |
| Packaged sidecar end-to-end LAN run | Passed; see below |
| Frozen lockfiles and all repository hooks | Passed |

The packaged sidecar was exercised manually on a real network: the loopback
listener served the desktop API and the web client, the TLS listener answered on
`https://192.168.1.12:7790` with the reported fingerprint, an unauthenticated LAN
request received 401, pairing over TLS returned a working device credential,
`/v1/session` identified the device, and revocation from loopback made the next
device request fail with 401.

Local results do not imply remote GitHub Actions passed.

## Known issues and limitations

- The service certificate is self-signed, so a browser shows a warning until the
  owner accepts it. There is no local certificate authority and no trust store
  installation.
- Mobile transport-level certificate pinning requires a native network security
  configuration generated from the stored fingerprint during `expo prebuild`. The
  app enforces origin, scheme, and service-identity pinning at the application
  layer; the native build was not produced or verified here.
- Mobile screens were typechecked and linted but not rendered. Only the pairing,
  transport, and storage rules have automated tests; no iOS or Android build,
  device run, or camera permission flow was exercised.
- Enabling or disabling LAN access is a startup decision and restarts the service.
  There is no runtime toggle inside a running daemon.
- Pairing tokens are unguessable and single-use, but there is no per-address rate
  limit or lockout on repeated pairing attempts.
- The LAN listener uses a fixed second port. If that port is taken, LAN access
  fails and the loopback service continues without it.
- `pairing_tokens.device_id` is provenance only and carries no foreign key,
  because the token is claimed before the device row exists.
- Windows and Linux sidecars, installers, and the remote CI matrix remain
  unverified, as in Phase 6. Installers are still unsigned.
- Real Ollama and remote OpenAI-compatible inference were again not exercised.

## Phase 8 handoff

Phase 7 exit criteria pass locally: the owner can install Soulmate, enable access
from other devices, pair a phone or browser with a scanned or typed one-time code,
communicate over TLS on the LAN, revoke that device from the desktop, and keep all
Personal Model data on their own machine.

Phase 8 may begin only after explicit authorization. Active learning and outcome
intelligence must not weaken the authorization boundary, the owner-only device
controls, or evidence provenance.
