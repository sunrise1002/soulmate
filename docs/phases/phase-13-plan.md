# Phase 13 plan — Decision I/O and trusted provenance

## Status and authorization

This plan was recorded on 2026-09-14 after review of the post-MVP architecture
delta and the repository delivered through Phase 12.

Planning is approved. The owner authorized implementation on 2026-09-23; results
are recorded in the [Phase 13 report](phase-13-report.md). This document
authorizes neither Phase 14 work nor automatic continuation beyond the Phase 13
exit review.

The 2026-09-17 provider-compatibility maintenance increment does not change this
plan's scope, ordering, migration number, or authorization gate. It strengthens the
existing Phase 3 LLM adapter boundary only. Phase 13 Decision I/O remains
provider-neutral and must not depend on a negotiated model-output mode; any future
LLM-assisted detection remains outside Phase 13 as already stated below. The
subsequent chat-path hardening that moved Evidence extraction to a backoff-enabled
durable job also leaves Phase 13 scope, ordering, persistence plan, and authorization
gate unchanged.

On 2026-09-17 the owner assigned migration `0011` to the
[key consistency increment](key-consistency-increment-plan.md). Phase 13 therefore
uses migration `0012_phase_13_decision_io` on top of revision `0011`. If Phase 13 is
authorized before that increment ships, the two migrations must be renumbered
together before either is merged. Phase 13 scope, ordering, and authorization gate
are otherwise unchanged.

## Inputs and precedence

Phase 13 must preserve the existing technical specification unless this plan and
a subsequently accepted ADR explicitly change one of its assumptions. The main
inputs are:

- the root technical specification and its phase execution protocol;
- the Phase 12 report and its delegation/security handoff;
- the post-MVP architecture delta concerning Decision I/O, passive observation,
  source provenance, outcome semantics, and shadow evaluation;
- ADR-003, ADR-004, ADR-008, ADR-010, ADR-012, and ADR-013;
- the current implementation rather than the phase reports alone.

When these documents differ, the architecture and privacy invariants in the root
specification remain binding. Phase 13 may define the new Decision I/O boundary,
but it must not weaken evidence provenance, owner authorization, local-first
storage, or the independent Personalization Kernel.

## Strategic outcome

The next product hypothesis is:

> Can Soulmate learn continuously from authorized real workflows and reduce the
> number of preference decisions that require owner intervention without
> increasing incorrect personalization or weakening security boundaries?

The repository cannot test that hypothesis safely until every externally
observed decision, correction, action, and outcome has a normalized identity,
acquisition record, actor classification, correlation path, retention policy,
and explicit evidence eligibility. Phase 13 establishes that foundation before
any Codex, Claude Code, Git, browser, or application-specific capture adapter is
allowed to produce learning input.

## Existing baseline

The following capabilities are already implemented and must be reused rather
than rebuilt:

| Capability | Current state | Phase 13 implication |
| --- | --- | --- |
| Decision lifecycle | Decisions, options, predictions, resolutions, and owner outcomes persist in SQLite | Add origin and observation provenance without replacing prediction logic |
| Evidence model | Evidence is provenance-bearing and derived state is rebuildable | External observations may become Evidence only through an explicit promotion policy |
| Behavioral and wellbeing separation | Predict Me and Advise Me are versioned separately | Technical results must not silently become owner wellbeing |
| External access | Service identities, scoped hash-only credentials, and metadata-only audit exist | Reuse the single authorization boundary and introduce only scopes required by Phase 13 |
| MCP | A local stdio adapter exposes six intelligence and three delegation tools | Preserve active consultation; do not add passive capture tools to the model-visible MCP surface |
| Connectors | Pull-based connectors produce source-linked, idempotent RawEvents under owner consent | Reuse provenance and deletion principles, but do not force push-based agent hooks into the pull API |
| Delegation | Owner policies issue prediction-bound authority under strict impact and confidence rules | Decision I/O observations never imply delegated authority |

Review-time inspection also established these gaps:

- `Source` records do not describe provider, acquisition method, consent,
  declared data classes, author scope, retention, or adapter/parser versions.
- `RawEvent` has no schema version, external idempotency key, actor type,
  evidence-eligibility classification, correlation ID, or causation link.
- external decision consultation persists decisions without a source-linked
  RawEvent or an explicit consultation/observation purpose.
