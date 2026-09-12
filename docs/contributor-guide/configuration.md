# Configuration

Configuration belongs to the daemon and uses standard-library TOML parsing with
Pydantic v2 validation. Loading settings alone does not create files or call
providers; `serve` creates and migrates the configured SQLite database.

## Sources and precedence

From lowest to highest priority:

1. Typed defaults.
2. TOML file selected by `serve --config PATH`, otherwise `SOULMATE_CONFIG_FILE`,
   otherwise `./config.toml`.
3. `DATA_DIR`, which overrides TOML `data_dir`.
4. `SOULMATE_*` variables, using `__` for nested fields.

An explicitly selected config file must exist. Missing implicit `./config.toml`
uses defaults. Invalid TOML, unknown keys, invalid values, and unreadable files
fail with a configuration error. `.env` files are not loaded automatically.

Examples of environment variables:

| Variable | Field | Default |
| --- | --- | --- |
| `SOULMATE_DATA_DIR` or `DATA_DIR` | `data_dir` | `./data` |
| `SOULMATE_SERVER__HOST` | `server.host` | `127.0.0.1` |
| `SOULMATE_SERVER__PORT` | `server.port` | `7432` |
| `SOULMATE_PRIVACY__MODE` | `privacy.mode` | `strict_local` |
| `SOULMATE_NETWORK__LAN_ENABLED` | `network.lan_enabled` | `false` |
| `SOULMATE_NETWORK__LAN_HOST` | `network.lan_host` | empty, detected |
| `SOULMATE_NETWORK__LAN_PORT` | `network.lan_port` | `7433` |
| `SOULMATE_NETWORK__TLS_DIR` | `network.tls_dir` | `DATA_DIR/tls` |
| `SOULMATE_NETWORK__PAIRING_TTL_SECONDS` | `network.pairing_ttl_seconds` | `300` |
| `SOULMATE_WEB__ENABLED` | `web.enabled` | `true` |
| `SOULMATE_WEB__CLIENT_DIR` | `web.client_dir` | packaged bundle |
| `SOULMATE_STORAGE__PATH` | `storage.path` | unset |
| `SOULMATE_LLM__OLLAMA__MODEL` | `llm.ollama.model` | empty |
| `SOULMATE_LLM__PROVIDER` | `llm.provider` | `ollama` |
| `SOULMATE_LLM__OPENAI_COMPATIBLE__BASE_URL` | compatible endpoint | loopback `/v1` |
| `SOULMATE_LLM__OPENAI_COMPATIBLE__MODEL` | compatible model | empty |
| `SOULMATE_LLM__OPENAI_COMPATIBLE__API_KEY` | provider secret | unset |

Only `127.0.0.1` and `::1` are accepted for `server.host`. Ports must be between 1
and 65535.

## Access from other devices

`network.lan_enabled` is false by default. When it is true the daemon keeps its
loopback listener and adds a TLS listener on `network.lan_host:network.lan_port`.
An empty `lan_host` uses the address of the default route. Wildcard addresses
(`0.0.0.0`, `::`, `[::]`, `*`) are rejected by configuration and by the resolver, as
are loopback addresses, so LAN exposure is always explicit. If no address or
certificate can be prepared, the daemon still serves loopback and reports the
reason through `GET /v1/network/state`.

The service certificate and its owner-only private key live in
`network.tls_dir`, defaulting to `DATA_DIR/tls`. It is generated on first use and
renewed within seven days of expiry or when the LAN address changes; devices pin
the `sha256:` fingerprint reported by `GET /v1/network/state`.

`network.pairing_ttl_seconds` accepts 30 to 3600 seconds. Enabling or disabling LAN
access is a startup decision, so the service must restart to apply it.

`web.enabled` controls whether the daemon serves a web client. Without
`web.client_dir`, it serves the bundle packaged inside the daemon, when present.

## Paths and future settings

Relative paths resolve against the process working directory, including when the
TOML file is elsewhere. `~` is expanded when resolving the database path. Without
an explicit `storage.path`, the database location is `DATA_DIR/decision-twin.db`.
An explicit storage path takes precedence over that derived location. Choose an
absolute `DATA_DIR` when launching from different directories.

Phase 10 local backups and encrypted exports default to `DATA_DIR/backups`.
Archives read the configured database path but never include configuration, TLS
keys, logs, or the backups directory itself. A staged desktop restore uses a
private temporary directory and marker under `DATA_DIR`, applies on daemon
restart, and is removed after successful migration. Do not manually edit or move
`.restore-*` files while a restore is pending.

Privacy mode accepts `strict_local`, `hybrid`, and `offline`. Storage accepts
`sqlite`; vector backend accepts `sqlite_vec` or `cosine`; provider defaults are
Ollama and local embeddings. `strict_local` and `offline` restrict model requests
to literal loopback endpoints. `hybrid` also allows external HTTPS endpoints, but
never plaintext external HTTP. The egress policy is enforced inside both HTTP
adapters immediately before every request.

Provider secrets should be supplied through the process environment and never
committed to TOML. The OpenAI-compatible adapter is generic and does not require a
specific vendor SDK. Provider configuration is lazy: the daemon can start without
a model, while `/v1/chat` returns a provider-unavailable response until a model is
configured. Vector search remains deferred.

## Desktop configuration

The desktop shell translates its Settings screen into the daemon environment and
always supplies an application-specific absolute data directory plus
`127.0.0.1:7432`. The shell supports Ollama and generic OpenAI-compatible provider
settings with the same privacy semantics as the daemon:

- `strict_local` and `offline` accept only literal loopback provider URLs.
- `hybrid` accepts loopback HTTP or remote HTTPS provider URLs.
- Ollama is always local and therefore requires a loopback HTTP URL.

The Devices screen writes `lanEnabled` into the same stored settings and restarts
the managed daemon. Settings saved before Phase 7 keep access from other devices
off.

Non-secret desktop settings are stored as `desktop-settings.json` in the platform
application-configuration directory. A compatible-provider API key is stored separately in
the operating system credential store. The UI receives only a boolean indicating
whether a key exists. Saving an empty key preserves the existing credential;
explicit removal deletes it. Restart the managed daemon to apply changed settings.

## Tool references

- [uv workspace configuration](https://docs.astral.sh/uv/concepts/projects/workspaces/)
- [Pydantic settings concepts](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [pnpm workspace settings](https://pnpm.io/settings)

The loader intentionally uses explicit TOML/environment sources and Pydantic
models without adding `pydantic-settings` for the current small configuration.
