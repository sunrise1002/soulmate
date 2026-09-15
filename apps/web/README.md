# `@soulmate/web`

Browser client for the local Soulmate service, built with React and Vite and
served by the daemon from the service root.

Screens: Connect, Chat, Decide, My Model, and History. It talks only to the origin
that served it, so the daemon remains the single source of personal data.
Decide displays separate Predict Me and Advise Me results and records outcome
feedback. My Model offers uncertainty-targeting pairwise questions.

A browser on the owner's own machine reaches the service over loopback and needs
no credential. A browser on another device must first enable access from other
devices on the owner's machine, then enter a one-time pairing code on the Connect
screen. The issued credential is stored in `localStorage` and dropped as soon as
the owner revokes the device.

```sh
pnpm --filter @soulmate/web dev     # UI-only Vite development server
pnpm --filter @soulmate/web build   # bundle into apps/web/dist
pnpm --filter @soulmate/web check   # lint, format, typecheck, test
```

For an end-to-end browser flow from a source checkout, serve the production
bundle from the daemon so the UI and API share one origin:

```sh
pnpm build:web
SOULMATE_WEB__CLIENT_DIR=apps/web/dist uv run --locked soulmate serve
```

Then open `http://127.0.0.1:7432/`. See the root
[setup guide](../../docs/contributor-guide/setup.md) for configuration and other
run modes.

`pnpm build:web` runs before the desktop sidecar build, which copies the bundle
into the daemon package so an installed product serves it without Node.js.
