# Soulmate

A local-first, self-hosted Personal Decision Model. The owner controls the data;
agents, LLM providers, and clients are replaceable.

**Current status:** Phase 12 Delegated Decision Agent is implemented locally.
See the [phase status](docs/phase-status.md) and detailed
[Phase 12 report](docs/phases/phase-12-report.md).

## Development setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24,
pnpm 11.21.0, and Rust 1.88 or later. `uv` manages the Python 3.12 development
interpreter; Python packages declare support for Python 3.12 and later.

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

Run the desktop product in development mode:

```sh
rustup component add rustfmt clippy
pnpm --filter @soulmate/desktop tauri dev
```

Build a native installer and its bundled daemon sidecar:

```sh
pnpm --filter @soulmate/desktop tauri build
```

The installed application starts and monitors its own loopback daemon, stores
data in the platform application-data directory, and needs no separately installed
Python, Node.js, database, or Docker runtime.

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
uv run --locked decision-twin evaluate
uv run --locked decision-twin backup
uv run --locked decision-twin import ./history.json
uv run --locked decision-twin export --output ./personal-model.dtw
uv run --locked decision-twin connectors
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

`evaluate` runs the packaged synthetic decision dataset without a database,
network access, or model provider. It emits machine-readable random, frozen
LLM-only, memory-only, Personal Model, and Decision Model results with accuracy,
Top-2 accuracy, log loss, multiclass Brier score, and confidence-calibration
error. Use `--dataset PATH` to evaluate another dataset with the same validated
schema.

`POST /v1/chat` persists conversations and messages, sends only lexically relevant
Personal Model context to the configured provider, validates structured evidence
proposals, accepts ordinary low-risk claims, and rebuilds the model when evidence
is accepted. Ollama is the default local adapter. A generic OpenAI-compatible
adapter is available in `hybrid` mode; configure its secret through the environment.

The Decision MVP exposes `POST /v1/decisions`,
`POST /v1/decisions/{id}/predict`, and `POST /v1/decisions/{id}/resolve`.
Options may supply normalized structured features directly or use the configured
provider to extract them from natural descriptions. Predict Me scoring is local
and deterministic, combines global, domain, and matching-context preferences with
online pairwise learning from prior resolutions, returns probabilities and
evidence-backed factors, and records the exact Personal Model snapshot and
learning algorithm version. Resolving the actual choice creates provenance-bearing
`actual_choice` Evidence and rebuilds the model.

Phase 8 adds `GET /v1/model/uncertainties`, persistent questions under
`/v1/active-questions`, `POST /v1/decisions/{id}/outcome`, and
`POST /v1/decisions/{id}/advise`. The owner can remove outcome source data with
`DELETE /v1/decisions/{id}/outcome`. Pairwise answers create inspectable preference
Evidence. Outcome feedback remains separate from behavioral preference learning:
Predict Me estimates the owner's likely choice, while Advise Me independently
combines that prediction with satisfaction, regret, similar resolved choices, and
matching goals or constraints. Both modes report their model snapshot and
algorithm version, and clients display them as distinct results.

Phase 9 adds separately scoped external service identities, independently
revocable API keys stored only as secure hashes, and a metadata-only local audit
trail. The desktop External Agents screen controls permissions and shows each new
key once. External REST responses provide derived summaries and decision results
without returning raw evidence, memories, outcome notes, or the broader personal
database.

Phase 10 adds consistent credential-free local backups and passphrase-encrypted
portable exports. `backup` writes a `.dtwb` archive under `DATA_DIR/backups` by
default. `export` writes an AES-256-GCM authenticated `.dtw` archive and prompts
for a passphrase; automation can use `--passphrase-file PATH` without exposing the
passphrase in process arguments. Archives include the database and any local
`objects`, `indexes`, and `models` files. They exclude pairing state, API
credentials, installation identity, TLS keys, provider secrets, logs,
configuration, and existing backups.

Restore while the daemon is stopped and only into a fresh installation:

```sh
DATA_DIR=./fresh-data uv run --locked decision-twin restore ./backup.dtwb
DATA_DIR=./fresh-data uv run --locked decision-twin restore ./personal-model.dtw
```

Encrypted restore prompts for the passphrase or accepts `--passphrase-file`.
Known older schemas migrate forward, the destination receives a new installation
identity, and the Personal Model is rebuilt from Evidence. Restore never merges
with or overwrites owner-created data.

`import` accepts UTF-8 generic JSON, Markdown, plain text, ChatGPT exports, and
Claude exports. Use `--format auto|json|markdown|text|chatgpt|claude`; auto is the
default. Imports create provenance-linked conversations and RawEvents locally and
never trigger hidden model-provider egress. The desktop Data & Privacy screen
provides one-click backup, encrypted export, fresh-install staged restore, import,
and source deletion. Deleting an imported source removes its messages, RawEvents,
and derivative Evidence before rebuilding the model.

Phase 11 adds an independently installable Python connector SDK and entry-point
discovery without adding connector dependencies to the Personalization Kernel.
The owner-only Connections API and desktop screen show each plugin's declared data,
network, credential, and RawEvent-learning permissions before registration.
Synchronizations run as durable local jobs, deduplicate external item identities,
and persist sanitized state and audits. Connector credentials come only from
dedicated `DECISION_TWIN_CONNECTOR__...` process variables, while allowed network
calls pass a manifest host allowlist and the central privacy policy.

