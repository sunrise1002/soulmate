# `@soulmate/mobile`

Expo React Native client for the local Soulmate service. The phone is only a
client: the Personal Model never leaves the owner's computer.

Screens: Connect (QR scan), Chat, Decide, My Model, and History.

Pairing scans the QR code shown by the desktop Devices screen, validates the
invitation before any network call, redeems it over TLS, and stores the credential
with the pinned service identity and certificate fingerprint in the operating
system secure store. Every later request is restricted to that origin and scheme,
and the service identity is re-checked before personal data is displayed.

```bash
pnpm --filter @soulmate/mobile start   # Expo development server
pnpm --filter @soulmate/mobile check   # lint, format, typecheck, test
```

Transport-level certificate pinning is installed by the native network security
configuration produced during `expo prebuild` from the stored fingerprint. That
native build is not produced by the repository checks; the automated tests cover
the pairing, transport, and storage rules.
