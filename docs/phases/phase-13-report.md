# Phase 13 report — Decision I/O and trusted provenance

## Authorization and scope

The [Phase 13 plan](phase-13-plan.md) was recorded on 2026-09-14. The owner
explicitly authorized its implementation on 2026-09-23 and allowed the work to be
split into increments. Work is limited to the plan's scope: provider-neutral
Decision I/O contracts, source and event provenance, observations, migration
`0012_phase_13`, scoped REST ingestion, owner inspection and deletion, SDK and
minimal desktop controls, and documentation. No Codex or Claude Code hook, Git
observer, LLM-based detection, shadow prediction, MCP ingestion tool, remote MCP
transport, or delegation change was built.

## Implementation plan

The plan's increments were executed in order, in three parts:

1. **Contracts (P13-01 to P13-03).** ADR-014, the provenance vocabulary and
   records in the kernel, and the deterministic eligibility, validation,
   fingerprint, and retention rules.
2. **Persistence (P13-04 to P13-06).** Observation records, the transactional
   `DecisionIoRepository` port and its SQLite adapter, and migration
   `0012_phase_13` with a conservative backfill.
3. **Surfaces (P13-07 to P13-09).** Least-privilege scopes, the push REST surface,
   owner source and observation routes, the `record_outcome` compatibility
   wrapper, retention enforcement, the TypeScript SDK, desktop controls, and
   documentation.

## Delivered work

