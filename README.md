# Soulmate

A local-first, self-hosted **Personal Decision Model**. Its goal is not to be the
smartest general-purpose agent, but to understand one specific person as
accurately as possible — and to keep that understanding on that person's own
machine. The owner controls the data; agents, LLM providers, and clients are
replaceable.

There is no Soulmate cloud. Each owner runs their own service.

📖 **[Read the project guide → `docs/index.html`](docs/index.html)** ([Tiếng Việt](docs/index.vi.html)) — vision,
architecture, technology, setup, usage, API, and privacy boundaries in one page.

**Current status:** Phases 0–12 are complete locally; Phase 12 is the Delegated
Decision Agent. See [phase status](docs/phase-status.md) and the
[Phase 12 report](docs/phases/phase-12-report.md). Remote CI remains unverified.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24,
pnpm 11.21.0, and Rust 1.88 or later. `uv` manages the Python 3.12 development
interpreter; Python packages support Python 3.12 and later.

```sh
# if uv is in ~/.local/bin and your shell cannot find it
export PATH="$HOME/.local/bin:$PATH"

uv sync --locked --all-packages
pnpm install --frozen-lockfile
uv run --locked pre-commit install

pnpm check    # lint, format check, typecheck, and tests across Python, TS, and Rust
```

Your editor's Git environment also needs `uv` on PATH for the pre-commit hook.

Run the service:

```sh
uv run --locked soulmate serve
```

It listens on `127.0.0.1:7432`, applies packaged Alembic migrations, creates
`DATA_DIR/soulmate.db`, and starts the durable local job worker. It enables
no telemetry; model calls happen only when `/v1/chat` is used and must pass the
configured egress policy.

Run the desktop product, or build a native installer with its bundled daemon
sidecar:

```sh
rustup component add rustfmt clippy
pnpm --filter @soulmate/desktop tauri dev
pnpm --filter @soulmate/desktop tauri build
```

The installed application starts and monitors its own loopback daemon, stores data
in the platform application-data directory, and needs no separately installed
Python, Node.js, database, or Docker runtime.

Optionally copy `config.example.toml` to `config.toml` and edit it; local config is
git-ignored. See the [configuration reference](docs/contributor-guide/configuration.md)
for environment overrides, `DATA_DIR`, and path semantics.

## CLI

```sh
uv run --locked soulmate <command>
```

| Command | Purpose |
| --- | --- |
| `serve` | Start the local daemon |
| `status` | Query `/v1/health` and `/v1/system/info` of a running daemon |
| `doctor` | Check storage, integrity, WAL, migrations, port, and provider readiness |
| `rebuild-model` | Deterministically rebuild derived state from stored evidence |
| `evaluate` | Run the packaged synthetic decision evaluation, offline |
| `import PATH` | Import JSON, Markdown, text, ChatGPT, or Claude history |
| `backup` / `export` | Write a local `.dtwb` or encrypted `.dtw` archive |
| `restore ARCHIVE` | Restore into a fresh installation while the daemon is stopped |
| `connectors` | List installed connector plugins |
| `mcp` | Run the scoped stdio MCP adapter |

`status` and `doctor` emit machine-readable JSON and exit nonzero when their
required checks fail.

## Access from other devices

Off until you turn it on. When enabled, the daemon keeps its loopback listener and
adds a TLS listener on one explicit local network address; wildcard binds are
rejected. Enable it from the desktop Devices screen, or set `network.lan_enabled`.

Pairing uses a one-time code that expires in five minutes. Only hashes of the
pairing token and the issued device credential are stored, and the QR payload
carries the certificate fingerprint so a phone pins the service it paired with.
The certificate is self-signed, so a browser warns the first time. Remote internet
exposure is out of scope; use a VPN if you need access away from home.

Loopback callers are the owner. Every other caller needs an active device
credential, and external applications always need a service API key — including on
loopback. Device and data management stay on the owner's machine.

## Repository map

| Path | Responsibility |
| --- | --- |
| `packages/core-python/src/soulmate_core/` | Personalization Kernel: infrastructure-independent entities, ports, and deterministic algorithms |
| `packages/storage-sqlite/` | SQLAlchemy adapter and packaged Alembic migrations |
| `packages/llm-providers/` | Provider protocol, egress policy, fake, Ollama, and OpenAI-compatible adapters |
| `packages/connector-sdk/` | Stable permission manifest, event, sync, discovery, and persistence contracts |
| `packages/connectors-local/` | Independently packaged Local Notes reference connector |
| `packages/sdk-typescript/` | Typed REST client and pairing rules shared by clients |
| `packages/sdk-python/` | Reserved future SDK location |
| `apps/daemon/src/soulmate_daemon/` | Configuration, API, worker, diagnostics, CLI, and composition root |
| `apps/desktop/` | Tauri shell, React UI, native service management, installer configuration |
| `apps/web/` | React browser client served by the daemon |
| `apps/mobile/` | Expo React Native client with QR pairing and pinned service identity |
| `apps/mcp/` | Scoped stdio MCP adapter backed by daemon REST |
| `tests/` | Unit, integration, and evaluation tests using synthetic data |
| `docs/` | Project guide, ADRs, phase reports, security boundaries, contributor guide |

## Documentation

| Document | Use it for |
| --- | --- |
| [`docs/index.html`](docs/index.html) ([Tiếng Việt](docs/index.vi.html)) | The consolidated project guide — start here |
| [Technical specification](<Open Personal Decision Agent — Technical Product Specification & Implementation Plan.md>) | Authoritative product definition and phase order |
| [Phase status](docs/phase-status.md) | What is built and what is authorized |
| [Architecture & ADRs](docs/architecture/README.md) | Layering rules and ADR-001 through ADR-013 |
| [Security boundaries](docs/security/README.md) | Privacy and security guarantees in force |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [AGENTS.md](AGENTS.md) | Human and AI agent rules — read before implementing |

## Language and license

Contributors may communicate with AI agents in any language. Code, comments,
identifiers, and maintained technical documentation use English. User content and
localization retain their original language.

Licensed under [Apache-2.0](LICENSE), as recommended by the specification.
