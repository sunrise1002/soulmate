# Phase 8 report — Active Learning & Outcome Intelligence

## Authorization and scope

Phase 8 was explicitly authorized on 2026-09-12. Work is limited to specification
tasks P8-01 through P8-06. MCP, external service identities and scopes, import,
backup, connectors, and delegated decisions are not authorized.

## Implementation plan

1. Expose deterministic uncertainty signals already derived from preference
   evidence and rank them by a versioned information-value heuristic.
2. Generate persistent, context-preserving pairwise questions without requiring an
   LLM and turn answers into provenance-bearing calibration Evidence.
3. Persist satisfaction, regret, and optional outcome notes through a new migration
   and preserve deletion control on the owner's machine.
4. Build a separate wellbeing estimator from resolved decisions and reported
   outcomes so outcome feedback cannot change Predict Me semantics.
5. Implement versioned Advise Me scoring over behavioral probabilities, historical
   wellbeing, and matching goals or constraints.
6. Add typed REST/SDK contracts and desktop, web, and mobile workflows for questions,
   advice, outcomes, history, and owner-controlled outcome deletion.

## Delivered work

| Task | Result |
| --- | --- |
| P8-01 Uncertainty Model | `rank_uncertainties` exposes preference uncertainty, confidence, context, and a deterministic information-value score through `GET /v1/model/uncertainties` |
| P8-02 Active Question Generator | Local pairwise question templates target one uncertain preference or a compatible-context trade-off and record the exact model snapshot and algorithm version |
| P8-03 Question Ranking | `active-learning-v1:uncertainty-v1:information-gain-v1` ranks candidates by a bounded heuristic and avoids repeating persisted question/context combinations |
| P8-04 Outcome Tracking | One restart-safe outcome per resolved decision records satisfaction from 0 to 1, regret, optional notes, RawEvent provenance, and history; owner deletion removes the source event and invalidates derived advice |
| P8-05 Behavioral vs Wellbeing Model | ADR-010 keeps actual-choice preference learning in Predict Me and derives wellbeing signals only inside the separate advice path |
| P8-06 Advise Me | `decision-advisor-v1` combines behavioral probability, signed similarity to reported outcomes, and matching goal/constraint alignment; responses show both predicted and recommended choices |

SQLite migration `0006_phase_8` adds `active_questions`, `question_answers`,
`decision_outcomes`, and `decision_advice`. Advice references its behavioral
prediction and Personal Model snapshot. Active questions reference the snapshot
that selected them. Outcome deletion is owner-only because it deletes private
source data; recording and consulting the Phase 8 models remain available to an
authorized paired device through the existing single access boundary.

Desktop, web, and mobile clients display Predict Me and Advise Me separately,
offer uncertainty-targeting questions, record simple outcome feedback, and include
outcome/advice information in history. The desktop owner can delete an outcome and
then record a replacement.

## Test perspectives

| Case ID | Input / Precondition | Perspective | Expected result |
| --- | --- | --- | --- |
| P8-T01 | Two uncertain preferences | Normal | Highest-information compatible trade-off ranks first |
| P8-T02 | Contextual preferences | Context boundary | Only preferences with identical context are paired; answer Evidence retains context |
| P8-T03 | Previously persisted question/context | Repeat | The same question target is not generated again |
| P8-T04 | Single uncertain preference | Boundary | Positive/negative calibration question is generated |
| P8-T05 | Unknown target key | Abnormal | No question is generated |
| P8-T06 | Answer A or B | Normal | Bounded pairwise preference Evidence is created with RawEvent provenance |
| P8-T07 | Answered question answered again | Abnormal | Request returns conflict and no second answer is stored |
| P8-T08 | Invalid answer value | Invalid format | Request validation returns 422 |
| P8-T09 | Active question restart | Persistence | Question state and answer survive restart |
| P8-T10 | Outcome on resolved decision | Normal | Satisfaction, regret, notes, and source event are stored |
| P8-T11 | Outcome on open decision | Abnormal | Request returns conflict |
| P8-T12 | Satisfaction below 0 or above 1 | Boundary | Request validation returns 422 |
| P8-T13 | Second outcome for the same decision | Duplicate | Request returns conflict |
| P8-T14 | Low satisfaction plus regret on similar prior choice | Normal | Wellbeing score penalizes a similar option and can favor its alternative |
| P8-T15 | Behavioral choice differs from wellbeing choice | Separation | Predict Me stays unchanged while Advise Me recommends another option |
| P8-T16 | No matching outcome or goal evidence | Sparse data | Advice falls back visibly to available behavioral components |
| P8-T17 | Advice after model evidence changes | Version boundary | A fresh behavioral prediction is recorded for the current snapshot |
| P8-T18 | Service restart after advice/outcome | Persistence | History returns the same outcome and versioned advice |
| P8-T19 | Owner deletes an outcome | Privacy | Outcome source and all potentially derived advice are removed atomically |
| P8-T20 | Paired device deletes an outcome | Authorization | Single access boundary returns 403 |
| P8-T21 | SDK identifiers contain `/` | Invalid path data | Identifiers are URL encoded before Phase 8 requests |

## Verification

Local verification on macOS arm64 with Python 3.12.4, Node.js 24, pnpm 11.21.0,
and Rust completed through `pnpm check:all`:

| Check | Result |
| --- | --- |
| Frozen Python and pnpm lockfiles | Passed |
| Ruff lint and formatting | Passed; 132 Python files |
| Strict mypy | Passed; 78 source files |
| Python unit, integration, and evaluation tests | Passed; 229 total with two unchanged upstream warnings |
| SDK, web, mobile, and desktop ESLint, Prettier, and TypeScript | Passed |
| SDK, web, mobile, and desktop tests | Passed; 82 client tests |
| Rust formatting, Clippy with warnings denied, and native shell tests | Passed; 4 tests |
| Repository pre-commit hooks | Passed |
| Python package builds | Passed |
| Web and desktop production builds | Passed |

Local results do not imply remote GitHub Actions passed.

## Known issues and limitations

- Information gain is a deterministic uncertainty heuristic, not a posterior or
  expected-information-gain calculation.
- Questions use English templates and normalized feature contrasts. They do not
  use an LLM to create richer scenarios, and no scheduling or notification system
  decides when to ask.
- Each decision has one current outcome. Correction uses owner deletion followed
  by a replacement, and deleting one outcome conservatively invalidates all stored
  advice for the profile.
- Wellbeing uses signed cosine similarity over structured option features. It does
  not model delayed outcomes, changing satisfaction, causal effects, or independent
  objective facts.
- Goal and constraint alignment requires their keys to match option feature keys.
  Natural-language goal mapping remains unavailable.
- Client screens were typechecked and covered by their existing component/transport
  suites, but no new native iOS or Android build or device run was performed.
- Remote CI, real provider inference, and external-dataset calibration remain
  unverified.

## Phase 9 handoff

Phase 8 exit criteria pass locally: Soulmate can identify uncertain preferences,
ask targeted trade-off questions, learn from answers, record satisfaction and
regret, keep behavioral prediction separate from wellbeing, and explain when
historical outcomes shift Advise Me away from Predict Me.

Phase 9 may begin only after explicit authorization. MCP and external credentials
must reuse application services and the single authorization/audit boundary; they
must not expose raw outcomes, notes, memories, or evidence by default.