| Area | Result |
| --- | --- |
| ADR | ADR-014 records Decision I/O as a daemon-owned boundary, the adapter-reports/daemon-decides trust split, observations, separate outcome semantics, transactional idempotency, identity-bound sources, correlation rules, and the in-place migration trade-off |
| Kernel vocabulary | `soulmate_core.domain.provenance` adds acquisition, consent, data class, author scope, retention, actor, eligibility, event type, origin, purpose, observation, outcome, technical, disposition, and attribution enums plus `SourceProvenance`, `EventProvenance`, `ResolutionObservation`, and `OutcomeObservation` with their invariants |
| Existing records | `Source`, `RawEvent`, `DecisionEvent`, `DecisionOption`, and `DecisionOutcome` gain provenance fields with conservative defaults; existing constructors keep working |
| Policy | `soulmate_core.decision_io` derives eligibility deterministically from source, acquisition, event type, actor, and policy profile `p13.1`; validates schema version, UTC timestamps, external IDs, payload size, acquisition, author scope, and declared data classes; fingerprints canonical content; enforces retention; and allows promotion only for owner-authored, eligible choices |
| Repository port | `DecisionIoRepository` commits event, decision projection, correlation of earlier unmatched observations, observations, and a promoted resolution with its choice Evidence in one transaction; identical retries replay, conflicting reuse raises `DecisionIoConflictError` |
| SQLite adapter | `SqliteDecisionIoRepository` implements ingestion, replay, owner confirmation, counts, and source removal; `repositories.py` reads and writes provenance on every existing path, and connector registrations record `connector_pull` provenance |
| Migration | `0012_phase_13` adds provenance columns in place, partial unique indexes for `(source_id, external_event_id)`, `(source_id, external_decision_id)`, and `(decision_id, external_option_id)`, and two constrained observation tables; the backfill marks only locally created owner records as owner-authored and eligible, imports as explicit owner imports, connectors as unverified, decisions as `legacy`, and outcomes as `legacy_unverified` |
| Scopes | `interaction:record`, `decision:resolution:record`, and `outcome:observe` join the existing `decision:record`; each push route requires exactly one |
| Push REST | `/v1/external/decision-io/interactions`, `decisions`, `resolutions`, and `outcomes`; sources must be pushed sources bound to the calling identity; responses return daemon-assigned eligibility, actor, policy version, duplicate flag, observation state, and promotion |
| Owner REST | `/v1/decision-io/sources` (approve, list with capabilities and counts, remove with rebuild) and `/v1/decision-io/observations` (list, confirm, reject); confirming a choice applies the canonical resolution atomically, and confirming a satisfaction report requires the owner's own values |
| Compatibility | `predict_choice`, `rank_options`, and `record_decision` are unchanged. External `record_outcome` (REST and MCP) now stores an unconfirmed `owner_reported` observation under a per-identity compatibility source and keeps its response fields, adding `status`, `kind`, and `requires_owner_confirmation`. Owner outcome recording is unchanged |
| Retention | `metadata_only` sources store no event content while fingerprints still detect conflicts; `delete_after_extraction` is rejected |
| Audit | `decision_io.*` audit events record identifiers, event types, classifications, counts, and flags only |
| SDK | `decision-io-types.ts` and ten new `SoulmateClient` methods; `recordExternalOutcome` is deprecated and correctly typed as `ExternalOutcomeObservation` |
| Desktop | The External agents screen shows approved sources with their allowed data, retention, author scope, and volume, approves new sources, removes them after stating the consequence, and lists observations as visibly distinct from confirmed records with confirm and reject actions |
| Documentation | ADR-014, architecture index, security boundaries, API overview, SDK README, CHANGELOG, phase status, and this report |

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result | Covered by |
| --- | --- | --- | --- | --- |
| P13-T01 | Owner-approved source and valid event | Normal ingestion | Event and projection commit with complete provenance | `test_owner_approved_source_commits_an_event_with_complete_provenance` |
| P13-T02 | Identical retry | Idempotency | Original result, no duplicate | `test_an_identical_retry_returns_the_original_result`, `test_retries_replay_and_conflicts_do_not_write` |
| P13-T03 | Same external ID, different content or projection | Integrity | 409 without mutation | `test_reusing_an_external_event_id_for_other_content_is_rejected`, `test_a_changed_projection_under_the_same_event_id_is_a_conflict` |
| P13-T04 | Agent output presented as a choice | Contamination | Contextual only, never promoted | `test_non_owner_content_can_never_be_eligible`, `test_agent_reported_choices_stay_observations` |
| P13-T05 | Agent submits satisfaction or regret | Wellbeing boundary | Unconfirmed observation; owner wellbeing unchanged | `test_an_agent_cannot_report_owner_wellbeing`, `test_the_owner_confirms_an_observation_before_it_becomes_wellbeing`, `test_confirming_a_satisfaction_report_requires_the_owners_values` |
| P13-T06 | Owner confirms a valid explicit choice | Learning path | Canonical resolution and choice Evidence once | `test_an_owner_choice_is_promoted_once_and_creates_choice_evidence`, `test_the_owner_confirms_an_agent_reported_choice_exactly_once`, `test_an_owner_choice_for_an_already_resolved_decision_is_not_applied_twice` |
| P13-T07 | Tests pass | Technical outcome | Technical history only, ignored for learning | `test_a_technical_result_never_becomes_owner_satisfaction`, `test_only_satisfaction_reports_can_become_wellbeing` |
| P13-T08 | Outcome before its decision | Ordering | Unmatched, correlated later, never to an unrelated decision | `test_an_outcome_before_its_decision_stays_unmatched_then_correlates`, `test_an_unmatched_observation_never_attaches_to_another_decision`, `test_a_late_matched_owner_choice_waits_for_confirmation` |
| P13-T09 | Missing exact scope, foreign source, remote device | Authorization | Refused at the shared boundary | `test_a_caller_without_the_exact_scope_is_refused`, `test_a_source_belonging_to_another_identity_cannot_be_written`, `test_external_sources_are_not_reachable_from_another_device` |
| P13-T10 | Actor or data class outside the source declaration | Consent boundary | Rejected before persistence | `test_events_outside_the_declared_consent_are_rejected` and unit consent tests |
| P13-T11 | Unsupported schema, naive timestamp, empty or oversized ID, oversized content | Validation (boundaries 0/1/2, 200/201 characters, 64 KiB ±1 byte) | Rejected without partial state | `test_invalid_envelopes_are_rejected_without_partial_state` and unit validation tests |
| P13-T12 | Restart after accepted events | Persistence | Idempotency, provenance, and state survive | `test_provenance_and_observations_survive_a_restart` |
| P13-T13 | Owner removes a source with Evidence | Privacy deletion | Graph removed, model rebuilt | `test_removing_a_source_removes_its_provenance_graph_and_rebuilds` |
| P13-T14 | Migration from a real `0011` database, and downgrade | Upgrade | Readable with conservative provenance | `test_upgrade_backfills_provenance_without_inventing_trust`, `test_downgrade_to_0011_keeps_legacy_records_and_re_upgrade_is_clean` |
| P13-T15 | Encrypted export and restore | Portability | Records restore; old API key unusable | `test_an_encrypted_export_restores_provenance_without_usable_credentials` |
| P13-T16 | Audit and failure paths | Payload privacy | No content in audit | `test_audit_records_hold_no_event_content` |
| P13-T17 | Kernel import graph | Architecture | Standard library and kernel only | `test_kernel_imports_only_itself_and_the_standard_library` |
| P13-T18 | Existing REST, MCP, and SDK clients | Compatibility | Reads and predictions unchanged; changed write semantics explicit | existing external access, MCP, and SDK suites |
| P13-T19 | Failure inside the ingestion transaction | Atomicity | Nothing from the request persists | `test_a_failed_promotion_leaves_no_partial_state`, `test_confirmation_requires_the_expected_state` |
| P13-T20 | Retention policy | Minimization | `metadata_only` stores no content; unsupported mode refused | `test_a_metadata_only_source_stores_no_event_content`, `test_unsupported_retention_is_rejected_rather_than_ignored` |