- an external service can currently submit an outcome using a record whose
  domain meaning is owner-reported satisfaction and regret.
- decision and outcome ingestion do not share the idempotency guarantees already
  present for connector items and delegation requests.
- technical success, owner acceptance, modification, reversion, satisfaction,
  and regret cannot be represented as separate observations.

## Post-MVP roadmap

Only Phase 13 is detailed and may become the next active implementation phase.
Later phases are directional sequencing, not authorized implementation plans.

| Phase | Direction | Dependency and stop gate |
| --- | --- | --- |
| 13 | Decision I/O and trusted provenance | Current planned phase; stop for owner review after its exit criteria pass |
| 14 | Provider-neutral agent integration framework and one Codex vertical slice | Requires stable Phase 13 ingestion contracts and separate authorization |
| 15 | Passive decision and correction candidate detection | Requires replayable events from one real adapter; inferred corrections remain review-only initially |
| 16 | Explicitly connected Git/repository outcome observation | Requires decision correlation metrics and strict separation of technical and user outcomes |
| 17 | Shadow prediction and real-workflow evaluation | Requires reliable resolution matching and must not influence the observed choice |
| 18 | Owner Decision Service v2 and task-scoped context steering | Requires shadow baselines so steering impact can be measured rather than assumed |
| 19 | A second live agent adapter and one-click connection lifecycle | Validates provider neutrality after the first vertical slice |
| 20 | Delegation hardening using reversibility, domain policy, and measured calibration | Requires sufficient real-world evidence; high and safety-critical automation remains prohibited |
| 21 | Selected general-life connectors | Requires a validated use case; connector breadth is not an early success metric |

## Phase 13 goal

Create one provider-neutral, privacy-bounded Decision I/O path that can ingest and
correlate authorized external decisions, resolutions, and outcome observations
without allowing an external agent to impersonate owner evidence or owner
wellbeing.

## Scope

Phase 13 includes:

- versioned acquisition and consent metadata for sources;
- a versioned normalized external event envelope;
- daemon-assigned actor and evidence-eligibility policy results;
- idempotent event ingestion and correlation;
- decision origin and purpose metadata;
- separate resolution and outcome observations;
- separate technical, user-behavior, and owner-reported outcome semantics;
- atomic SQLite persistence and migration `0012_phase_13_decision_io`;
- scoped REST ingestion and owner inspection/deletion surfaces;
- compatibility behavior for existing external decision and outcome APIs;
- typed TypeScript SDK support;
- deterministic unit, integration, migration, restart, deletion, privacy, and
  packaged-sidecar verification;
- architecture, security, API, changelog, phase-status, and phase-report updates.

## Explicit non-goals

Phase 13 does not include:

- Codex or Claude Code hook installation;
- provider-specific event parsing;
- Git working-tree or history observation;
- browser, accessibility, private-cache, or network-interception capture;
- automatic LLM-based decision, correction, or outcome detection;
- automatic preference Evidence from inferred user overrides;
- shadow prediction execution or continuous evaluation;
- new MCP ingestion tools visible to an external model;
- remote MCP transport;
- AI Gateway proxying;
- notification delivery;
- autonomous third-party side-effect execution;
- relaxed delegation thresholds or safety-critical automation.

## Architecture boundary

The target flow is:

```text
Provider-specific adapter
        │
        ▼
External authentication and source capability check
        │
        ▼
Decision I/O validation and policy classification
        │
        ├── daemon assigns profile and source
        ├── daemon derives evidence eligibility
        ├── idempotency and payload limits
        └── correlation and causation validation
        │
        ▼
RawEvent plus lifecycle observation in one transaction
        │
        ├── DecisionEvent
        ├── ResolutionObservation
        └── OutcomeObservation
        │
        ▼
Explicit promotion policy
        │
        ├── confirmed owner choice → canonical resolution/Evidence
        ├── confirmed owner report → wellbeing outcome
        ├── technical result → technical history only
        └── agent/third-party content → contextual or ignored
```

Provider payload schemas, Pydantic request models, authentication, and HTTP stay
in adapters and the daemon. Infrastructure-independent records, policy rules, and
required repository ports belong in `packages/core-python`. SQLite is implemented
only in `packages/storage-sqlite`, and the daemon remains the composition root.

## Required invariants

