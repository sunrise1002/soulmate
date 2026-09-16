# Phase 6 report — Desktop Product

## Authorization and scope

Phase 6 was explicitly authorized on 2026-09-12. Work is limited to specification
tasks P6-01 through P6-07. Mobile/web clients, LAN pairing, MCP, active learning,
outcomes/regret, Advise Me, signing, automatic updates, and later integrations are
not authorized.

## Implementation plan

1. Build a Tauri 2 shell with a React and TypeScript frontend.
2. Freeze the daemon as a target-specific PyInstaller sidecar and smoke-test it.
3. Manage sidecar start, stop, restart, health, exit cleanup, and bounded logs.
4. Implement Chat, Decide, My Model, Decision History, and Settings screens.
5. Configure Ollama and generic OpenAI-compatible providers without exposing
   saved credentials to the webview.
6. Enforce strict-local, hybrid, and offline provider URL rules at the native
   boundary and retain daemon-side egress enforcement.
7. Add history and evidence-deletion APIs, tests, cross-platform packaging CI,
   documentation, and complete local verification.

## Delivered work

| Task | Result |
| --- | --- |
| P6-01 Tauri shell | Tauri 2 native application with a responsive React 19, TypeScript, Vite, local-only content security policy, desktop icons, and locked pnpm/Cargo dependencies |
| P6-02 Daemon sidecar | Reproducible target-suffixed PyInstaller one-file daemon build containing packaged migrations and evaluation data; build script smoke-tests CLI startup and packaged evaluation |
| P6-03 Service management | Native start, stop, restart, health polling, startup timeout, process-exit handling, application-exit cleanup, status, PID, and bounded stdout/stderr log tail |
| P6-04 Main UI | Chat with conversation history, Decision submission/prediction/resolution, My Model, prediction history, and service/provider Settings screens |
| P6-05 Provider configuration | Local Ollama and generic local/cloud OpenAI-compatible endpoint configuration with model selection; API keys live in the OS credential store and are never returned to the webview |
| P6-06 Privacy mode | Strict-local, hybrid, and offline controls with native URL validation, fixed loopback daemon binding/proxying, disabled redirects, and existing centralized daemon egress enforcement |
| P6-07 My Model | Preference summary and context, evidence provenance inspection, correction/add flow, and evidence deletion followed by deterministic model rebuild |

The daemon API now offers latest-first local-owner conversation and decision
history reads. Evidence deletion uses the existing repository boundary and creates
a fresh immutable model snapshot after removing the selected source; no persistent
schema change was required.

The webview cannot supply a destination origin. Its native proxy permits only
GET, POST, and DELETE on `/v1/` paths at fixed `127.0.0.1:7432`, rejects traversal,
query, and fragment input, and does not follow redirects. The daemon remains the
only composition root and the Python kernel has no desktop dependency.

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24, pnpm 11.21.0,
and Rust:

| Check | Result |
| --- | --- |
| Root complete gate, `pnpm check:all` | Passed |
| Locked Ruff lint and formatting | Passed; 105 Python files formatted |
| Strict mypy | Passed; 56 source files |
| Python unit, integration, and evaluation tests | Passed; 92 total with two unchanged upstream warnings |
| Frontend ESLint, Prettier, and TypeScript | Passed |
| Frontend component tests | Passed; 1 test file |
| Rust formatting and Clippy with warnings denied | Passed |
| Native shell tests | Passed; 2 tests |
| Python package builds | Passed; four source distributions and wheels |
| PyInstaller daemon sidecar and smoke tests | Passed; macOS arm64 one-file sidecar |
| Production frontend build | Passed; 1,875 modules transformed |
| Native application and installer build | Passed; `Soulmate.app` and unsigned macOS arm64 DMG |
| Frozen lockfiles and all repository hooks | Passed |

Local results do not imply remote GitHub Actions passed.

## Known issues and limitations

- Only the macOS arm64 sidecar, application bundle, and DMG were built locally.
  Native Windows MSI/NSIS and Linux DEB/AppImage builds are configured in the CI
  matrix but remain remotely unverified.
- Installers are unsigned and unnotarized. Operating systems can display an
  unknown-publisher warning; release signing and automatic updates are deferred.
- Real Ollama and remote OpenAI-compatible inference were not exercised because
  verification used synthetic providers and offline fixtures. Users must configure
  an installed/reachable model before chat and natural option extraction work.
- Credential-store behavior depends on the host operating system and desktop
  session. The native boundary has automated validation tests, but interactive
  credential prompts are not covered by headless CI.
- The desktop shell assumes one application-managed daemon on fixed port 7432.
  It reports startup failure if another process owns that port; shared discovery
  and secure multi-device access belong to Phase 7.
- The two upstream Starlette test-client compatibility warnings remain unchanged.

## Maintenance correction — 2026-09-16

The original stop path used the shell plugin's force-kill operation against the
PID returned for the PyInstaller one-file bootloader. On macOS, that could kill
the bootloader while leaving its Python child serving port 7432, so a subsequent
Save and restart failed with `address already in use`.

The managed sidecar now listens for a private stdin shutdown command and treats
control-pipe closure as desktop exit. The shell waits for the complete sidecar to
terminate before starting its replacement, checks for an occupied port before it
spawns, and no longer force-kills the one-file bootloader after a health timeout.
The sidecar build smoke test runs two consecutive start/clean-stop cycles on the
same loopback port. No public API, persistent schema, privacy boundary, or phase
scope changed.

Verification passed locally on macOS arm64: `pnpm check:all`, 304 Python tests,
87 TypeScript tests, seven native Rust tests, Ruff formatting/lint, strict mypy,
Prettier/ESLint/TypeScript checks, Rustfmt, Clippy with warnings denied, all
repository hooks, seven Python package builds, and the web/desktop production
builds. A clean PyInstaller sidecar rebuild passed the new two-cycle managed
restart smoke test, and the development desktop loaded the saved Hybrid provider
configuration with a healthy daemon. Remote CI and packaged Windows/Linux
behavior remain unverified.

## Phase 7 handoff

Phase 6 exit criteria pass locally: the platform installer includes both the
desktop interface and daemon runtime, so a normal user does not need Python,
Node.js, Docker, a terminal, or a separately managed database after installation.

Phase 7 may begin only after explicit authorization. It may add mobile/web clients
and secure LAN pairing around the existing loopback-first service, but must not
weaken owner-controlled authorization, privacy, or evidence provenance.
