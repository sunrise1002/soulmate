# Configuration

Configuration belongs to the daemon and uses standard-library TOML parsing with
Pydantic v2 validation. Loading settings alone does not create files or call
providers; `serve` creates and migrates the configured SQLite database.

For a normal source checkout, copy `config.example.toml` to `config.toml` and use
TOML for non-secret settings. Use process environment variables for secrets and
temporary overrides. The desktop application manages a separate configuration
through its Settings screen; root `config.toml` does not configure its managed
sidecar.

## Sources and precedence

From lowest to highest priority:

1. Typed defaults.
2. TOML file selected by `<command> --config PATH`, otherwise `SOULMATE_CONFIG_FILE`,
   otherwise `./config.toml`.
3. `DATA_DIR`, which overrides TOML `data_dir`.
4. `SOULMATE_*` variables, using `__` for nested fields.

An explicitly selected config file must exist. This includes a path selected by
`SOULMATE_CONFIG_FILE`, even when that variable came from a manually loaded
`.env`. Missing implicit `./config.toml` uses defaults. Invalid TOML, unknown keys,
invalid values, and unreadable files fail with a configuration error.

`.env` files are not loaded automatically. See [development setup](setup.md) for
explicit POSIX and PowerShell loading examples. Copying `.env.example` alone has
no effect.

## Setting reference

Every TOML field maps to an environment variable by prefixing `SOULMATE_`, using
uppercase, and separating nested names with two underscores. For example,
`llm.ollama.base_url` becomes `SOULMATE_LLM__OLLAMA__BASE_URL`.

### Files, service, and web client

| TOML field | Environment variable | Default | Meaning |
| --- | --- | --- | --- |
| `data_dir` | `DATA_DIR` or `SOULMATE_DATA_DIR` | `./data` | Root for the default database, backups, generated TLS files, and other local runtime data. `SOULMATE_DATA_DIR` wins if both variables are set. |
| — | `SOULMATE_CONFIG_FILE` | unset | Selects a TOML file. Unlike implicit `./config.toml`, the selected file must exist. |
| `server.host` | `SOULMATE_SERVER__HOST` | `127.0.0.1` | Owner listener. Only literal `127.0.0.1` and `::1` are valid; this is never a LAN bind. |
| `server.port` | `SOULMATE_SERVER__PORT` | `7432` | Owner HTTP port, from 1 through 65535. All CLI clients must use the same value. |
| `web.enabled` | `SOULMATE_WEB__ENABLED` | `true` | Enables static browser-client serving when a bundle is available. |
| `web.client_dir` | `SOULMATE_WEB__CLIENT_DIR` | packaged bundle | Overrides the static bundle directory. For source development, use `apps/web/dist` after `pnpm build:web`. |

### Storage and currently reserved backends

| TOML field | Environment variable | Default | Meaning |
| --- | --- | --- | --- |
| `storage.backend` | `SOULMATE_STORAGE__BACKEND` | `sqlite` | Persistent storage backend. `sqlite` is the only accepted value. |
| `storage.path` | `SOULMATE_STORAGE__PATH` | unset | Explicit database file. When unset, uses `DATA_DIR/soulmate.db`. |
| `vector.backend` | `SOULMATE_VECTOR__BACKEND` | `sqlite_vec` | Accepts `sqlite_vec` or `cosine`; vector storage/search remains deferred, so this currently records intent rather than enabling a working vector index. |
| `embedding.provider` | `SOULMATE_EMBEDDING__PROVIDER` | `local` | Embedding provider selector. `local` is the only accepted value; embedding execution remains deferred. |

### Privacy and model provider

