# Configuration

Configuration belongs to the daemon and uses standard-library TOML parsing with
Pydantic v2 validation. Loading settings does not create files or call providers.

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
Ollama and local embeddings. These are configuration declarations only: Phase 0
does not implement storage, vector search, inference, or network egress policy.
Selecting a privacy mode does not enable integrations. Future outbound adapters
must enforce the central policy before they can run.

## Tool references

- [uv workspace configuration](https://docs.astral.sh/uv/concepts/projects/workspaces/)
- [Pydantic settings concepts](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [pnpm workspace settings](https://pnpm.io/settings)

The loader intentionally uses explicit TOML/environment sources and Pydantic
models without adding `pydantic-settings` for the current small configuration.
