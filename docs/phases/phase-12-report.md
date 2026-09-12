# Phase 12 report — Delegated Decision Agent

## Authorization and scope

Phase 12 was explicitly authorized on 2026-09-12. Work is limited to a separate
Policy Engine, owner-controlled impact classification and confidence thresholds,
agent permissions, durable approval workflows, and local product/API surfaces.
Soulmate does not execute third-party side effects or become a general autonomous
agent framework.

## Implementation plan

1. Add infrastructure-independent delegated-action records, repository ports, and
   a deterministic Policy Engine that evaluates only persisted predictions.
2. Persist owner policies and idempotent approval requests with migration
   `0010_phase_12`, including restart-safe lifecycle transitions and expiry.
3. Extend the single authorization boundary with a separate `agent:delegate`
   scope and expose owner-only policy/review plus scoped external request/status/
   completion REST APIs.
4. Add typed SDK, MCP, and desktop External Agents workflows without placing
   external action execution inside Soulmate.
5. Verify impact, confidence, freshness, isolation, idempotency, approval,
   revocation, restart, privacy-minimal audit, migration, and product behavior.

## Delivered work

| Area | Result |
| --- | --- |
| Policy Engine | Dependency-free deterministic kernel service evaluates exact owner policies against the latest persisted prediction and current Personal Model snapshot |
| Impact | Owners classify each agent/action pair as low, medium, high, or safety-critical; external requests cannot supply or override impact |
| Confidence | Automatic approval has hard floors of 0.90 for low impact and 0.95 for medium impact; policy thresholds may only be stricter |
| Confirmation | High and safety-critical actions always require owner approval; lower-impact actions also remain pending when automation is disabled or confidence is insufficient |
| Permissions | The independent `agent:delegate` scope gates request, status, and completion operations in the shared authorization boundary |
| Durability | Policies and idempotent per-agent request IDs persist in SQLite; requests expire after 24 hours and lifecycle transitions are atomic |
| Product surfaces | Owner-only REST and desktop policy/review screens, typed TypeScript SDK operations, and MCP request/status/complete tools are implemented |
| Audit and privacy | Policy, approval, and completion audits contain IDs, states, and reason codes without action labels, decision text, evidence, credentials, or private payloads |
| Execution boundary | Soulmate returns authorization and the predicted option; the external agent performs and self-reports its own side effect |

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result |
| --- | --- | --- | --- |
| P12-T01 | Low-impact policy below 0.90 or medium below 0.95 | Safety floor | Policy is rejected |
| P12-T02 | High or safety-critical policy enables automation | Impact invariant | Policy is rejected |
| P12-T03 | Low impact, automation enabled, fresh confidence above threshold | Automatic path | Request is approved without owner interaction |
| P12-T04 | Confidence below threshold or automation disabled | Conservative path | Request remains pending |
| P12-T05 | High-impact request with confidence 1.0 | Mandatory review | Request remains pending until explicit owner approval |
| P12-T06 | Prediction references an older Personal Model snapshot | Freshness | Delegation is refused until the agent obtains a fresh prediction |
| P12-T07 | Reused external request ID with identical content | Idempotency | Original durable request is returned without duplicate authority |
| P12-T08 | Reused external request ID with different content | Integrity | Request is rejected |
| P12-T09 | Another service identity requests the status | Isolation | Request is hidden |
| P12-T10 | Missing `agent:delegate` scope | Authorization | Shared boundary denies the operation even on loopback |
| P12-T11 | Approved request is completed twice or after expiry | Lifecycle | Only the first unexpired completion succeeds |
| P12-T12 | Daemon restart | Persistence | Policy and request state remain available |
| P12-T13 | Policy is removed after use | Revocation/history | Future requests are denied while historical requests remain |
| P12-T14 | Delegation is audited | Privacy | Audit metadata excludes action labels and decision content |

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24.19.0, pnpm
11.21.0, and Rust 1.91.0 passed on 2026-09-12:

| Gate | Result |
| --- | --- |
| Frozen lockfiles | Passed |
| Ruff lint and formatting | Passed; 177 Python files checked |
| Strict mypy | Passed; 114 source files checked |
| Python unit, integration, and evaluation tests | Passed; 285 tests, with 7 upstream/deprecation warnings |
| TypeScript tests | Passed; 86 SDK, desktop, mobile, and web tests |
| Rust tests | Passed; 4 tests |
| Repository hooks | Passed; existing empty `py.typed` markers were normalized by the EOF hook |
| Python package builds | Passed; seven packages |
| Web and desktop production builds | Passed |
| Clean PyInstaller sidecar build and packaged `0010_phase_12` migration smoke | Passed on macOS arm64 |

Remote GitHub Actions verification remains unconfirmed.

## Known issues and limitations

- Soulmate grants or denies authority but does not execute, observe, verify, or
  roll back the third-party action. Completion is reported by the external agent.
- Impact classification is configured by the owner per exact action type. There is
  no LLM-based or inferred classification, avoiding an untrusted classification
  path but requiring careful owner configuration.
- Confidence uses the existing deterministic prediction calibration. Broad
  external datasets and safety-critical real-world calibration remain unverified;
  high and safety-critical automation is therefore prohibited.
- Approval notifications, scheduled expiry cleanup, batch review, remote MCP
  transport, and connector-specific action executors are not implemented.
- Authorization expiry is fixed at 24 hours in this phase. Removing a policy does
  not retroactively revoke an already approved request, but the owner can reject
  that individual request before completion.

## Phase 12 handoff

Phase 12 exit criteria pass locally: an approved external identity can request a
fresh prediction-bound action, receive automatic authority only inside explicit
low/medium impact and confidence limits, wait for owner approval otherwise, and
complete that durable authorization exactly once without gaining access to raw
Personal Model data.

Phase 12 is the final phase defined by the current specification. No later product
phase is authorized or specified. Further autonomous execution, notification,
policy language, or safety-critical functionality requires a new explicit scope
and architecture review.
