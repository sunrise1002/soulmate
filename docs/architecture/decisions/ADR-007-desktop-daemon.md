# ADR-007: Desktop daemon model

Status: Accepted for architecture; desktop implementation starts in Phase 6.

## Context

Non-technical owners should install an app without installing Python, Node, or a
database service; multiple clients should share one model (sections 37–44).

## Decision

Run the kernel in a local Python daemon. Eventually package it as a platform-specific
sidecar managed by a Tauri 2 desktop shell with React/TypeScript UI. Mobile and web
remain clients of the same service. Begin with a development CLI and loopback
binding; secure LAN pairing arrives in Phase 7.

## Consequences

Daemon lifecycle, packaging, updates, and compatibility need platform tests in
later phases. Client scaffolds remain placeholders until the kernel and Decision
MVP have a working testable loop. No Tauri or mobile dependencies are needed yet.
