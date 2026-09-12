# ADR-007: Desktop daemon model

Status: Implemented in Phase 6.

## Context

Non-technical owners should install an app without installing Python, Node, or a
database service; multiple clients should share one model (sections 37–44).

## Decision

Run the kernel in a local Python daemon. Package it as a platform-specific
PyInstaller sidecar managed by a Tauri 2 desktop shell with a React/TypeScript UI.
The shell starts and stops the daemon, polls health, retains a bounded log tail,
stores provider secrets in the operating system credential store, and proxies a
fixed loopback API surface to the webview. Mobile and web remain clients of the
same service. Secure LAN pairing remains deferred to Phase 7.

## Consequences

The release pipeline must build the sidecar and installer natively on macOS,
Windows, and Linux because PyInstaller is not a cross-compiler. Signing,
notarization, updates, and broad platform compatibility testing require later
release work. The loopback proxy and provider URL validation are part of the
desktop trust boundary and must remain narrow. Mobile dependencies are still not
needed.
