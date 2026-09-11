# Phase 3 report — Conversation and Evidence Extraction

## Authorization and scope

Phase 3 was explicitly authorized on 2026-09-11. Work is limited to specification
tasks P3-01 through P3-08. Decision prediction, embeddings, desktop/mobile clients,
MCP integration, and later phases are not authorized.

## Implementation plan

1. Add provider-neutral text and structured-generation contracts outside the
   kernel, a deterministic fake, and centrally policy-checked HTTP adapters.
2. Add persistent conversation and message domain records, ports, SQLite rows,
   repositories, and a packaged migration.
3. Implement `/v1/chat` as a daemon application workflow using bounded history
   and minimal compiled Personal Model context.
4. Validate fact, preference, goal, and constraint proposals with Pydantic, review
   risk, stamp provenance, store accepted Evidence, and rebuild derived state.
5. Test adapters without network, validation failures, review behavior, migration,
   chat learning, explainability, context selection, and restart persistence.
6. Run every local quality gate, build every package, and record actual results
   and limitations.

## Delivered work

| Task | Result |
| --- | --- |
| P3-01 Provider interface | Async provider-neutral text and structured-generation protocol in the infrastructure-side provider package |
| P3-02 Fake provider | Deterministic queued text and object responses with captured requests for offline tests |
| P3-03 Ollama | Local `/api/chat` adapter with native JSON-schema format and egress enforcement |
| P3-04 OpenAI-compatible | Generic `/chat/completions` adapter with JSON-schema response format and optional bearer credential |
| P3-05 Conversation | Migrated conversation/message persistence and `POST /v1/chat` with bounded history |
| P3-06 Extraction | Strict Pydantic schemas for facts, preferences, goals, and constraints before Evidence construction |
| P3-07 Review | Ordinary low-risk proposals auto-accept; named sensitive categories are withheld; accepted claims record model, algorithm, source event, and source message |
| P3-08 Context compiler | Deterministic lexical retrieval includes at most five relevant entries per model-state type and sends no unrelated model entries |

HTTP provider calls are lazy and occur only for chat. Both adapters invoke the
central egress policy immediately before a request. `strict_local` and `offline`
allow loopback endpoints only; `hybrid` additionally permits external
HTTPS. Provider failures do not include prompt, response, endpoint, or credential
content in public errors.

Each accepted conversational claim is linked to an immutable conversation-message
RawEvent and its source message. Providers never write Evidence or derived state
directly. The daemon validates and reviews proposals, repositories persist them,
and the deterministic Phase 2 rebuilder creates a new versioned snapshot.

## Verification

Local verification on macOS arm64 with Python 3.12.14:

| Check | Result |
| --- | --- |
| Locked Ruff lint | Passed |
| Locked Ruff formatting check | Passed |
| Strict mypy | Passed; 46 source files |
| Unit and integration tests | 76 passed (54 unit, 22 integration) |
| Phase 1/2 to Phase 3 migration | Passed with existing profile and model data preserved |
| Chat/restart behavior | Passed with history, extraction provenance, preferences, snapshots, and relevant context preserved |
| Provider adapter tests | Passed offline with deterministic fake HTTP transports |
| Full pre-commit suite | Passed |
| Core, daemon, provider, and SQLite source/wheel builds | Passed |
| Packaged migration inspection | Passed; migrations `0001_phase_1`, `0002_phase_2`, and `0003_phase_3` are present |
| Frozen pnpm installation | Passed |

Local results do not imply remote GitHub Actions passed. Remote CI has not yet been
observed for this phase.

## Known issues and limitations

- Extraction and model rebuild run synchronously in the chat request. Durable job
  offloading is deferred until measured local workloads require it.
- The V1 review policy blocks named sensitive target-key categories but is not a
  complete semantic safety classifier. Rejected proposals are counted but not
  persisted because a user review interface does not exist yet.
- Context selection uses deterministic lexical overlap and exact stored context;
  semantic retrieval and embeddings remain deferred.
- Conversation history is bounded to the latest 20 stored messages for provider
  calls. There is no public history/list/delete API in this phase.
- Provider credentials are accepted from process configuration and are not stored
  in SQLite. Native operating-system secret storage belongs to a later settings UI.
- Ollama and generic compatible endpoints are implemented, but local verification
  uses fake transports and does not assert availability of a user's model server.
- The two upstream Starlette test-client compatibility warnings remain unchanged.
- Remote CI verification remains unconfirmed.

## Phase 4 handoff

Phase 3 exit criteria pass locally. A user can chat through the daemon, express an
ordinary preference naturally, inspect provenance-bearing Evidence, observe the
derived preference and snapshot, restart, and continue the same conversation with
relevant Personal Model context.

Phase 4 may introduce the Decision MVP only after explicit authorization. It must
store the model snapshot used by every prediction, keep Predict Me separate from
advice, and keep deterministic scoring independent of LLM providers. Do not add
evaluation learning, clients, MCP, or later-phase integrations during Phase 4.