| TOML field | Environment variable | Default | Meaning |
| --- | --- | --- | --- |
| `privacy.mode` | `SOULMATE_PRIVACY__MODE` | `strict_local` | `strict_local` permits policy-approved loopback calls; `hybrid` also permits external HTTPS; `offline` still permits loopback model endpoints but denies connector network access and external inference. |
| `llm.provider` | `SOULMATE_LLM__PROVIDER` | `ollama` | Selects `ollama` or `openai_compatible`. |
| `llm.ollama.base_url` | `SOULMATE_LLM__OLLAMA__BASE_URL` | `http://127.0.0.1:11434` | Local Ollama HTTP endpoint. It must remain literal loopback. |
| `llm.ollama.model` | `SOULMATE_LLM__OLLAMA__MODEL` | empty | Exact installed Ollama model name. Empty means chat provider unavailable. |
| `llm.openai_compatible.base_url` | `SOULMATE_LLM__OPENAI_COMPATIBLE__BASE_URL` | `http://127.0.0.1:8000/v1` | Generic OpenAI-compatible base URL. A remote URL requires `hybrid` and HTTPS. |
| `llm.openai_compatible.model` | `SOULMATE_LLM__OPENAI_COMPATIBLE__MODEL` | empty | Model identifier sent to the compatible provider. Empty means chat provider unavailable. |
| `llm.openai_compatible.api_key` | `SOULMATE_LLM__OPENAI_COMPATIBLE__API_KEY` | unset | Optional bearer secret. Supply only through the process environment; never commit it or put it in TOML. |

### Optional encrypted remote backup

Remote backup is a separate adapter boundary; it does not replace SQLite as the
primary database. The first adapter uses the S3 protocol, so the same code works
with Cloudflare R2, AWS S3, Backblaze B2 S3, MinIO, and compatible self-hosted
stores. Contributors can implement `RemoteBackupStore` for a different backend
without changing archive or restore logic.

| TOML field | Environment variable | Default | Meaning |
| --- | --- | --- | --- |
| `remote_backup.backend` | `SOULMATE_REMOTE_BACKUP__BACKEND` | `disabled` | `disabled` preserves local-only behavior; `s3` enables the S3-compatible adapter. |
| `remote_backup.automatic_daily` | `SOULMATE_REMOTE_BACKUP__AUTOMATIC_DAILY` | `false` | Enqueues a durable encrypted upload when the configured interval has elapsed. |
| `remote_backup.interval_hours` | `SOULMATE_REMOTE_BACKUP__INTERVAL_HOURS` | `24` | Successful/enqueued backup interval, from 1 through 168 hours. |
| `remote_backup.passphrase` | `SOULMATE_REMOTE_BACKUP__PASSPHRASE` | unset | Archive encryption passphrase of at least 12 characters. Environment only; losing it makes remote backups unrecoverable. |
| `remote_backup.s3.endpoint_url` | `SOULMATE_REMOTE_BACKUP__S3__ENDPOINT_URL` | unset | Explicit S3-compatible endpoint. External endpoints must use HTTPS and require `hybrid` privacy mode. |
| `remote_backup.s3.region` | `SOULMATE_REMOTE_BACKUP__S3__REGION` | `auto` | Signing region; R2 uses `auto`. |
| `remote_backup.s3.bucket` | `SOULMATE_REMOTE_BACKUP__S3__BUCKET` | unset | Existing private bucket name. Soulmate does not create or make buckets public. |
| `remote_backup.s3.prefix` | `SOULMATE_REMOTE_BACKUP__S3__PREFIX` | `soulmate` | Object-key prefix used to isolate this backup collection. |
| `remote_backup.s3.access_key_id` | `SOULMATE_REMOTE_BACKUP__S3__ACCESS_KEY_ID` | unset | S3 access identifier. Environment only. |
| `remote_backup.s3.secret_access_key` | `SOULMATE_REMOTE_BACKUP__S3__SECRET_ACCESS_KEY` | unset | S3 secret. Environment only. |

Each remote object is a credential-free `.dtw` archive encrypted and authenticated
locally before upload. `soulmate remote-backup` triggers an immediate upload.
On a new, fresh installation, `soulmate remote-restore-latest` downloads the newest
object, validates and decrypts it, migrates known schemas, creates a new local
installation identity, and rebuilds derived model state.

This is versioned backup/restore, not bidirectional SQLite replication. Do not run
two writable installations and alternate restores between them; select one active
installation, upload a final backup, then restore it on the replacement machine.

For Cloudflare R2, create a private bucket and an R2 API token scoped to that
bucket with object read/write permission. Use the S3 endpoint shown by the R2
dashboard and export the secrets only in the daemon process:

