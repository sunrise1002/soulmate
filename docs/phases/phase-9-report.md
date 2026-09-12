# Phase 9 report — MCP & External Personal Intelligence API

## Authorization and scope

Phase 9 was explicitly authorized on 2026-09-12. Work is limited to specification
tasks P9-01 through P9-06. Import, backup, connectors, raw-memory access, external
preference mutation, and delegated decision making are not authorized.

## Implementation plan

1. Add framework-independent service identity, API credential, and permission
   records plus repository ports to the kernel.
2. Persist identities, normalized scopes, and API-key hashes through a migration,
   with restart-safe rotation and revocation.
3. Extend the single authorization boundary so external API routes require an
   API key even on loopback and enforce one exact scope per operation.
4. Add privacy-minimal external REST operations backed by the existing model,
   decision, outcome, and similarity application services.
5. Implement the six specified MCP tools over stdio and route them through the
   scoped REST boundary rather than opening persistence directly.
6. Audit every external request locally without arguments or credentials, and add
   an owner-only desktop screen for identities, scopes, keys, and recent audit.

## Delivered work

| Task | Result |
| --- | --- |
| P9-01 Service Identity | Each external application has an owner-created, separately revocable identity with a name, optional description, scopes, credentials, and timestamps |
| P9-02 Scope System | Five normalized least-privilege scopes gate model summary, preference summary, prediction/similarity, decision recording, and outcome recording; no raw-memory or preference-write scope is exposed |
| P9-03 API Keys | 256-bit URL-safe secrets are shown once; SQLite stores only SHA-256 hashes plus non-secret credential identifiers and usage/revocation timestamps; keys rotate and revoke independently |
| P9-04 MCP Server | `decision-twin mcp` provides `predict_choice`, `rank_options`, `get_preference_summary`, `find_similar_decisions`, `record_decision`, and `record_outcome` over newline-delimited stdio JSON-RPC |
| P9-05 Audit | Every authenticated, denied, validation-failed, or unexpected-failure external request records local identity/credential metadata, method, path, and status without request bodies or keys |
| P9-06 Permission UI | Desktop External Agents creates identities and keys, shows allowed and denied capabilities, changes scopes, rotates/revokes keys and identities, and displays recent local audit events |

SQLite migration `0007_phase_9` adds `service_identities`,
`service_identity_scopes`, and `api_credentials`. External request authorization
remains inside the Phase 7 boundary, but external paths deliberately never inherit
loopback owner authority. Remote service-key use additionally requires the owner
to enable the existing TLS LAN listener.

The MCP adapter is transport-only. It holds an API key supplied by the launching
agent configuration, calls the daemon's scoped endpoints, and never imports a
storage adapter or reads SQLite. The adapter is available as both the
`soulmate-mcp` console entry point and the packaged daemon's `mcp` subcommand.

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result |
| --- | --- | --- | --- |
| P9-T01 | New identity with known scopes | Normal | Identity and first credential are created; usable key is returned once |
| P9-T02 | Persisted credential | Storage privacy | Database contains only the hash and never the usable key or secret |
| P9-T03 | Unknown or empty scope set | Invalid format | Identity or permission change is rejected |
| P9-T04 | Correct key and exact scope | Normal | External operation succeeds and identifies the service principal |
| P9-T05 | Correct key without required scope | Least privilege | Request returns 403 and does not execute the operation |
| P9-T06 | Missing, malformed, or unknown key | Authentication | Request returns a generic 401 without personal data |
| P9-T07 | Key used after daemon restart | Persistence | Authentication and scopes still work |
| P9-T08 | Credential or identity revoked | Revocation | The next request returns 401 |
| P9-T09 | Scope changed | Permission boundary | The next request uses the replacement scope set |
| P9-T10 | Prediction request | Privacy | Response contains rankings and version metadata but no raw evidence, events, or memories |
| P9-T11 | Preference summary request | Privacy | Response contains derived values and confidence only, without evidence identifiers |
| P9-T12 | Similar-decision request | Privacy | Response contains identifier, domain, and similarity only |
| P9-T13 | Decision and outcome scopes separated | Authorization | Each write requires its own scope; external outcome response omits notes |
| P9-T14 | Successful or denied external request | Audit | Local log records identity where known, operation, and status without payload or key |
| P9-T15 | MCP initialize and tools/list | Protocol | Client negotiates the protocol and sees exactly the six specified tools |
| P9-T16 | MCP tools/call | Integration boundary | Adapter calls the scoped daemon route and returns a standard text content result |
| P9-T17 | Packaged daemon sidecar | Packaging | Frozen executable starts `mcp` and completes the MCP initialize handshake |
| P9-T18 | SDK identifier contains `/` | Invalid path data | Identity and credential identifiers are URL encoded |

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24, pnpm 11.21.0,
and Rust completed through `pnpm check:all`, followed by a clean sidecar rebuild
and frozen MCP initialize smoke test:

| Check | Result |
| --- | --- |
| Frozen Python and pnpm lockfiles | Passed |
| Ruff lint and formatting | Passed; 143 workspace files |
| Strict mypy | Passed; 88 source files |
| Python unit, integration, and evaluation tests | Passed; 247 total with two unchanged upstream warnings |
| SDK, web, mobile, and desktop ESLint, Prettier, and TypeScript | Passed |
| SDK, web, mobile, and desktop tests | Passed; 83 client tests |
| Rust formatting, Clippy with warnings denied, and native shell tests | Passed; 4 tests |
| Repository pre-commit hooks | Passed |
| Python package builds | Passed; five packages including `soulmate-mcp` |
| Web and desktop production builds | Passed |
| Clean PyInstaller sidecar rebuild and MCP initialize smoke | Passed on macOS arm64 |

Local results do not imply remote GitHub Actions passed.

## Known issues and limitations

- MCP currently uses local stdio. Streamable HTTP or another remote MCP transport
  is not implemented; remote callers may use the scoped REST API over the existing
  opt-in TLS listener.
- External decision tools require normalized structured features. They do not call
  an LLM to infer features, preventing an external tool call from causing hidden
  model-provider egress.
- Prediction and ranking tools persist their decision and versioned prediction so
  every prediction remains reproducible. Bulk cleanup of externally submitted
  decisions is not available.
- Similar-decision output deliberately omits question text, option content, and
  resolutions. Agents receive identifiers, domain, and deterministic scores only.
- API keys cannot be recovered after creation. Rotation creates a replacement key;
  the owner then revokes the old credential.
- Audit retention and audit deletion controls are not implemented. Audit events
  remain local and store operational metadata only.
- The desktop permission workflow was typechecked and component-tested, but no new
  native iOS or Android build or device run was performed.
- Remote CI and packaged MCP smoke tests on Windows and Linux remain unverified.

## Phase 10 handoff

Phase 9 exit criteria pass locally: an MCP-compatible external agent can ask which
structured option the owner is most likely to prefer and receive a versioned,
privacy-minimal result without the owner's complete personal database.

Phase 10 may begin only after explicit authorization. Backup, restore, and export
must account for service identities and audit records while excluding usable
credentials by default; no Phase 10 work has started.
