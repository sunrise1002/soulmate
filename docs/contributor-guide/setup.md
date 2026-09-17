# Development setup, build, and run

This guide covers a source checkout. Installed desktop releases are intended to
be self-contained, but the repository does not currently publish signed release
artifacts. Build installers on the operating system they target.

## Choose the path you need

| Goal | Required toolchains | Command |
| --- | --- | --- |
| Run the daemon and CLI | uv | `uv run --locked soulmate serve` |
| Run the complete desktop product | uv, Node.js/pnpm, Rust, native Tauri prerequisites | `pnpm --filter @soulmate/desktop tauri dev` |
| Build browser assets | Node.js/pnpm | `pnpm build:web` |
| Run the Expo development server | Node.js/pnpm and the Expo target prerequisites | `pnpm --filter @soulmate/mobile start` |
| Run every repository check | All desktop toolchains | `pnpm check:all` |

Docker Compose is not implemented. The daemon uses embedded SQLite, so no
database server is required.

## Prerequisites

Run commands from the repository root. The supported workspace versions are:

- `uv` 0.12.x; the lockfile and CI currently use 0.12.13.
- Python 3.12 or later. `uv` downloads and manages a compatible interpreter.
- Node.js 24, selected by `.node-version` and enforced by `package.json`.
- pnpm 11.21.0, pinned by the `packageManager` field.
- Rust 1.88 or later for the native desktop shell.

Enable pnpm with Corepack after installing Node.js:

```sh
corepack enable
corepack prepare pnpm@11.21.0 --activate
```

Install the native prerequisites before building the desktop app:

- macOS: install Xcode Command Line Tools with `xcode-select --install`.
- Windows: install Microsoft C++ Build Tools with **Desktop development with
  C++** and Microsoft Edge WebView2. Use the MSVC Rust toolchain.
- Debian/Ubuntu: install the packages used by CI:

  ```sh
  sudo apt-get update
  sudo apt-get install -y \
    libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev \
    libxdo-dev libssl-dev patchelf
  ```