1. An external caller cannot choose `profile_id`, internal `source_id`, consent,
   evidence eligibility, impact, or delegation authority.
2. Every externally ingested event references an owner-approved source and an
   active service identity with the exact required scope.
3. Agent, assistant, system, and third-party content cannot independently mutate
   the Personal Model.
4. Technical success does not imply owner acceptance, satisfaction, or regret.
5. A decision prediction is never security authorization. Decision I/O does not
   bypass runtime approvals, sandboxing, or the Phase 12 Policy Engine.
6. Retrying identical input is idempotent. Reusing an external event ID with
   different canonical content is rejected.
7. Events may arrive out of order. Unmatched observations are retained safely and
   never forced into an unrelated decision lifecycle.
8. Audit events contain operational identifiers, counts, states, and reason codes,
   but not prompts, tool input/output, file contents, diffs, credentials, or
   Personal Model payloads.
9. Source deletion removes derivative data according to provenance and triggers a
   deterministic model rebuild when Evidence changed.
10. Fixed inputs, policy version, and algorithm version produce deterministic
    eligibility and promotion decisions without an LLM.

## Proposed domain vocabulary

The exact representation must be finalized in ADR-014 before schema code lands.
The intended vocabulary is:

```text
AcquisitionMethod
ConsentMode
RawRetentionPolicy
EventActorType
EvidenceEligibility
DecisionOrigin
DecisionPurpose
ObservationStatus
OutcomeKind
TechnicalOutcomeStatus
UserDisposition
```

Recommended values include:

```text
EventActorType:
    owner
    agent
    assistant
    system
    third_party
    unknown

EvidenceEligibility:
    eligible
    contextual_only
    ignored

DecisionPurpose:
    owner_interactive
    agent_consultation
    observed
    shadow

OutcomeKind:
    technical
    user_behavior
    owner_reported

UserDisposition:
    accepted
    modified
    replaced
    reverted
    unknown
```

`eligible` means the event may be considered by a later validated extractor or
promotion rule. It does not mean that ingestion creates Evidence automatically.

## Implementation increments

### P13-01 — ADR and contract freeze

Create ADR-014 covering:

- Decision I/O as an application boundary rather than a provider integration;
- event, actor, eligibility, observation, and promotion semantics;
- the trust distinction between an actor reported by an adapter and authority
  assigned by the daemon;
- transactional ingestion and idempotency boundaries;
- compatibility treatment of existing REST and MCP behavior;
- source deletion and retention implications;
- why the pull-based connector SDK and push-based agent integration API remain
  separate while sharing normalized source/event concepts.

No migration or public API should be implemented before this ADR and the request/
response examples in this plan agree.

### P13-02 — Source provenance model

Extend `Source` and its repository contract with versioned metadata for:

```text
provider
acquisition_method
consent_mode
consent_at
data_classes
author_scope
raw_retention_policy
adapter_version
parser_version
policy_profile_version
```

Requirements:

- normalize enum-like values in the core;
- use immutable records and timezone-aware UTC timestamps;
- validate data classes and author scope at source creation;
- let only the owner create, approve, or change acquisition capabilities;
- preserve existing import and connector source behavior;
- return sanitized source metadata through owner-only inspection APIs.

### P13-03 — Normalized event envelope

Extend `RawEvent` or introduce a closely linked Decision I/O envelope with:

```text
schema_version
external_event_id
actor_type
evidence_eligibility
correlation_id
causation_event_id
content_fingerprint
```

Use a small provider-neutral taxonomy initially:

```text
interaction
decision_candidate
decision_resolution
agent_proposal
user_override
action
technical_outcome
user_outcome
correction
context
```

The daemon derives `evidence_eligibility` from the owner-approved source,
acquisition method, event type, actor type, and a recorded policy-profile version.
The request must not contain a trusted eligibility field.

Enforce bounded JSON content, supported schema versions, UTC timestamps, stable
external IDs, declared event/data classes, and a uniqueness constraint over
`(source_id, external_event_id)`.

### P13-04 — Decision lifecycle observations

Add source provenance and purpose to externally created decisions. Preserve stable
external decision and option identifiers so later events do not rely on labels or
daemon-generated IDs.

Represent non-canonical input as observations:

```text
ResolutionObservation
OutcomeObservation
```

An observation has:

```text
source event
reported actor
kind
status
correlation confidence where applicable
linked decision when known
created and confirmed timestamps
```

Supported states are initially:

```text
unmatched
pending
confirmed
rejected
```

Owner-authenticated explicit choices may be promoted deterministically to the
existing `DecisionResolution` path. External agent reports remain observations
unless a source-specific rule established by the owner permits a narrower
promotion. Satisfaction and regret require owner confirmation.

### P13-05 — Atomic ingestion repository and service

Define the smallest core repository port needed to atomically persist:

```text
RawEvent
+ idempotency identity/fingerprint
+ correlation links
+ lifecycle observation or explicit decision projection
```

The SQLite adapter must commit all records or none. Identical retries return the
original result; conflicting retries return a stable conflict error. A later event
may attach an unmatched observation without rewriting the original event.

Keep LLM and network calls out of this path. Model rebuilding may occur after the
ingestion transaction and must remain recoverable through the existing evidence-
revision mechanism.

Expected code locations include:

```text
packages/core-python/src/soulmate_core/decision_io/
packages/core-python/src/soulmate_core/domain/ports.py
packages/storage-sqlite/src/soulmate_storage_sqlite/
apps/daemon/src/soulmate_daemon/decision_io.py
```

These are intended locations, not permission to introduce unused abstractions.

### P13-06 — Migration and conservative backfill

Create migration `0012_phase_13_decision_io` with indexes, constraints, foreign
keys, and new observation records required by the accepted ADR.

Backfill conservatively:

- live owner conversation events may be marked owner-authored and eligible;
- imported assistant messages are contextual only;
- connector events remain contextual until a connector-specific acquisition
  policy permits eligibility;
- existing predictions use the interactive/consultation purpose;
- existing owner API resolutions retain their canonical resolution behavior but
  receive explicit legacy provenance;
- legacy outcomes whose actor cannot be proven become `legacy_unverified`; they
  remain visible but must not gain stronger trust through migration.

Do not infer consent, provider, or owner authorship merely because data is stored
locally. Migration tests must start from a real revision `0011` schema fixture.

### P13-07 — REST authorization and compatibility

Add a bounded push-ingestion surface for installed agent adapters. Do not expose
an unrestricted `RawEvent` write endpoint.

Candidate least-privilege scopes are:

```text
interaction:record
decision:record
decision:resolution:record
outcome:observe
```

Finalize their exact names in the ADR and security tests. Each route accepts only
the event families its scope permits.

Compatibility requirements:

- existing `predict_choice`, `rank_options`, and `record_decision` clients receive
  source and purpose metadata without losing their current response fields;
- existing external `record_outcome` becomes a compatibility wrapper that records
  an observation rather than asserting owner wellbeing;
- owner-facing outcome recording continues to create confirmed owner-reported
  wellbeing;
- deprecated behavior is documented before removal;
- passive recording remains REST-based and is not added to the model-visible MCP
  tool list in Phase 13.

### P13-08 — Retention, inspection, and deletion

Support explicit retention per source and data class. Initial safe defaults are:

- tool and command activity: metadata only;
- full prompts and assistant responses: not captured by default;
- structured decisions and corrections: retained only under explicit consent;
- full file content and diffs: separate opt-in and otherwise excluded;
- audit: metadata only.

Do not claim `delete_after_extraction` support until an extraction job has a
durable success marker and deletion can be retried safely. Unsupported retention
modes must be rejected rather than silently ignored.

Owner-only APIs must allow the owner to inspect a source's capabilities, retention
policy, event counts, and observation states, then remove the source and its
provenance graph. Deletion must account for decisions, resolutions, observations,
Evidence, snapshots, predictions, advice, and retained audit requirements without
leaving foreign-key-invalid records.

### P13-09 — SDK, product visibility, and documentation

Add typed TypeScript SDK contracts for source registration/inspection, bounded
event ingestion, idempotent results, and observation review where the accepted
API requires them.

Desktop work is limited to the minimum owner controls needed to:

- see the new source metadata and granted capabilities;
- distinguish observations from confirmed outcomes;
- confirm or reject an owner-outcome observation;
- remove a source and understand the deletion consequence.

Do not build Codex/Claude connection installers in this phase.

Update:

- ADR-014 and the architecture index;
- security and API documentation;
- public SDK documentation;
- `CHANGELOG.md`;
- `docs/phase-status.md`;
- this plan into a completed `phase-13-report.md` or extend it with delivered
  results, verification, limitations, and handoff notes according to the
  repository's established phase-report convention.

## Test perspectives

| Case ID | Input or precondition | Perspective | Expected result |
| --- | --- | --- | --- |
| P13-T01 | Owner-approved source and valid event | Normal ingestion | Event and projection commit with complete provenance |
| P13-T02 | Identical retry with the same external event ID | Idempotency | Original result is returned and no duplicate is written |
| P13-T03 | Same external event ID with different content | Integrity | Request is rejected without mutation |
| P13-T04 | Agent output presented as owner preference | Contamination | Daemon assigns contextual-only or ignored eligibility |
| P13-T05 | Agent submits satisfaction or regret | Wellbeing boundary | An unconfirmed observation is stored; owner wellbeing is unchanged |
| P13-T06 | Owner confirms a valid explicit choice | Learning path | Canonical resolution and provenance-bearing choice Evidence are created once |
| P13-T07 | Tests pass and code is merged | Technical outcome | Technical history changes; owner satisfaction does not |
| P13-T08 | Outcome arrives before its decision | Event ordering | Observation remains unmatched and can correlate later |
| P13-T09 | Caller lacks the exact scope | Authorization | Shared boundary rejects the request and records sanitized audit metadata |
| P13-T10 | Event actor/type is outside source declaration | Consent boundary | Event is rejected before persistence |
| P13-T11 | Unsupported schema, naive timestamp, oversized content | Validation | Request is rejected without partial state |
| P13-T12 | Daemon restart after accepted events | Persistence | Idempotency, provenance, correlation, and observation state survive |
| P13-T13 | Owner removes a source with derivative Evidence | Privacy deletion | Provenance graph is removed and the Personal Model is rebuilt |
| P13-T14 | Migration from revision `0011` | Upgrade | Existing data remains readable with conservative provenance |
| P13-T15 | Backup/export/restore after migration | Portability | New records restore and migrate without usable external credentials |
| P13-T16 | Audit and failure paths | Payload privacy | Prompts, content, diffs, keys, and outcome notes are absent from logs/audit |
| P13-T17 | Core package import graph | Architecture | Core remains free of FastAPI, SQLAlchemy, provider, connector, and runtime dependencies |
| P13-T18 | Existing REST/MCP clients | Compatibility | Supported reads/predictions remain valid and changed write semantics are explicit |

## Verification protocol

Use focused tests while implementing each increment, then run the complete local
gate from the repository root:

```sh
pnpm check:all
```

Also run and record:

```sh
uv run --locked pytest tests/unit
uv run --locked pytest tests/integration
uv run --locked pytest tests/evaluation
uv build --all-packages
pnpm --filter @soulmate/desktop sidecar:build
```

Perform a clean packaged-sidecar smoke test covering migration `0011 → 0012`, MCP
initialization, one valid event, one identical retry, one conflicting retry,
restart persistence, and source deletion. Cross-platform installer and sidecar
behavior belongs in the existing CI matrix. Local success must never be reported
as remote CI success.

## Exit criteria

Phase 13 is complete only when:

- every externally ingested decision lifecycle record has source, acquisition,
  consent, actor, policy-version, and event provenance;
- an external caller cannot assign its own evidence eligibility or owner authority;
- agent-only content cannot independently change derived owner beliefs;
- agent-reported outcomes cannot become owner satisfaction or regret without owner
  confirmation;
- technical and user outcome semantics are separately stored and returned;
- identical retries are idempotent and conflicting retries are rejected;
- out-of-order observations remain recoverable and never attach silently to an
  unrelated decision;
- source deletion removes derivative data and deterministic rebuilding passes
  after restart;
- migration, backup, export, restore, SDK, REST, existing MCP compatibility, audit
  privacy, and packaged-sidecar tests pass locally;
- ADR, security, API, user documentation, changelog, phase status, verification
  results, known limitations, and the Phase 13 handoff are complete;
- remote CI status is reported factually.

## Phase 13 stop gate

After the exit criteria pass, stop and request owner review. Do not implement a
Codex hook, Claude Code hook, Git observer, shadow predictor, MCP v2 surface, or
delegation change until a new phase has been planned from the completed Phase 13
report and explicitly authorized.