```sh
export SOULMATE_PRIVACY__MODE=hybrid
export SOULMATE_REMOTE_BACKUP__BACKEND=s3
export SOULMATE_REMOTE_BACKUP__AUTOMATIC_DAILY=true
export SOULMATE_REMOTE_BACKUP__PASSPHRASE='replace-with-a-long-unique-passphrase'
export SOULMATE_REMOTE_BACKUP__S3__ENDPOINT_URL='https://ACCOUNT_ID.r2.cloudflarestorage.com'
export SOULMATE_REMOTE_BACKUP__S3__REGION=auto
export SOULMATE_REMOTE_BACKUP__S3__BUCKET=soulmate-backups
export SOULMATE_REMOTE_BACKUP__S3__PREFIX=soulmate
export SOULMATE_REMOTE_BACKUP__S3__ACCESS_KEY_ID='replace-me'
export SOULMATE_REMOTE_BACKUP__S3__SECRET_ACCESS_KEY='replace-me'
uv run --locked soulmate serve
```

Keep the passphrase in a password manager separate from R2. Bucket lifecycle
rules may remove old versions according to the owner's retention policy; Soulmate
does not delete remote objects automatically.

### Opt-in LAN listener

| TOML field | Environment variable | Default | Meaning |
| --- | --- | --- | --- |
| `network.lan_enabled` | `SOULMATE_NETWORK__LAN_ENABLED` | `false` | Adds a separate TLS LAN listener while preserving loopback. Requires a restart. |
| `network.lan_host` | `SOULMATE_NETWORK__LAN_HOST` | empty | Explicit LAN address. Empty asks the daemon to detect the default-route address; wildcard and loopback values are rejected. |
| `network.lan_port` | `SOULMATE_NETWORK__LAN_PORT` | `7433` | TLS LAN port, from 1 through 65535. |
| `network.tls_dir` | `SOULMATE_NETWORK__TLS_DIR` | unset | Directory for the generated certificate and owner-only private key; unset means `DATA_DIR/tls`. |
| `network.pairing_ttl_seconds` | `SOULMATE_NETWORK__PAIRING_TTL_SECONDS` | `300` | One-time pairing lifetime, from 30 through 3600 seconds. |

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

## Paths, archives, and deferred settings

Relative paths resolve against the process working directory, including when the
TOML file is elsewhere. `~` is expanded when resolving the database path. Without
an explicit `storage.path`, the database location is `DATA_DIR/soulmate.db`.
An explicit storage path takes precedence over that derived location. Choose an
absolute `DATA_DIR` when launching from different directories.

Phase 10 local backups and encrypted exports default to `DATA_DIR/backups`.
Archives read the configured database path but never include configuration, TLS
keys, logs, or the backups directory itself. A staged desktop restore uses a
private temporary directory and marker under `DATA_DIR`, applies on daemon
restart, and is removed after successful migration. Do not manually edit or move
`.restore-*` files while a restore is pending.

Phase 11 connector registration stores non-secret configuration and granted
permission snapshots in SQLite. Connector credentials are read only from dedicated
process variables using
`SOULMATE_CONNECTOR__<NORMALIZED_CONNECTOR_ID>__<NORMALIZED_KEY>`; for example,
credential key `api_token` on `example.calendar` becomes
`SOULMATE_CONNECTOR__EXAMPLE_CALENDAR__API_TOKEN`. Credential values are not
accepted by the registration API, persisted, logged, or included in archives.
Connector HTTP destinations must appear in the installed manifest and pass the same
privacy-mode policy as model calls. `offline` denies all connector network access.

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

## Complete examples

Run local Ollama while keeping every model request on the machine:

```sh
SOULMATE_LLM__OLLAMA__MODEL=llama3.2 uv run --locked soulmate serve
```

Run a daemon-served web bundle from a source checkout:

```sh
pnpm build:web
SOULMATE_WEB__CLIENT_DIR=apps/web/dist uv run --locked soulmate serve
```

Select an alternate file and absolute data location:

```sh
DATA_DIR=/srv/soulmate/data \
  uv run --locked soulmate serve --config /etc/soulmate/config.toml
```

Use the same configuration selection for `serve`, `status`, `doctor`, local and
remote backup/restore, import, and rebuild commands so they resolve the same
listener, database, and optional storage backend.

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
