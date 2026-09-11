# Soulmate

A local-first, self-hosted Personal Decision Model. The owner controls the data;
agents, LLM providers, and clients are replaceable.

**Current status:** Phase 0 foundation. The daemon starts as an empty application.
Phase 1 has not started. See [phase status](docs/phase-status.md).

## Development setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24,
and pnpm 11.21.0. `uv` manages the Python 3.12 development interpreter; Python
packages declare support for Python 3.12 and later.

If `uv` was installed in `~/.local/bin` and your macOS/Linux shell cannot find it,
add that directory to the current shell before running the commands below:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Your editor's Git environment also needs `uv` on PATH for the pre-commit hook.

```sh
uv sync --locked --all-packages
pnpm install --frozen-lockfile
uv run --locked pre-commit install
```

Run all current checks:

```sh
pnpm check
```

Start the Phase 0 development shell:

```sh
uv run --locked decision-twin serve
```

The process listens on `127.0.0.1:7432`; every HTTP path returns 404 because no
product routes exist yet. Stop it with Ctrl+C. Startup does not create storage,
contact model providers, or launch jobs. The minimal `serve` entry point satisfies
the Phase 0 startup criterion; health, persistence, status, and doctor are Phase 1.

Optionally copy `config.example.toml` to `config.toml` and edit it. Local config is
ignored by Git. See [configuration](docs/contributor-guide/configuration.md) for
environment overrides, `DATA_DIR`, and path semantics.

## Repository map

| Path | Responsibility |
| --- | --- |
| `packages/core-python/src/soulmate_core/` | Infrastructure-independent kernel; empty module boundaries in Phase 0 |
| `apps/daemon/src/soulmate_daemon/` | Typed configuration, application composition, development entry point |
| `apps/{desktop,mobile,web,mcp}/` | Reserved client and integration locations |
| `packages/{storage-sqlite,llm-providers,sdk-python,sdk-typescript}/` | Reserved adapter and SDK locations |
| `tests/` | Unit, integration, and future evaluation tests with synthetic data |
| `docs/architecture/decisions/` | ADR-001 through ADR-008 |
| `docs/contributor-guide/` | Conventions and configuration reference |

The root [technical specification](<Open Personal Decision Agent — Technical Product Specification & Implementation Plan.md>)
defines the product and phase order. Read [AGENTS.md](AGENTS.md) for AI agent rules
and [CONTRIBUTING.md](CONTRIBUTING.md) before implementation.

## Language and license

Contributors may communicate with AI agents in any language. Code, comments,
identifiers, and maintained technical documentation use English. User content and
localization retain their original language.

Licensed under [Apache-2.0](LICENSE), as recommended by the specification.
