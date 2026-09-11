# Soulmate

A local-first, self-hosted Personal Decision Model. The owner controls the data;
agents, LLM providers, and clients are replaceable.

**Current status:** Phase 4 Decision MVP is implemented locally.
See the [phase status](docs/phase-status.md) and detailed
[Phase 4 report](docs/phases/phase-4-report.md).

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

Start the local service:

```sh
uv run --locked decision-twin serve
```

The process listens on `127.0.0.1:7432`, automatically applies packaged Alembic
migrations, creates `DATA_DIR/decision-twin.db`, and starts the durable local job
worker. Stop it with Ctrl+C. It does not enable telemetry. Model calls occur only
when `/v1/chat` is used and must pass the configured local egress policy.

Inspect the running service or local persistence:

```sh
uv run --locked decision-twin status
uv run --locked decision-twin doctor
uv run --locked decision-twin rebuild-model
```

`status` queries `/v1/health` and `/v1/system/info`. `doctor` checks storage
permissions, database integrity, WAL, foreign keys, migration state, and whether
the configured port is already in use. It also reports whether the selected model
provider has a configured model. Both commands emit machine-readable JSON and
return nonzero when their required checks fail. Vector diagnostics remain deferred.

`rebuild-model` deterministically replaces derived model state from all stored
evidence and creates a new versioned snapshot. The Phase 2 API also exposes
`GET /v1/model/summary`, `GET /v1/preferences`, `GET /v1/evidence/{id}`,
`GET /v1/preferences/{key}/evidence`, and `POST /v1/preferences/corrections`.
Corrections create a RawEvent and correction Evidence before rebuilding; they do
not overwrite history.

`POST /v1/chat` persists conversations and messages, sends only lexically relevant
Personal Model context to the configured provider, validates structured evidence
proposals, accepts ordinary low-risk claims, and rebuilds the model when evidence
is accepted. Ollama is the default local adapter. A generic OpenAI-compatible
adapter is available in `hybrid` mode; configure its secret through the environment.

The Decision MVP exposes `POST /v1/decisions`,
`POST /v1/decisions/{id}/predict`, and `POST /v1/decisions/{id}/resolve`.
Options may supply normalized structured features directly or use the configured
provider to extract them from natural descriptions. Predict Me scoring is local
and deterministic, returns probabilities and evidence-backed factors, and records
the exact Personal Model snapshot. Resolving the actual choice creates
provenance-bearing `actual_choice` Evidence and rebuilds the model.

Optionally copy `config.example.toml` to `config.toml` and edit it. Local config is
ignored by Git. See [configuration](docs/contributor-guide/configuration.md) for
environment overrides, `DATA_DIR`, and path semantics.

## Repository map

| Path | Responsibility |
| --- | --- |
| `packages/core-python/src/soulmate_core/` | Infrastructure-independent entities and repository ports |
| `packages/storage-sqlite/` | SQLAlchemy adapter and packaged Alembic migrations |
| `apps/daemon/src/soulmate_daemon/` | Configuration, API, worker, diagnostics, and composition root |
| `apps/{desktop,mobile,web,mcp}/` | Reserved client and integration locations |
| `packages/llm-providers/` | Provider protocol, fake provider, egress policy, Ollama, and OpenAI-compatible adapters |
| `packages/{sdk-python,sdk-typescript}/` | Reserved future SDK locations |
| `tests/` | Unit, integration, and future evaluation tests with synthetic data |
| `docs/architecture/decisions/` | ADR-001 through ADR-008 |
| `docs/phases/` | Durable plans, results, issues, and handoff reports per phase |
| `docs/contributor-guide/` | Conventions and configuration reference |

The root [technical specification](<Open Personal Decision Agent — Technical Product Specification & Implementation Plan.md>)
defines the product and phase order. Read [AGENTS.md](AGENTS.md) for AI agent rules
and [CONTRIBUTING.md](CONTRIBUTING.md) before implementation.

## Language and license

Contributors may communicate with AI agents in any language. Code, comments,
identifiers, and maintained technical documentation use English. User content and
localization retain their original language.

Licensed under [Apache-2.0](LICENSE), as recommended by the specification.