Failure and rejection cases outnumber success cases in the new suites. Tests use
Given/When/Then comments and synthetic data only.

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24.19.0, pnpm
11.21.0, and Rust 1.91.0 passed on 2026-09-25 with `pnpm check:all`:

| Gate | Result |
| --- | --- |
| Frozen lockfiles | Passed |
| Ruff lint and formatting | Passed; 256 Python files checked |
| Strict mypy | Passed; 180 source files checked |
| Python unit, integration, and evaluation tests | Passed; 862 tests (12 `local_model` tests deselected by default configuration), including 91 new Decision I/O cases |
| TypeScript tests | Passed; 206 tests: 59 SDK (3 new), 69 desktop (11 new), 27 mobile, 51 web |
| Rust tests | Passed; 7 tests |
| Repository hooks, including the kernel architecture boundary | Passed |
| Python package builds | Passed; seven packages |
| Web and desktop production builds | Passed |
| Clean PyInstaller sidecar build | Passed; 74.1 MB against the 220 MB budget |

A packaged-sidecar smoke test then ran the freshly built binary against a real
revision `0011` database holding a live owner chat event. Start-up migrated it to
`0012_phase_13` and backfilled that event as owner-authored and eligible; MCP
`initialize` and `tools/list` succeeded with the same nine tools and no ingestion
tool; one valid decision event returned 201, the identical retry returned the
same event as `duplicate`, and a conflicting reuse returned 409; after a daemon
restart the retry still replayed and the source counts were intact; removing the
source deleted its event and decision; and neither daemon log contained event
content.

Remote GitHub Actions verification, Windows and Linux packaged behavior, and
interoperability with a real agent adapter remain unverified.

## Known issues and limitations

- **Schema constraints on existing tables.** Migration `0012` adds columns in
  place, so the new vocabulary columns on `sources`, `raw_events`,
  `decision_events`, `decision_options`, and `decision_outcomes` have no database
  check constraints, and `decision_events.source_id`, `source_event_id`, and
  `raw_events.causation_event_id` are plain columns rather than foreign keys. The
  domain records enforce the vocabulary and the Decision I/O repository removes
  those references explicitly. The new observation tables carry full constraints.
- **Free-form content.** Soulmate cannot verify that free-form event content
  matches the data classes a source declared. `metadata_only` removes content
  entirely; for other policies the adapter is trusted to send only declared data.
- **Correlation IDs are not validated to exist**, because events may arrive out of
  order. They are stored as reported.
- **Late-matched owner choices are not promoted automatically.** An owner choice
  that arrives before its decision becomes `pending` once matched and needs the
  owner's confirmation.
- **Eligibility is recorded at ingestion time** against policy profile `p13.1`.
  A policy change does not re-classify stored events; no re-classification job
  exists. Eligible events are not yet consumed by any extractor.
- **Unmatched observations do not expire.** They remain until their decision
  arrives, their source is removed, or the owner rejects them.
- **Satisfaction confirmation is two writes.** The owner's own outcome is written
  first and the report is then marked confirmed; an interruption leaves the
  owner's outcome in place and the report still open, never the reverse.
- **Legacy `record_outcome` idempotency.** Its reports use the external ID
  `legacy_outcome:{decision_id}`, so a changed second report for the same decision
  returns 409 instead of silently replacing the first.
- **Imports are backfilled as explicit owner acquisitions** because an import is
  an owner-initiated upload; this is recorded rather than inferred from storage.
- Web and mobile clients have no Decision I/O screens; the plan limited product
  work to the desktop.

## Phase 13 handoff

Phase 13 exit criteria pass locally: every externally ingested lifecycle record
carries source, acquisition, consent, actor, policy-version, and event provenance;
an external caller cannot assign eligibility or owner authority; agent-only content
cannot change derived beliefs; agent-reported wellbeing stays unconfirmed until the
owner confirms it with their own values; technical, behavioral, and owner-reported
outcomes are stored and returned separately; retries are idempotent and conflicts
rejected; out-of-order observations stay recoverable and never attach to an
unrelated decision; and source removal deletes derivative data and rebuilds the
model after restart. Remote CI status is unverified, as stated above.

Phase 13 is a stop gate: no Codex or Claude Code hook, Git observer, passive detection, shadow
prediction, MCP v2 surface, or delegation change may start until a new phase is
planned from this report and explicitly authorized. Phase 14 should build on the
push contracts here: an adapter registers nothing itself, the owner approves its
source, and the adapter sends `schema_version` 1 envelopes with stable external
IDs.
