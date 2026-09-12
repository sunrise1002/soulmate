# ADR-013: Prediction-bound delegated action policy

Status: Implemented in Phase 12.

## Context

External agents can already request predictions, but a prediction is not authority
to act. Letting an agent submit its own impact classification or confidence would
make least-privilege scopes ineffective, while executing calendar, financial, or
other provider actions inside Soulmate would turn the project into a general
automation framework. Delegated authority must remain owner-defined, narrow,
auditable, revocable, and independent of any LLM.

## Decision

Implement a deterministic Policy Engine in the Personalization Kernel. An owner
creates a policy for one service identity and one exact action type, assigning its
impact (`low`, `medium`, `high`, or `safety_critical`), minimum prediction
confidence, and whether automatic approval is allowed. Low-impact policies have a
hard 0.90 confidence floor and medium-impact policies have a 0.95 floor. High and
safety-critical actions can never be approved automatically.

Require the separate `agent:delegate` service-identity scope for every external
delegation operation. A request references a decision and its latest persisted
prediction; the Policy Engine also requires that prediction to use the current
Personal Model snapshot. The daemon derives impact from the owner's stored policy,
never from agent input. Requests are idempotent per agent and external request ID,
expire after 24 hours, and persist through restart.

The engine returns either a bounded automatic approval or a pending request. The
owner can approve pending requests or reject pending/approved requests through
owner-only REST and desktop surfaces. An agent can inspect only its own requests
and mark one approved request completed exactly once. Soulmate grants authority
but does not perform the remote side effect. Policy and lifecycle audits contain
identifiers and reason codes, not action labels, decision text, credentials, or
model evidence.

## Consequences

Agents receive explicit, short-lived authorization tied to a concrete prediction
instead of interpreting confidence as permission. Policy removal prevents future
requests without deleting retained approval history. The owner can revoke an
individual uncompleted approval by rejecting it. Revoking the service identity,
credential, or `agent:delegate` scope blocks the next request at the shared access
boundary.

The owner remains responsible for classifying each action type and the external
agent remains responsible for executing and accurately reporting completion.
Soulmate cannot prove that a remote side effect occurred or roll it back. Current
confidence calibration is the deterministic Phase 5 implementation and has not
been validated against broad external or safety-critical datasets, so high and
safety-critical automation remains prohibited regardless of confidence.
