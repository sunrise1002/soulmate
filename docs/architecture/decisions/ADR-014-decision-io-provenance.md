# ADR-014: Decision I/O and trusted provenance

Status: Implemented in Phase 13 (accepted 2026-09-23; implemented locally
2026-09-25).

## Context

Soulmate can already predict a choice for an external caller, record a decision, and
accept an outcome through scoped REST endpoints. Every one of those writes is
trusted as if the owner had produced it. A `Source` row records only a type and a
name, a `RawEvent` records only a type, content, and sensitivity, and the external
`record_outcome` endpoint writes `DecisionOutcome`, whose domain meaning is
owner-reported satisfaction and regret.

The next product hypothesis needs continuous learning from real authorized
workflows. Before any Codex, Claude Code, Git, or application adapter may produce
learning input, the repository must be able to answer, for every externally
observed record: where it came from, how it was acquired, under which consent, who
authored it, whether it may ever influence the Personal Model, which decision it
belongs to, and what happens to it when the owner deletes its source.

Phase 12 already solved the neighbouring problem for delegated action: an agent
supplies an intent, and the daemon — never the agent — assigns impact and
authority. Decision I/O must apply the same asymmetry to learning input.

## Decision

Introduce **Decision I/O** as an application boundary owned by the daemon rather
than a provider integration.

**Provenance is a first-class part of the source.** `Source` carries versioned
acquisition metadata: provider, acquisition method, consent mode and timestamp,
declared data classes, author scope, raw retention policy, adapter version, parser
version, and the policy-profile version used to classify its events. Only the
owner may create a source or change its acquisition capabilities.

**Events are a versioned normalized envelope.** `RawEvent` carries a schema
version, an optional external event ID, an actor type, an evidence-eligibility
classification, a correlation ID, a causation event ID, and a content fingerprint.
The provider-neutral event taxonomy is `interaction`, `decision_candidate`,
`decision_resolution`, `agent_proposal`, `user_override`, `action`,
`technical_outcome`, `user_outcome`, `correction`, and `context`.

**The adapter reports; the daemon decides.** An adapter may state which actor it
believes produced an event. The daemon derives `evidence_eligibility`
deterministically from the owner-approved source, its acquisition method, the event
type, the reported actor, and a recorded policy-profile version. A request that
carries an eligibility field is rejected. `eligible` means a later validated
extractor or promotion rule may consider the event; it never means that ingestion
creates Evidence.

**Non-canonical input is an observation, not a fact.** An external resolution
report becomes a `ResolutionObservation` and an external outcome report becomes an
`OutcomeObservation`. Observations move through `unmatched`, `pending`,
`confirmed`, and `rejected`. Only an owner-authenticated explicit choice is
promoted to the canonical `DecisionResolution` path and its choice Evidence, and
only an owner confirmation can create owner-reported wellbeing.

**Technical, behavioral, and wellbeing outcomes are separate.** `OutcomeKind`
distinguishes `technical`, `user_behavior`, and `owner_reported`. A passing test
suite is a technical result with a `TechnicalOutcomeStatus`; a kept, modified, or
reverted suggestion is a `UserDisposition`; satisfaction and regret remain the
owner's `DecisionOutcome` and require owner confirmation. ADR-010's separation of
behavior and wellbeing therefore extends to observed workflows.

**Ingestion is transactional and idempotent.** One request commits the raw event,
its correlation links, and its lifecycle projection together or not at all.
Uniqueness is `(source_id, external_event_id)`. An identical retry returns the
original result; the same external event ID with a different content fingerprint is
a stable conflict error and mutates nothing. Events may arrive out of order: an
observation with no matching decision is retained as `unmatched` and never attached
to an unrelated lifecycle.

**Authorization reuses the single boundary.** Push ingestion is REST-only and
needs an active service identity holding the exact scope for the event family:
`interaction:record`, `decision:record`, `decision:resolution:record`, or
`outcome:observe`. No unrestricted `RawEvent` write endpoint exists, and Phase 13
adds no passive-capture tool to the model-visible MCP surface.

**Existing clients keep working with explicit semantics.** `predict_choice`,
`rank_options`, and `record_decision` keep their response fields and gain source
and purpose provenance. External `record_outcome` becomes a compatibility wrapper
that records an unconfirmed `owner_reported` observation instead of asserting owner
wellbeing. Owner-facing outcome recording is unchanged.

**Deletion follows provenance.** Removing a source removes its events,
observations, and derivative decisions and Evidence, then triggers a deterministic
model rebuild when Evidence changed. Retention is declared per source and data
class; `delete_after_extraction` is rejected rather than silently accepted, because
no durable extraction success marker exists yet.

**A pushed source belongs to one identity.** The owner approves a source for
exactly one service identity; another identity cannot write to it even when it
holds the right scope. Legacy `record_outcome` writes are attached to an
automatically created per-identity compatibility source whose consent is
`owner_implicit` (the owner granted that identity the `outcome:record` scope) and
whose author scope is agent-only, so they can never become eligible.

**Correlation is by source-scoped external identifiers.** A decision is identified
by `(source, external_decision_id)` and its options by `external_option_id`.
Correlation and causation IDs are stored as reported and are not required to
exist yet, because events may arrive out of order. A new decision attaches only
unmatched observations from its own source with the same external decision ID,
in the same transaction; a late-matched owner choice becomes `pending` and waits
for owner confirmation rather than being promoted retroactively.

**Promotion is part of the transaction.** A promoted choice writes the canonical
resolution and its choice Evidence together with the event and observation; only
the model rebuild runs afterwards, recoverable through the evidence revision. An
owner confirmation of a pending choice uses the same atomic path.

**Existing tables gain columns in place.** SQLite rebuilds a table to add a check
constraint or foreign key, and the affected tables are foreign-key targets with
cascading children, so migration `0012` adds plain columns to them and the domain
records enforce the vocabulary. The new observation tables carry full database
constraints.

**Pull connectors and push adapters stay separate.** The connector SDK remains a
pull API with its own scheduling, cursors, and credentials. Decision I/O is a push
API for installed agent adapters. They share the normalized source and event
concepts and the same deletion guarantees, but merging their lifecycles would force
scheduling and cursor semantics onto hooks that have neither.

## Consequences

Every externally ingested lifecycle record becomes attributable and revocable, and
an external caller can no longer assign itself owner authority, evidence
eligibility, or wellbeing. Classification stays deterministic: fixed inputs, policy
version, and algorithm version produce the same eligibility and promotion result
without an LLM.

The cost is a second write path with its own records, scopes, and migration, and a
compatibility break in meaning — not in shape — for external `record_outcome`.
Agents that relied on it to assert satisfaction now produce observations the owner
must confirm, which is the intended correction.

Observations accumulate: unmatched reports are retained until their decision
arrives, is deleted, or the owner rejects them, so Phase 14 and later phases must
add owner review ergonomics rather than silent expiry. Eligibility is recorded at
ingestion time against a policy-profile version; changing the policy does not
retroactively re-classify stored events, and a re-classification job is
intentionally deferred.
