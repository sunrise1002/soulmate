# `@soulmate/sdk`

Typed client for the local Soulmate service, shared by the web and mobile clients
so neither can drift from the daemon contract.

- `SoulmateClient` wraps the REST surface, attaches a paired device credential as
  a bearer token, and raises `ApiError`. `requiresPairing` is true for 401 and 403
  so a client can drop a revoked credential.
- `parsePairingPayload`, `encodePairingPayload`, and `isPairingPayloadExpired`
  validate scanned QR data. A payload must use an unsupported-version check, an
  `https://` service address, and a `sha256:` fingerprint.
- `assertPinnedFingerprint` and `connectionFrom` bind a credential to the service
  identity and certificate fingerprint that were pinned during pairing.
- Active-learning, outcome, and advice methods keep the Phase 8 REST contracts
  identical across the web and mobile clients.
- External identity management and privacy-minimal Phase 9 intelligence methods
  use the same typed transport. External clients pass their service API key as the
  bearer credential and receive no raw evidence or memory payloads.
- Phase 10 data methods cover static imports, source deletion, local backup,
  encrypted export, and staged restore. The daemon permits these operations only
  for a loopback owner, even though the shared client exposes their types.

The transport is injectable, so callers can wrap it. The mobile client uses that
to refuse any request that leaves the paired origin.

```bash
pnpm --filter @soulmate/sdk check
```