The bundled Local Notes reference connector reads only UTF-8 Markdown and text
files under one explicitly configured directory and performs no network calls.
Connector routes are `GET /v1/connectors/catalog`, `GET/POST /v1/connectors`,
`PATCH/DELETE /v1/connectors/{id}`, `POST /v1/connectors/{id}/sync`, and
`GET /v1/connectors/syncs/{job_id}`. Removing a connector deletes its RawEvents and
derivative Evidence before rebuilding the Personal Model. Installed connector
packages are trusted owner-selected code; see ADR-012 before installing third-party
plugins.

Phase 12 adds a separate deterministic Policy Engine. The owner grants an external
identity the `agent:delegate` scope and creates a policy for one exact action type.
The policy assigns impact and a confidence threshold; impact is never accepted
from the agent. Low-impact automatic approval requires at least 0.90 confidence,
medium impact requires at least 0.95, and high or safety-critical actions always
require confirmation. Every request uses the latest persisted prediction from the
current Personal Model snapshot, has a per-agent idempotency key, expires after 24
hours, and survives restart.

Owner routes are `GET/POST /v1/delegation-policies`,
`DELETE /v1/delegation-policies/{id}`, `GET /v1/delegation-requests`, and
`POST /v1/delegation-requests/{id}/approve|reject`. Scoped agents use
`POST /v1/external/delegation-requests`,
`GET /v1/external/delegation-requests/{id}`, and
`POST /v1/external/delegation-requests/{id}/complete`. Soulmate returns authority
and the predicted option but never performs the external side effect.

Run the stdio MCP adapter through the daemon executable:

```sh
SOULMATE_API_KEY='<key-shown-once>' uv run --locked decision-twin mcp
```

Set `SOULMATE_BASE_URL` only when the daemon does not use the default
`http://127.0.0.1:7432`. The nine tools are `predict_choice`, `rank_options`,
`get_preference_summary`, `find_similar_decisions`, `record_decision`, and
`record_outcome`, plus `request_delegation`, `get_delegation`, and
`complete_delegation`. Grant the corresponding scopes in the desktop UI. Every
tool call passes the same authorization boundary and application services as REST.

Phase 10 owner-only routes are `GET /v1/data/sources`,
`POST /v1/data/imports`, `DELETE /v1/data/sources/{id}`,
`POST /v1/data/backups`, `POST /v1/data/exports`, and
`POST /v1/data/restores`. Paired devices and external service identities cannot
use data-management operations.

The desktop history views use `GET /v1/conversations` and `GET /v1/decisions`.
The My Model screen can inspect provenance, add correction evidence, and use
`DELETE /v1/evidence/{id}` to remove evidence before a deterministic model rebuild.

## Access from other devices

Access from other devices is off until you turn it on. When enabled, the daemon
keeps its loopback listener and adds a TLS listener on one explicit local network
address; wildcard binds are rejected. Enable it from the desktop Devices screen, or
set `network.lan_enabled` in `config.toml` or `SOULMATE_NETWORK__LAN_ENABLED`.

The Devices screen creates a one-time pairing code that expires in five minutes.
Scan it with the mobile client, or type it into the web client on the other device.
The daemon stores only hashes of the pairing token and of the issued device
credential, and the QR payload carries the certificate fingerprint so a phone pins
the service it paired with. Revoke any device from the same screen; the next
request from that device fails immediately.

Loopback callers are the owner for normal owner/client routes. External API paths
always require a service API key, including on loopback. Every other caller needs
an active device credential. Pairing, device listing, revocation, network status, and evidence
deletion are only available on the owner's machine. A paired device can chat,
decide, resolve, read the model, record corrections, answer active-learning
questions, record outcomes, and request advice.

The pairing and device endpoints are `POST /v1/pairing/start`,
`POST /v1/pairing/complete`, `GET /v1/devices`, `DELETE /v1/devices/{id}`,
`GET /v1/network/state`, and `GET /v1/session`. The web client is served from the
service root when its bundle is packaged with the daemon.

The service certificate is self-signed, so a browser shows a warning the first
time. Remote internet exposure is out of scope; use a private network such as a VPN
if you need access away from home.

Optionally copy `config.example.toml` to `config.toml` and edit it. Local config is
ignored by Git. See [configuration](docs/contributor-guide/configuration.md) for
environment overrides, `DATA_DIR`, and path semantics.

## Repository map

| Path | Responsibility |
| --- | --- |
| `packages/core-python/src/soulmate_core/` | Infrastructure-independent entities and repository ports |
| `packages/connector-sdk/` | Stable permission manifest, event, sync, discovery, and persistence contracts for plugins |
| `packages/connectors-local/` | Independently packaged Local Notes reference connector |
| `packages/storage-sqlite/` | SQLAlchemy adapter and packaged Alembic migrations |
| `apps/daemon/src/soulmate_daemon/` | Configuration, API, worker, diagnostics, and composition root |
| `apps/desktop/` | Tauri shell, React UI, native service management, and installer configuration |
| `apps/web/` | React browser client served by the daemon |
| `apps/mobile/` | Expo React Native client with QR pairing and pinned service identity |
| `apps/mcp/` | Scoped stdio MCP adapter backed by daemon REST application services |
| `packages/llm-providers/` | Provider protocol, fake provider, egress policy, Ollama, and OpenAI-compatible adapters |
| `packages/sdk-typescript/` | Typed REST client and pairing rules shared by clients |
| `packages/sdk-python/` | Reserved future SDK location |
| `tests/` | Unit, integration, and evaluation tests using synthetic data |
| `docs/architecture/decisions/` | ADR-001 through ADR-012 |
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
