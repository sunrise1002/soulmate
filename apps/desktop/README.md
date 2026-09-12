# Soulmate desktop

The Phase 6 desktop product is a Tauri 2 shell with a React and TypeScript UI.
It packages the Python daemon as a PyInstaller sidecar, owns the sidecar lifecycle,
and proxies only fixed loopback `/v1/` API paths from the webview.

## Development

Install the root workspace first, including Rust with `rustfmt` and `clippy`:

```sh
uv sync --locked --all-packages
pnpm install --frozen-lockfile
rustup component add rustfmt clippy
```

Run the frontend alone:

```sh
pnpm --filter @soulmate/desktop dev
```

Run the complete desktop application:

```sh
pnpm --filter @soulmate/desktop tauri dev
```

The Tauri command builds a target-suffixed daemon sidecar before starting. Data is
stored in the operating system's application-data directory. Provider settings
are stored in a local JSON file; model-provider API keys are stored separately in
the operating system credential store and are never returned to the webview.

The External Agents screen creates scoped service identities, shows each new API
key once, manages key rotation and revocation, defines exact delegated-action
policies, approves or rejects pending actions, and displays the local audit trail.
The packaged sidecar also exposes the MCP stdio adapter as `decision-twin mcp`.

The Data & Privacy screen creates consistent local backups, passphrase-encrypted
portable exports, imports static JSON/Markdown/text histories, deletes imported
sources and their derivative evidence, and stages restore into a fresh
installation. Restore restarts the managed daemon so migrations and model rebuild
run before the restored data is served. Desktop archive uploads are limited to 64
MiB; use the CLI for larger supported archives.

The Connections screen discovers independently packaged connector entry points,
shows their complete permission declarations, and requires owner approval before
configuration. The bundled Local Notes reference connector synchronizes only an
explicit directory and never uses the network. Connector removal deletes its
RawEvents and derivative Evidence before rebuilding the Personal Model.

## Verification and packaging

```sh
pnpm --filter @soulmate/desktop check
pnpm --filter @soulmate/desktop sidecar:build
pnpm --filter @soulmate/desktop tauri build
```

Packaging is native: build macOS artifacts on macOS, Windows artifacts on Windows,
and Linux artifacts on Linux. The CI matrix produces unsigned DMG, MSI/NSIS, DEB,
and AppImage artifacts. Signing, notarization, and automatic updates are not part
of Phase 6.

## Security boundary

- The daemon always binds to `127.0.0.1:7432`.
- The webview cannot choose an arbitrary proxy destination or redirect the proxy.
- Strict-local and offline modes reject non-loopback provider endpoints.
- Hybrid mode permits loopback HTTP or external HTTPS provider endpoints.
- The shell retains only a bounded daemon log tail and does not log request bodies.
- Data-management routes are owner-only and archives exclude all usable
  authentication state.
- The content security policy allows application assets and Tauri IPC only.
