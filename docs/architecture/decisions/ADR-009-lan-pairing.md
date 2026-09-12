# ADR-009: LAN access through owner-approved device pairing

Status: Implemented in Phase 7.

## Context

Owners want their phone and browser to reach the Personal Model that lives on
their computer, without moving that data anywhere (sections 39–43). The daemon
binds loopback only, and everything reaching it over loopback has been treated as
the owner.

## Decision

Keep the loopback listener unchanged and add an opt-in second listener on an
explicit LAN address served over TLS with a self-signed certificate generated and
renewed by the daemon. Wildcard binds are rejected by configuration and by the
network resolver. One authorization boundary runs before every route: loopback
callers are the owner, every other caller needs LAN access enabled and a bearer
credential issued by pairing, and device management, LAN status, and evidence
deletion stay owner-only.

Pairing uses a one-time, short-lived, high-entropy token that the owner creates on
their own machine. Only hashes of the token and of the device credential are
stored, and the token is claimed atomically so it can never be redeemed twice. The
QR payload carries the service URL, service identity, and certificate fingerprint,
so a phone pins the service it paired with. Devices are listed and revoked from
the owner's machine, and revocation takes effect on the next request.

## Consequences

Clients share one typed TypeScript SDK, so the web and mobile clients cannot drift
from the daemon contract. The self-signed certificate means browsers show a
warning until the owner accepts it, and mobile transport pinning must be installed
through a native network configuration built from the stored fingerprint. LAN mode
is a startup decision: enabling or disabling it restarts the service. Remote
internet exposure stays out of scope; private networks such as a VPN remain the
documented path.