Other Linux distributions need their equivalent WebKitGTK 4.1, app indicator,
SVG, OpenSSL, and build packages. See the
[official Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

Confirm the toolchain before installing dependencies:

```sh
uv --version
node --version
pnpm --version
rustc --version
```

## Install the workspace

```sh
uv sync --locked --all-packages
pnpm install --frozen-lockfile
rustup component add rustfmt clippy
uv run --locked pre-commit install --install-hooks \
  --hook-type pre-commit --hook-type commit-msg --hook-type pre-push
```

`uv sync` creates `.venv` and installs all Python workspace packages from
`uv.lock`. `pnpm install` installs every TypeScript package from
`pnpm-lock.yaml`. Do not use `pip install -r requirements.txt` or `npm install`;
this repository has no requirements file and uses workspace lockfiles.

If `uv` was installed under `~/.local/bin`, ensure that directory is also on the
`PATH` inherited by Git and your editor:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

## Configure the daemon

Configuration is optional for a first daemon start. Defaults bind only to
`127.0.0.1:7432`, store data under `./data`, use strict-local privacy, and make no
model call until a chat request is sent. Chat requires a configured model.

### Recommended: TOML for non-secret settings

```sh
cp config.example.toml config.toml
```

Edit `config.toml` as needed. Both `config.toml` and local data are ignored by
Git. Keep provider API keys out of TOML and source control.

### Optional: process environment and `.env`

The daemon reads process environment variables, but deliberately does **not**
load `.env` files. `.env.example` is a documented template, not an automatic
runtime feature. To use it in a POSIX shell:

```sh
cp .env.example .env
set -a
. ./.env
set +a
uv run --locked soulmate serve
```

In PowerShell, load its simple `NAME=value` lines into the current process:

```powershell
Copy-Item .env.example .env
Get-Content .env |
  Where-Object { $_ -match '^[^#].*=.*$' } |
  ForEach-Object {
    $name, $value = $_ -split '=', 2
    Set-Item -Path "Env:$name" -Value $value
  }
uv run --locked soulmate serve
```

You can also set only the variables needed for one command:

```sh
DATA_DIR=./data SOULMATE_LLM__OLLAMA__MODEL=llama3.2 \
  uv run --locked soulmate serve
```

Environment values override TOML. See the
[configuration reference](configuration.md) for every setting, its meaning,
precedence, valid values, and security implications.

## Configure a model provider

The daemon starts without a model, but chat returns a provider-unavailable error.
Decision scoring and other deterministic features remain usable.

For local inference, install [Ollama](https://docs.ollama.com/), download a model,
and put the exact model name in `config.toml` or the environment:

```sh
ollama pull llama3.2
export SOULMATE_LLM__OLLAMA__MODEL=llama3.2
```

The default Ollama endpoint is `http://127.0.0.1:11434`. `strict_local` and
`offline` accept only literal loopback provider URLs.

For a remote OpenAI-compatible HTTPS endpoint, use `hybrid` mode and provide the
secret only through the process environment:

```sh
export SOULMATE_PRIVACY__MODE=hybrid
export SOULMATE_LLM__PROVIDER=openai_compatible
export SOULMATE_LLM__OPENAI_COMPATIBLE__BASE_URL=https://provider.example/v1
export SOULMATE_LLM__OPENAI_COMPATIBLE__MODEL=model-name
export SOULMATE_LLM__OPENAI_COMPATIBLE__API_KEY=replace-me
uv run --locked soulmate serve
```

The generic adapter can be pointed at the compatibility endpoint published by a
provider such as OpenAI, Anthropic, Gemini, DeepSeek, GLM, or Kimi, as well as
local servers such as vLLM or LM Studio. Use the provider's exact base URL and
model identifier; these values change independently of Soulmate. Compatibility
does not imply identical structured-output support, so Soulmate automatically
negotiates strict schema, JSON-object, and validated prompted-JSON modes. The
reply is saved and returned before structured learning runs as a durable background
job. A model that cannot produce valid learning data remains usable for chat and
does not modify the Personal Model.

External plaintext HTTP is always rejected. `offline` still permits loopback
model endpoints, but denies connector network access and all external inference.

## Run and verify

### Daemon and CLI

Start the daemon in one terminal:

```sh
uv run --locked soulmate serve
```

It creates and migrates `DATA_DIR/soulmate.db`. From a second terminal, using the
same configuration environment, verify the live service:

```sh
uv run --locked soulmate status
curl http://127.0.0.1:7432/v1/health
```

Stop the daemon with `Ctrl+C`, then run the offline diagnostics:

```sh
uv run --locked soulmate doctor
```

`status` expects a running daemon. `doctor` intentionally reports unhealthy
before the database exists, and its `port_available` check is false while the
daemon is using the configured port.

### Complete desktop app

```sh
pnpm --filter @soulmate/desktop tauri dev
```

This command builds a target-suffixed PyInstaller daemon sidecar, starts the Vite
frontend, launches the native shell, and supervises its own daemon. Desktop
settings are separate from root `config.toml`; use the app's Settings screen for
model providers, privacy mode, and optional encrypted R2/S3-compatible backup.
Desktop backup credentials and its encryption passphrase are stored in the
operating-system credential store, so no `.env` file is required.

`pnpm --filter @soulmate/desktop dev` starts only the Vite webview and does not
start the sidecar or provide the native IPC boundary.

### Browser client from a source checkout

Build the browser bundle, point the daemon at it, and then open the daemon origin:

```sh
pnpm build:web
SOULMATE_WEB__CLIENT_DIR=apps/web/dist uv run --locked soulmate serve
```

Open `http://127.0.0.1:7432/`. The standalone Vite command is useful for UI-only
work, but the browser client intentionally calls the origin that served it; use
the daemon-served bundle for an end-to-end browser flow.

### Mobile client

```sh
pnpm --filter @soulmate/mobile start
```

The mobile app is a client, not a host. A physical device needs LAN access enabled
from the desktop Devices screen, TLS pairing, and a native build with certificate
pinning. The repository gate tests the TypeScript pairing rules but does not build
or verify native iOS/Android packages.

## Build artifacts

```sh
# all Python source distributions and wheels -> dist/
pnpm build:python

# browser bundle -> apps/web/dist/
pnpm build:web

# desktop React production bundle -> apps/desktop/dist/
pnpm build:desktop

# standalone daemon sidecar -> apps/desktop/src-tauri/binaries/
pnpm --filter @soulmate/desktop sidecar:build

# native installer -> apps/desktop/src-tauri/target/release/bundle/
pnpm --filter @soulmate/desktop tauri build
```

`build:desktop` builds browser and desktop frontend assets; it does not create a
native installer. `tauri build` runs the sidecar/frontend build hooks and creates
the installer for the current operating system. The artifacts are unsigned; code
signing, notarization, and automatic updates are not implemented.

## Validate a change

```sh
pnpm check       # lint, formatting, strict types, and Python/TS/Rust tests
pnpm check:all   # also lockfiles, all hooks, Python packages, and web/desktop builds
```

Use the focused commands and CI expectations in [quality gates](quality-gates.md).

## Troubleshooting

- `uv: command not found`: add the uv install directory to the shell and editor
  `PATH`, then reopen the terminal or editor.
- `Corepack` or `pnpm` version errors: run the pinned Corepack commands above and
  verify `pnpm --version` reports `11.21.0`.
- `Configuration file not found`: `SOULMATE_CONFIG_FILE` or `--config` selects an
  explicit file and therefore requires it to exist. Create the file or unset the
  selector.
- Chat says the provider is unavailable: configure a non-empty model name and
  ensure the model service is running. `doctor` reports `provider_check` as
  `not_configured` when the model name is empty.
- Chat answers and reports pending learning: this is the normal decoupled flow;
  the reply is already retained while an ID-only background job extracts Evidence.
  Failed attempts retry with exponential backoff and never reach the Personal
  Model. If the model does not update later, confirm the exact model identifier,
  quota, and JSON reliability, then inspect the bounded desktop daemon log without
  pasting private prompts or credentials.
- Port 7432 is already in use: stop the existing daemon or set the same alternate
  `server.port` for every CLI command and client. A daemon orphaned by a desktop
  development build from before the managed-shutdown fix must be stopped once;
  on macOS/Linux, identify it with
  `lsof -nP -iTCP:7432 -sTCP:LISTEN` and send that verified Soulmate PID `TERM`.
- The daemon root returns JSON/404 instead of the web UI: build `apps/web/dist`
  and set `web.client_dir` or `SOULMATE_WEB__CLIENT_DIR`.
- Tauri fails before compiling Rust: install the platform-specific native
  prerequisites above. On Linux, compare installed packages with the CI list.
- `doctor` is unhealthy while `serve` is running: use `status` for a live daemon;
  `doctor` also checks whether the configured port is free.
- A source-run daemon may end with exit code 130 and print a `KeyboardInterrupt`
  traceback after `Ctrl+C`. If the log first reports that application shutdown
  completed, the daemon and worker stopped normally; this is a known development
  CLI shutdown-noise issue.
