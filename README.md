# Soulmate

A local-first, self-hosted **Personal Decision Model**. Its goal is not to be the
smartest general-purpose agent, but to understand one specific person as
accurately as possible — and to keep that understanding on that person's own
machine. The owner controls the data; agents, LLM providers, and clients are
replaceable.

There is no Soulmate cloud. Each owner runs their own service.

📖 **[Read the project guide → `docs/index.html`](docs/index.html)** — vision,
architecture, technology, usage, API, and privacy boundaries in one page. For a
source checkout, use the dedicated [setup, build, and run guide](docs/contributor-guide/setup.md).

**Current status:** Phases 0–12 are complete locally; Phase 12 is the Delegated
Decision Agent. See [phase status](docs/phase-status.md) and the
[Phase 12 report](docs/phases/phase-12-report.md). Remote CI remains unverified.

## Source quick start

For only the daemon and CLI, install
[uv](https://docs.astral.sh/uv/getting-started/installation/). For the complete
desktop workspace, also install Node.js 24, pnpm 11.21.0, Rust 1.88+, and the
[native Tauri prerequisites](https://v2.tauri.app/start/prerequisites/). `uv`
manages the Python 3.12+ interpreter.

```sh
# if uv is in ~/.local/bin and your shell cannot find it
export PATH="$HOME/.local/bin:$PATH"

uv sync --locked --all-packages
pnpm install --frozen-lockfile
rustup component add rustfmt clippy
uv run --locked pre-commit install --install-hooks \
  --hook-type pre-commit --hook-type commit-msg --hook-type pre-push

pnpm check    # lint, format check, typecheck, and tests across Python, TS, and Rust
```

Your editor's Git environment also needs `uv` on PATH for the pre-commit hook.

Configuration is optional for the first start. The recommended non-secret setup
is:

```sh
cp config.example.toml config.toml
```

`.env.example` is also provided, but `.env` files are **not loaded
automatically**. Either export the required variables in your shell or explicitly
load the file before starting:

```sh
cp .env.example .env
set -a
. ./.env
set +a
```

Run and verify the service:

```sh
uv run --locked soulmate serve
# in another terminal, with the same configuration environment
uv run --locked soulmate status
```

It listens on `127.0.0.1:7432`, applies packaged Alembic migrations, creates
`DATA_DIR/soulmate.db`, and starts the durable local job worker. It enables
no telemetry; model calls happen only when `/v1/chat` is used and must pass the
configured egress policy. Chat remains unavailable until a model is configured;
the daemon itself and deterministic features still work.

Run the complete desktop product, or build a native installer with its bundled
daemon sidecar:

```sh
pnpm --filter @soulmate/desktop tauri dev
pnpm --filter @soulmate/desktop tauri build
```

The installed application starts and monitors its own loopback daemon, stores data
in the platform application-data directory, and needs no separately installed
Python, Node.js, database, or Docker runtime.

Both local config files and `./data` are git-ignored. See the
[setup guide](docs/contributor-guide/setup.md) for prerequisite and OS-specific
instructions, provider examples, separate daemon/web/mobile flows, build artifact
locations, and troubleshooting. The [configuration reference](docs/contributor-guide/configuration.md)
defines every parameter, precedence, valid value, and path/security behavior.

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
| `remote-backup` | Encrypt and upload a backup through the configured storage adapter |
| `remote-restore-latest` | Restore the newest remote backup into a fresh installation |
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
| `packages/llm-providers/` | Provider protocol, capability negotiation, egress policy, fake, Ollama, and OpenAI-compatible adapters |
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
| [`docs/index.html`](docs/index.html) | The consolidated project guide — start here |
| [Setup, build, and run](docs/contributor-guide/setup.md) | Source prerequisites, installation, `.env`, providers, run modes, artifacts, and troubleshooting |
| [Technical specification](<Open Personal Decision Agent — Technical Product Specification & Implementation Plan.md>) | Authoritative product definition and phase order |
| [Phase status](docs/phase-status.md) | What is built and what is authorized |
| [Architecture & ADRs](docs/architecture/README.md) | Layering rules and implemented ADRs through ADR-015; ADR-014 is reserved for Phase 13 |
| [Security boundaries](docs/security/README.md) | Privacy and security guarantees in force |
| [CONTRIBUTING.md](CONTRIBUTING.md) · [AGENTS.md](AGENTS.md) | Human and AI agent rules — read before implementing |

## Language and license

Contributors may communicate with AI agents in any language. Code, comments,
identifiers, and maintained technical documentation use English. User content and
localization retain their original language.

Licensed under [Apache-2.0](LICENSE), as recommended by the specification.
