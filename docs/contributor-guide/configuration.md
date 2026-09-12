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
| `SOULMATE_STORAGE__PATH` | `storage.path` | unset |
| `SOULMATE_LLM__OLLAMA__MODEL` | `llm.ollama.model` | empty |
| `SOULMATE_LLM__PROVIDER` | `llm.provider` | `ollama` |
| `SOULMATE_LLM__OPENAI_COMPATIBLE__BASE_URL` | compatible endpoint | loopback `/v1` |
| `SOULMATE_LLM__OPENAI_COMPATIBLE__MODEL` | compatible model | empty |
| `SOULMATE_LLM__OPENAI_COMPATIBLE__API_KEY` | provider secret | unset |

Only `127.0.0.1` and `::1` are accepted as bind addresses in the foundation. Ports
must be between 1 and 65535. LAN activation and secure pairing belong to Phase 7.

## Paths and future settings

Relative paths resolve against the process working directory, including when the
TOML file is elsewhere. `~` is expanded when resolving the database path. Without
an explicit `storage.path`, the database location is `DATA_DIR/decision-twin.db`.
An explicit storage path takes precedence over that derived location. Choose an
absolute `DATA_DIR` when launching from different directories.

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
