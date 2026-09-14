# Soulmate — Post-MVP Architecture Delta & Decision/Outcome Capture Handoff

**Document status:** Reviewed against the repository on 2026-09-14

**Delivered baseline:** Phases 0–12 complete locally

**Next phase:** Phase 13 is planned but not started and requires explicit owner authorization

**Verification boundary:** Remote CI and the cross-platform checks listed in the phase reports remain unconfirmed

This document records post-MVP product and architecture direction. It is not an
implementation-status authority or authorization to begin a phase. The current
status and phase gate are maintained in [`docs/phase-status.md`](docs/phase-status.md),
with delivered details in the linked phase reports. The recorded Phase 13 scope is
in [`docs/phases/phase-13-plan.md`](docs/phases/phase-13-plan.md).

## 1. Purpose of This Document

This document summarizes the **new conclusions reached after the original Soulmate MVP specification was created**.

The repository is no longer merely assumed to contain the MVP. Phases 0–12 are
complete locally. In addition to the original Personal Model and decision loop,
the delivered baseline includes desktop/web/mobile clients, active learning,
outcomes and Advise Me, scoped REST and local stdio MCP access, encrypted
portability, a permissioned connector framework, and prediction-bound delegated
action approval. Each phase report records its exact limitations and local
verification results; remote CI is still unconfirmed.

Therefore, this document intentionally **does not repeat the original specification** unless a previous assumption needs to be changed.

The main new topics are:

1. How Soulmate should learn without requiring users to continuously chat with it.
2. How to capture real decisions, corrections, and outcomes from existing workflows.
3. Which integration approaches should be prioritized or avoided.
4. How MCP and native agent hooks should work together.
5. How to prevent AI-generated content from contaminating the Personal Model.
6. How Soulmate should evolve from a prediction system into an **Owner Decision Service** for other agents.
7. How delegation should work safely.
8. How the post-MVP implementation roadmap should change.

---

# 2. Main Product Insight After the MVP

The key assumption that changed is:

> Soulmate should not depend on users actively talking to Soulmate in order to improve.

Conversation remains useful, but the system should optimize for:

> **collecting high-quality evidence about the user from decisions they are already making in their normal digital workflows.**

The goal is therefore not:

```text
make user chat with Soulmate more
```

but:

```text
observe useful user-authorized decision signals
        ↓
capture decisions
        ↓
capture corrections
        ↓
capture actual actions
        ↓
capture outcomes
        ↓
learn continuously
```

This is especially important because actual behavior is generally more valuable than casual conversation.

Examples:

```text
User says:
"I prefer simple software."

Useful evidence.

But:

AI proposes microservices
        ↓
User replaces it with a modular monolith
        ↓
User repeats this behavior in several projects

Much stronger evidence.
```

Soulmate should increasingly learn from the second category.

---

# 3. New Architectural Concept: Decision I/O

A new abstraction should be introduced:

```text
Decision I/O Layer
```

Its responsibility is to allow external systems to both:

```text
send decisions into Soulmate
```

and:

```text
send resolutions/outcomes back into Soulmate
```

Conceptually:

```text
External Agent / Application
            │
            │ authorized external event
            ▼
     Soulmate Decision I/O
            │
            ├─ validate source, consent, actor, schema
            ├─ assign evidence eligibility
            └─ enforce idempotency and correlation
            ▼
     RawEvent + Observation
            │
            │ explicit promotion policy
            ▼
 Decision / Resolution / Outcome
            │
            ├─ eligible owner evidence → Personal Model
            └─ technical/agent observation → history only
            │
            ▼
     prediction / ranking
            │
            ▼
 External Agent acts
            │
            │ actual result
            ▼
     Soulmate Decision I/O
            │
            ▼
 observation / learning loop
```

This is broader than the existing `DecisionEvent` concept.

It becomes the standard boundary between Soulmate and the outside world.

**Current status:** this boundary is the planned scope of Phase 13 and is not yet
implemented. The existing external decision APIs, connector ingestion, and
delegation requests are separate delivered paths that Phase 13 must preserve
while introducing trusted provenance and observation semantics.

---

# 4. Separate Two Integration Responsibilities

One of the most important conclusions is that external integrations should be divided into two fundamentally different mechanisms.

## 4.1 Passive Observation

Used for:

```text
capturing behavior
capturing corrections
capturing actions
capturing outcomes
capturing workflow context
```

Preferred mechanisms:

```text
native hooks
application events
Git/repository observation
official connectors
```

These should generally NOT require the external LLM to explicitly call Soulmate.

---

## 4.2 Active Consultation

Used when an agent needs an answer such as:

```text
"What would the owner prefer?"

"Which option best matches the owner?"

"Would the owner probably choose A or B?"

"What preferences matter for this task?"
```

Preferred mechanism:

```text
MCP / REST Decision Service
```

The recommended architecture is therefore:

```text
                External Agent
                     │
       ┌─────────────┴──────────────┐
       │                            │
       ▼                            ▼
    Hooks / Events                 MCP
       │                            │
       │ observe                    │ consult
       │                            │
       ▼                            ▼
┌──────────────────────────────────────────┐
│                 Soulmate                 │
│                                          │
│ Raw Events        Personal Model         │
│ Evidence          Decision Engine        │
│ Outcomes          Context Compiler       │
│ Corrections       Policy Engine          │
└──────────────────────────────────────────┘
```

A useful mental model is:

> **Hooks are Soulmate's sensory system.**

> **MCP is Soulmate's communication and decision interface.**

---

# 5. Capture Strategy Comparison

The following approaches were evaluated.

| Approach | Main Signal | Signal Quality | Non-Tech UX | Implementation | Policy / Legal Risk | Recommendation |
|---|---|---:|---:|---:|---:|---|
| Native agent hooks | decisions, corrections, tool activity, outcomes | Very High | Excellent after automatic setup | Medium | Low | Highest priority |
| MCP / Soulmate tools | explicit decision consultation | Very High | Excellent after automatic setup | Medium | Low | Highest priority |
| Git/repository observer | accepted/rejected/reverted technical decisions | High | Excellent | Low-Medium | Low | High priority |
| Soulmate AI Gateway using official APIs | AI conversations and decision contexts | High | Good | Medium | Low-Medium | High priority |
| Official app connectors | real behavioral data | High | Excellent with OAuth | Medium | Medium | High priority later |
| IDE extensions | edits, accept/reject, coding preferences | Very High | Excellent | Medium-High | Low-Medium | Strong future integration |
| Share Sheet / Quick Capture | explicitly submitted context | Medium | Excellent | Low | Low | Useful supporting feature |
| Opt-in browser extension | user AI interactions | High | Excellent | Medium | Medium | Optional |
| Always-on browser scraping | entire AI conversation history | High | Excellent | Medium-High | High | Avoid in core |
| Accessibility/screen observation | arbitrary application activity | Medium | Medium | High | High | Experimental only |
| HTTPS MITM interception | almost everything | High | Poor | Very High | Very High | Do not implement |
| Reading private application caches | historical conversations | Medium-High | Potentially automatic | High/brittle | High | Do not implement |

---

# 6. Priority Capture Direction

The original recommendation placed native hooks and MCP first. Repository
delivery changed the relevant baseline:

```text
Delivered:
    scoped REST + local stdio MCP              Phase 9
    permissioned connector framework           Phase 11
    prediction-bound delegation Policy Engine  Phase 12

Planned next:
    Decision I/O + trusted provenance           Phase 13

Directional later work (not authorized):
    agent adapters and native hooks             Phase 14
    decision/correction detection               Phase 15
    Git/repository outcome observation          Phase 16
    shadow evaluation                           Phase 17
    Owner Decision Service v2/context steering  Phase 18
    second live agent adapter                   Phase 19
    delegation hardening                        Phase 20
    selected general-life connectors            Phase 21
```

The Phase 13 plan, rather than the original priority list, is now the sequencing
authority. Later phase numbers above are directional only and require separate
plans and explicit owner authorization.

Avoid designing Soulmate around surveillance-style collection.

The principle should be:

> **Soulmate should be present where users already make decisions, rather than trying to observe everything the user does.**

---

# 7. Native Agent Hooks

Native hooks should be the preferred mechanism for passive learning from tools such as:

```text
Claude Code
Codex
future coding agents
other hook-capable agent runtimes
```

Typical lifecycle events may include:

```text
SessionStart
UserPromptSubmit
PreToolUse
PostToolUse
PermissionRequest
Stop
SessionEnd
```

The exact event names depend on the external agent.

Soulmate should normalize provider-specific hooks into a provider-independent internal event format.

Example:

```text
Claude Code / Codex
        │
        │ PostToolUse
        ▼
Agent Adapter
        │
        ▼
Soulmate local daemon
        │
        ▼
RawEvent
```

The agent's LLM does not necessarily need to know this happened.

**Current status:** no Codex or Claude Code hook installer, provider adapter, or
push-ingestion endpoint exists yet. Phase 13 establishes the provider-neutral
ingestion contract; the first hook adapter is directional Phase 14 work.

---

# 8. Hooks Should Usually Be Token-Free

A major reason to prefer hooks for observation is token efficiency.

Example:

```text
agent runtime
    ↓
local hook script
    ↓
localhost Soulmate API
    ↓
SQLite / event processor
```

No LLM call is required.

Therefore:

```text
PostToolUse capture       → ~0 additional agent tokens
SessionEnd capture        → ~0 additional agent tokens
User correction capture   → ~0 additional agent tokens
Git outcome capture       → 0 additional agent tokens
```

LLM cost only appears if Soulmate later chooses to use an LLM for semantic extraction.

Even then, extraction can potentially use:

```text
local model
batch processing
cheap model
heuristic processing
```

rather than increasing the active coding agent's context.

---

# 9. What Hooks Should Capture

Hooks should NOT simply store everything indefinitely.

They should generate structured `RawEvent`s such as:

```text
agent_session_started
user_prompt_submitted
agent_proposed_decision
tool_invoked
file_modified
user_override_detected
agent_action_completed
agent_session_finished
```

The system should then determine whether an event is useful for:

```text
decision detection
correction detection
outcome detection
preference evidence
```

---

# 10. Correction Capture Is Extremely Valuable

One of the strongest passive learning signals is:

```text
agent proposes something
        ↓
user changes/rejects it
```

Examples:

```text
Agent chooses JWT
User changes to session cookies
```

```text
Agent introduces Redis
User removes Redis
```

```text
Agent creates a complex abstraction
User says:
"This is over-engineered. Simplify it."
```

These should create high-value correction evidence.

Conceptually:

```text
AgentProposal
      ↓
UserOverride
      ↓
CorrectionCandidate
      ↓
eligibility and promotion review
      ↓
Evidence, only when policy permits
```

Corrections should generally receive significantly more weight than ordinary conversational inference.

An inferred override must not automatically become owner Evidence. The daemon
must first classify actor and evidence eligibility, and Phase 15 initially keeps
inferred correction candidates review-only.

---

# 11. Git / Repository Observation

For coding workflows, Git provides a useful outcome channel.

Soulmate may observe repositories that the user explicitly connects.

Potential signals:

```text
AI-created code remains unchanged
AI-created code heavily edited
dependency added then removed
architecture introduced then reverted
feature merged
feature reverted
tests continue passing
user repeatedly rewrites the same pattern
```

Example:

```text
Agent selects library A
        ↓
library A implemented
        ↓
user removes A two days later
        ↓
possible negative outcome
```

However:

> A behavioral observation is not automatically a preference.

For example, library A may have been removed because of a technical bug rather than personal preference.

Therefore the system should distinguish:

```text
ObservedOutcome
```

from:

```text
PreferenceEvidence
```

When causality is uncertain, Active Learning may ask:

```text
"You replaced library A with B.
Was that because you prefer B,
or because A did not work correctly?"
```

---

# 12. Technical Outcome vs User Preference Outcome

A new important distinction should be introduced.

An agent decision may be:

```text
technically successful
```

while simultaneously:

```text
personally undesirable to the user
```

Example:

```text
Architecture works correctly.
All tests pass.

But the user considers it over-engineered
and rewrites it.
```

Do not collapse these into one outcome.

Recommended conceptual structure:

```text
Decision
   ↓
Resolution
   ↓
┌───────────────────────┐
│                       │
▼                       ▼
TechnicalOutcome     UserOutcome
                         │
                         ▼
                  Satisfaction
                         │
                         ▼
                      Regret
```

Possible fields:

```text
technical_success
user_accepted
user_modified
user_reverted
satisfaction
regret
```

This distinction is especially important for coding-agent integration.

---

# 13. Decision Shadowing

Soulmate should eventually support **shadow decisions**.

When Soulmate detects a real decision:

```text
User / Agent is considering A vs B vs C
```

Soulmate can internally predict:

```text
A = 18%
B = 73%
C = 9%
```

without showing the prediction to the user.

Later:

```text
user chooses B
```

Soulmate compares:

```text
shadow prediction
vs
actual choice
```

Benefits:

1. Generates unbiased evaluation data.
2. Avoids influencing the user's decision.
3. Measures whether the Personal Model actually understands the user.
4. Creates continuous evaluation without requiring explicit benchmark sessions.

Recommended new concept:

```text
DecisionPrediction.mode =
    interactive
    shadow
```

**Current status:** shadow prediction is not implemented. It is directional
Phase 17 work after Phase 13 provenance and later real-adapter correlation are
stable.

---

# 14. MCP as the Active Owner Decision Interface

Soulmate already exposes nine compact tools through a local stdio MCP adapter:

```text
predict_choice
rank_options
get_preference_summary
find_similar_decisions
record_decision
record_outcome
request_delegation
get_delegation
complete_delegation
```

They call the scoped daemon REST boundary and do not read persistence directly.
`consult_owner`, `get_owner_context`, and `rank_for_owner` remain possible v2
facades, not current tool names. Phase 13 does not add passive ingestion to the
model-visible MCP surface; passive recording belongs on a bounded REST path used
by installed adapters.

The current `record_outcome` contract predates trusted actor/outcome provenance.
Phase 13 plans to preserve compatibility while treating external submissions as
unconfirmed observations rather than assertions of owner satisfaction or regret.

---

# 15. `consult_owner`

Example request:

```json
{
  "decision": "Which persistence implementation should be used?",
  "domain": "software.architecture",
  "options": [
    {
      "id": "sqlite",
      "features": {
        "simplicity": 0.9,
        "dependencies": 0.2,
        "scalability": 0.5
      }
    },
    {
      "id": "postgres",
      "features": {
        "simplicity": 0.5,
        "dependencies": 0.7,
        "scalability": 0.9
      }
    }
  ]
}
```

Example response:

```json
{
  "preferred": "sqlite",
  "probability": 0.86,
  "confidence": 0.82,
  "important_factors": [
    "prefers simple local solutions",
    "avoids infrastructure without clear need"
  ],
  "model_version": 73
}
```

Responses should be deliberately compact.

This proposed call is personalization only, not authorization. An agent that
wants authority to act must separately use the delivered delegation workflow.
The Phase 12 Policy Engine derives impact from an exact owner-created
agent/action policy; callers cannot supply or override impact, confidence policy,
or approval authority. Reversibility and domain-aware policy are possible future
hardening inputs, not current delegation fields.

---

# 16. `get_owner_context`

Agents should not need to wait until a discrete decision occurs.

Before beginning a task, an agent may ask:

```text
"What preferences are relevant to this task?"
```

Example:

```text
get_owner_context(
    domain = "software.authentication"
)
```

Response:

```text
- prefers simple implementations
- avoids unnecessary infrastructure
- prioritizes maintainability over clever abstraction
```

This allows **implicit steering**.

Instead of Soulmate answering hundreds of micro-decisions, the agent receives relevant owner context once and naturally produces work closer to the user's expectations.

---

# 17. Token Strategy for MCP

MCP introduces some token overhead because:

1. Tool schemas are visible to the agent.
2. Tool calls may become part of agent context.
3. Tool responses consume context.

Therefore Soulmate should NOT expose:

```text
get_entire_personal_model()
```

or return large memory dumps.

Use:

```text
current task
      ↓
Context Compiler
      ↓
retrieve relevant Personal Model subset
      ↓
return compact structured context
```

Example:

```text
10,000 evidence records
        ↓
local retrieval
        ↓
3 relevant preferences
        ↓
~50-150 tokens returned to coding agent
```

Recommended principle:

> **Passive observation through hooks; expensive contextual communication only when decision support is useful.**

---

# 18. Avoid Model Contamination From AI Responses

Imported or observed AI conversations contain two very different actors:

```text
user
assistant
```

Soulmate should NOT treat AI-generated opinions as evidence about the user.

Example:

```text
Claude:
"You should use microservices."

This is NOT evidence that the user prefers microservices.
```

But:

```text
User:
"No, use a modular monolith. Microservices are unnecessary here."

This IS strong evidence.
```

Recommended extension to `RawEvent` or message metadata:

```text
actor_type:
    owner
    assistant
    system
    third_party
    agent
    unknown
```

And:

```text
evidence_eligibility:
    eligible
    contextual_only
    ignored
```

Default:

```text
owner statement       → evidence candidate
actual owner choice   → strong evidence
owner correction      → very strong evidence
agent response        → contextual_only
third-party content   → contextual_only
```

Assistant content may still be retained temporarily because it provides the context necessary to understand statements such as:

```text
"No, choose the second option."
```

But assistant content should not independently update the Personal Model.

---

# 19. New Source Provenance Requirements

The existing `Source` concept should be expanded.

Soulmate should know not only:

```text
where did this evidence come from?
```

but also:

```text
how was this data acquired?
```

Recommended metadata:

```text
Source {
    id
    type
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
}
```

Example:

```text
provider = "codex"
acquisition_method = "native_hook"
consent_mode = "user_enabled_connection"
author_scope = ["user", "agent"]
```

Another example:

```text
provider = "chrome"
acquisition_method = "extension_user_click"
author_scope = ["user"]
```

This makes data provenance explainable and auditable.

**Current status:** the existing `Source` record does not yet carry this complete
metadata. Phase 13 plans to finalize it in ADR-014 and migration
`0011_phase_13_decision_io`; neither exists yet.

---

# 20. Data Acquisition Policy Tiers

Soulmate should formally classify acquisition mechanisms.

## GREEN — Supported

Examples:

```text
official exports
official APIs
user-selected files
OS-supported integrations
native agent hooks
MCP integrations
Git repositories explicitly connected by user
share sheet
explicit extension actions
```

These should be allowed in the official project.

`GREEN` means an acquisition mechanism is eligible for implementation after the
normal architecture, consent, and phase review. It does not mean every listed
mechanism is currently shipped. Today, MCP, static imports, user-selected Local
Notes, and the connector framework exist; native hooks and explicit Git
observation do not.

---

## YELLOW — Requires Provider-Specific Review

Examples:

```text
browser DOM observation
browser extensions that automatically observe a site
accessibility-based observation
documented application-local data
```

These may be implemented only after checking:

```text
provider terms
platform rules
privacy consequences
```

They should require explicit user consent.

---

## RED — Unsupported

Examples:

```text
HTTPS MITM interception
root certificate installation for traffic inspection
session-cookie extraction
credential interception
reverse engineering private application databases
bypassing application sandboxing
undocumented private API circumvention
keylogging
```

These should NOT be part of Soulmate core.

Important principle:

> **Local storage does not automatically make the acquisition method acceptable.**

Privacy, provider Terms of Service, copyright/licensing, and applicable law are separate concerns.

---

# 21. AI Gateway

A Soulmate AI Gateway remains a useful optional integration.

This is NOT HTTPS interception.

Instead:

```text
Agent / Application
       │
       ▼
Soulmate AI Gateway
       │
       ▼
Official LLM API
```

For example:

```text
OPENAI_BASE_URL=http://localhost:<port>/v1
```

The gateway may:

```text
observe prompts
observe user corrections
detect decisions
record decisions
inject compact owner context
forward request to provider
capture results
```

Advantages:

```text
clean architecture
explicit configuration
provider-independent integration point
good source of structured AI workflow data
```

Limitation:

Consumer subscriptions such as ChatGPT Plus, Claude Max, etc. are not automatically equivalent to official API access.

Therefore native agent hooks may be more useful for tools such as Claude Code or Codex where users already have an existing workflow.

---

# 22. Browser Extension Direction

A browser extension may be useful, but should not become Soulmate's primary acquisition strategy.

Recommended modes:

```text
OFF

ASK
    user explicitly saves useful interaction

ON FOR THIS SITE
    explicit per-site authorization
```

Potential controls:

```text
Capture:
[x] messages written by me
[x] decisions/corrections
[ ] assistant responses
[ ] attachments
```

Avoid:

```text
silent always-on scraping of every AI conversation
```

Browser integrations should be treated as a secondary convenience integration, not the architectural foundation.

---

# 23. Process → Extract → Forget

Local-first should not mean:

```text
store every raw source forever
```

For high-volume sources:

```text
source data
    ↓
local processing
    ↓
RawEvent
    ↓
Evidence extraction
    ↓
structured Evidence
    ↓
optional deletion of raw source
```

Retention modes may include:

```text
retain_raw
delete_after_extraction
retain_recent_only
metadata_only
```

This reduces privacy risk while preserving useful learned information.

**Current status:** these are design candidates, not all delivered modes. In
particular, `delete_after_extraction` must not be offered until extraction has a
durable success marker and deletion is safely retryable. Phase 13 requires
unsupported retention modes to be rejected rather than silently ignored.

---

# 24. Core Learning Integrations Should Move Earlier

The original roadmap treated connectors and external-agent integration as
relatively late phases. That baseline has now moved: the MCP Decision Service was
delivered in Phase 9, the connector framework in Phase 11, and constrained
delegation in Phase 12.

Two connector categories should now be distinguished.

## Core Learning Integrations

Current and next work:

```text
Delivered: Soulmate REST/MCP decision access and micro-feedback
Planned Phase 13: Decision I/O protocol and trusted provenance
Directional Phase 14: first provider adapter and native hooks
Directional Phase 15: passive decision/correction capture
Directional Phase 16: Git outcome observer
Directional Phase 17: shadow prediction
Directional Phase 18: Owner Decision Service v2 and context steering
Directional Phase 19: second provider adapter
```

These integrations directly improve training and evaluation.

---

## General Life Connectors

Keep as later ecosystem work:

```text
calendar
email
browser
tasks
shopping history
personal documents
other SaaS integrations
```

Reason:

The next technical goal is not connector breadth.

It is:

> **build a continuous stream of high-quality decision/resolution/outcome data.**

---

# 25. Non-Tech User Experience

Users should never need to understand:

```text
MCP
hooks
JSON
daemon endpoints
configuration files
```

Desktop UI should eventually expose:

```text
Connections

Coding
────────────────────
Claude Code       [Connect]
Codex             [Connect]
VS Code           [Connect]

Productivity
────────────────────
GitHub            [Connect]
Calendar          [Connect]
Email             [Connect]

Browser
────────────────────
Soulmate Extension [Install]
```

Example:

```text
Connect Claude Code
        ↓
detect installation
        ↓
backup existing configuration
        ↓
install Soulmate MCP configuration
        ↓
install Soulmate hooks
        ↓
test connection
        ↓
done
```

The user sees:

```text
✓ Claude Code can now consult Soulmate
✓ Soulmate can learn from your corrections
```

Also provide:

```text
Disconnect
Undo configuration
View permissions
View captured data
```

The desired UX is:

> technically MCP/hooks underneath, but as simple as connecting a device.

---

# 26. Post-MVP Product Evolution: Owner Decision Service

Once the Personal Model reaches sufficient predictive quality, Soulmate should evolve from:

```text
personal prediction application
```

into:

```text
user-owned Owner Decision Service
```

The central question external agents ask becomes:

> **What would the owner want?**

Potential interfaces:

```text
consult_owner()
predict_owner()
rank_for_owner()
get_owner_context()
```

Soulmate should become personalization infrastructure rather than another general-purpose autonomous agent.

The first version of this role already exists through Phase 9's scoped REST/MCP
prediction tools and Phase 12's separate delegation workflow. The compact
`consult_owner`/`get_owner_context` v2 interface and task-scoped steering remain
directional Phase 18 work and require real-workflow evaluation first.

A useful architectural principle:

> **Other agents know how to do things. Soulmate knows how the owner wants things done.**

---

# 27. Responsibility Boundary Between Agent and Soulmate

Soulmate should NOT decide everything.

Decisions can be classified into four categories.

| Decision Type | Primary Decision Maker |
|---|---|
| Objective technical correctness | Agent / tools |
| Personal preference | Soulmate |
| Objective + personal trade-off | Agent + Soulmate |
| High-impact / irreversible / sensitive | User |

Example:

```text
"Does this code compile?"

→ not Soulmate's responsibility
```

```text
"Do I prefer Zustand or Redux here?"

→ Soulmate can help
```

```text
"Should we add another dependency to save two days of work?"

→ technical facts from agent
→ preference trade-off from Soulmate
```

```text
"Should production data be deleted?"

→ human authorization required
```

---

# 28. Soulmate Must Never Become a Security Permission Bypass

This distinction is critical.

Do NOT implement:

```text
agent requests dangerous permission
        ↓
Soulmate predicts user would approve
        ↓
permission automatically granted
```

Soulmate decisions are not equivalent to security authorization.

Example:

```text
"Should we use Zustand or Redux?"

Soulmate may decide.
```

But:

```text
"May I delete files outside the workspace?"

must remain governed by the agent/runtime security model.
```

Even if:

```text
Soulmate confidence = 99%
```

security boundaries must remain independent.

---

# 29. Delegation Ladder

Delegation should not be binary.

Phase 12 delivered a narrower, enforceable baseline rather than this entire
conceptual ladder. The owner configures one exact service-identity/action policy,
including impact, minimum confidence, and whether automation is allowed. Automatic
approval is limited to low impact at confidence >= 0.90 and medium impact at
confidence >= 0.95; high and safety-critical actions always require owner review.
Requests are prediction-bound, durable, idempotent, expire after 24 hours, and can
be completed once. Soulmate grants authority but does not execute or verify the
external side effect.

The broader ladder remains a future product model:

Introduce multiple levels.

| Level | Behavior |
|---|---|
| L0 — Context | Soulmate provides relevant owner preferences |
| L1 — Recommend | Soulmate recommends but agent remains responsible |
| L2 — Auto Delegate | Soulmate may decide low-impact reversible choices |
| L3 — Ask When Uncertain | auto only above confidence threshold |
| L4 — Always Human | high-impact / irreversible / sensitive |

Example:

```text
impact = low
reversible = true
confidence = 94%

→ auto delegation may be permitted
```

But:

```text
impact = high
confidence = 99%

→ ask user
```

Delegation policy must combine:

```text
impact
reversibility
confidence
permission
decision domain
```

In the current implementation, impact, confidence, permissions, and exact action
type are enforced. Reversibility and domain-aware policy are not yet implemented;
they are directional Phase 20 hardening and must not be inferred from agent input.

---

# 30. Coding Agents as the First Major Application

Coding is likely the best first vertical for Owner Decision integration.

A coding agent makes many implicit decisions:

```text
folder structure
library choice
architecture
abstraction level
naming
UI density
error handling
dependency selection
feature scope
test depth
performance trade-offs
code style
```

Generic agents optimize for:

```text
"What is generally good?"
```

Agent + Soulmate can optimize for:

```text
"What would this specific owner consider good?"
```

Architecture:

```text
               Coding Agent
                    │
       ┌────────────┼────────────┐
       │            │            │
       ▼            ▼            ▼
 compiler/tests   docs/tools   Soulmate
                                  │
                                  ├── preferences
                                  ├── goals
                                  ├── coding style
                                  ├── past decisions
                                  └── trade-offs
```

The expected result is not merely:

```text
working code
```

but:

```text
working code that more closely matches
how the owner would have implemented it
```

---

# 31. Agent Workflow Example

This is an illustrative future workflow, not current end-to-end product behavior.
It depends on later agent hooks, bounded context steering, correlation, and
observation/promotion work.

User:

```text
Build the Settings feature.
Continue until complete.
```

## Step 1 — Session Capture

Hook:

```text
SessionStart
```

Soulmate records:

```text
project
task
agent
timestamp
```

Additional coding-agent tokens:

```text
0
```

---

## Step 2 — Initial Personal Context

Agent calls:

```text
get_owner_context(
    domain="product.settings"
)
```

Soulmate returns:

```text
- prefers simple UX
- avoids unnecessary screens
- prefers local-first behavior
```

Small token cost.

---

## Step 3 — Meaningful Preference Decision

Agent must choose:

```text
A. Sidebar settings architecture
B. Single scrolling settings page
```

Agent calls:

```text
consult_owner(...)
```

Soulmate:

```text
B
confidence = 84%
```

Small token cost.

---

## Step 4 — Implementation

Agent modifies 15 files.

Hooks record activity.

Additional LLM tokens:

```text
0
```

---

## Step 5 — User Override

User changes part of the generated UI.

Soulmate detects:

```text
agent result
vs
user final result
```

Potential correction evidence is created.

Additional coding-agent tokens:

```text
0
```

---

## Step 6 — Outcome

Code is:

```text
kept
merged
tests passing
not reverted
```

Soulmate records an outcome.

No explicit user training session was required.

At this stage, `tests passing`, `kept`, or `merged` is only a technical
observation. It must not be stored as owner acceptance, satisfaction, regret, or
Preference Evidence without the trusted actor and promotion rules introduced by
the planned Decision I/O work.

---

# 32. Micro-Learning Remains Useful

Passive observation will not answer everything.

When model uncertainty is high, Soulmate should use lightweight micro-questions rather than long questionnaires.

Example:

```text
Which would you prefer?

A:
$20/month
1-minute setup

B:
Free
2-hour setup
```

One tap provides strong evidence about:

```text
money vs convenience
```

This should complement passive learning.

Micro-learning should preferably be triggered by:

```text
high uncertainty
+
high expected information value
```

rather than random questioning.

---

# 33. Proposed New Internal Event Taxonomy

A normalized cross-integration event model will likely be required.

Phase 13 now owns the contract freeze for this taxonomy. The plan uses a bounded,
versioned envelope with event types such as `interaction`, `decision_candidate`,
`decision_resolution`, `agent_proposal`, `user_override`, `action`,
`technical_outcome`, `user_outcome`, `correction`, and `context`. The exact
representation remains provisional until ADR-014 is accepted.

Potential event categories:

```text
InteractionEvent

DecisionCandidateEvent
DecisionResolutionEvent

AgentProposalEvent
UserOverrideEvent

ActionEvent
OutcomeEvent

TechnicalOutcomeEvent
UserOutcomeEvent

CorrectionEvent

ContextEvent
```

Provider adapters should normalize external events into these internal event categories.

Example:

```text
Codex PostToolUse
Claude Code PostToolUse
VS Code file edit event
```

may all become:

```text
ActionEvent
```

The Personalization Kernel should remain provider-independent.

---

# 34. Decision Detection Pipeline

Not every event should automatically become a decision.

Potential pipeline:

```text
RawEvent
    ↓
cheap heuristic filter
    ↓
possible decision?
    │
    ├── no → archive / ignore
    │
    └── yes
          ↓
DecisionCandidate
          ↓
structured extraction
          ↓
confidence threshold
          ↓
DecisionEvent
```

Detection may use:

```text
heuristics
local LLM
small classification model
structured agent metadata
explicit MCP calls
```

Explicitly structured agent decisions should have higher confidence than inferred decisions from arbitrary text.

---

# 35. Outcome Detection Pipeline

Similarly:

```text
Action / repository activity
        ↓
possible resolution/outcome
        ↓
link to previous DecisionEvent
        ↓
OutcomeCandidate
        ↓
confidence
        ↓
Outcome
```

Matching may use:

```text
session ID
project ID
file paths
decision IDs
temporal proximity
semantic similarity
explicit metadata
```

The system should tolerate unresolved outcomes.

Do not force every event into a decision lifecycle.

---

# 36. Important New Evaluation Dataset

Passive integrations provide a new evaluation opportunity.

Create a dataset of:

```text
decision context
options
Soulmate prediction
confidence
actual user choice
later user outcome
```

Especially valuable:

```text
shadow predictions
```

Metrics can then measure real-world prediction quality continuously.

This is superior to evaluating only synthetic or manually entered decisions.

---

# 37. Recommended Post-MVP Technical Workstreams

These workstreams remain useful, but their delivery status and mapping have
changed.

## Workstream A — Decision I/O Foundation

**Status:** planned as Phase 13; implementation has not started.

Build:

```text
normalized external decision schema
external decision ingestion
resolution ingestion
outcome ingestion
event correlation
source provenance extensions
```

---

## Workstream B — Agent Integration Framework

**Status:** directional Phase 14 and later; not implemented.

Build:

```text
AgentIntegration interface
hook adapter interface
provider-neutral event normalization
connection lifecycle
permissions
audit trail
```

Initial adapters:

```text
Codex
Claude Code
```

---

## Workstream C — MCP Owner Decision Service

**Status:** the Phase 9 REST/local-stdio MCP v1 and Phase 12 delegation tools are
delivered. The compact v2 facade and context steering are directional Phase 18.

Build:

```text
consult_owner
get_owner_context
rank_for_owner
```

Optimize:

```text
small schemas
small responses
minimal context/token overhead
```

---

## Workstream D — Passive Coding Capture

**Status:** directional Phases 15–16; not implemented.

Build:

```text
session capture
prompt capture
agent action capture
user override detection
Git observation
decision candidate detection
outcome detection
```

---

## Workstream E — Shadow Evaluation

**Status:** directional Phase 17; not implemented.

Build:

```text
shadow prediction
actual-choice matching
automatic evaluation
per-domain calibration analysis
```

---

## Workstream F — Delegation Policy

**Status:** the constrained Phase 12 Policy Engine is delivered. Reversibility,
domain policy, stronger real-world calibration, and external action verification
are not delivered; hardening is directional Phase 20.

Only after prediction quality is sufficiently reliable:

```text
impact classification
reversibility classification
confidence threshold
per-agent permissions
per-domain permissions
auto/recommend/ask policy
```

---

# 38. Suggested Implementation Order From the Existing MVP

Do not restart the original phase sequence: Phases 0–12 are complete locally. The
old lettered A–I proposal is superseded by the recorded repository roadmap:

| Phase | Direction | Status |
|---|---|---|
| 13 | Decision I/O and trusted provenance | Planned; not started; requires explicit authorization |
| 14 | Provider-neutral agent framework and one Codex vertical slice | Directional only |
| 15 | Passive decision and correction candidate detection | Directional only |
| 16 | Explicitly connected Git/repository outcome observation | Directional only |
| 17 | Shadow prediction and real-workflow evaluation | Directional only |
| 18 | Owner Decision Service v2 and task-scoped context steering | Directional only |
| 19 | Second live agent adapter and one-click connection lifecycle | Directional only |
| 20 | Delegation hardening | Directional only |
| 21 | Selected general-life connectors | Directional only |

Only Phase 13 has a recorded implementation plan. No Phase 14 or later
implementation is defined or authorized. Phase 13 must stop for owner review
after its exit criteria pass.

---

# 39. What Should NOT Be Built Yet

Avoid prematurely implementing:

```text
large browser scraping infrastructure
MITM proxy
private cache extraction
generic desktop surveillance
large connector marketplace
autonomous high-impact delegation
complex multi-agent orchestration
cloud synchronization
centralized telemetry
```

These do not directly help validate the immediate post-MVP hypothesis.

---

# 40. Immediate Post-MVP Hypothesis

The next question Soulmate should test is no longer only:

> Can Soulmate predict what the user would choose?

The next hypothesis should be:

> **Can Soulmate learn continuously from authorized real workflows and reduce the
> number of preference decisions that require owner intervention without
> increasing incorrect personalization or weakening security boundaries?**

For coding agents specifically:

> **Can a coding agent using Soulmate produce work that requires fewer user corrections than the same coding agent without Soulmate?**

Possible metrics:

```text
prediction accuracy
correction rate
revert rate
percentage of Soulmate decisions accepted
number of user interruptions
user modifications after agent completion
decision confidence calibration
task completion time
token overhead
```

---

# 41. Key Design Principles Going Forward

The new conclusions can be summarized in the following principles.

### 1. Learn from behavior, not only conversation.

```text
actual choices
corrections
overrides
outcomes
reverts
```

should become major learning signals.

### 2. Use hooks for observation and MCP for consultation.

Do not force everything through the LLM.

### 3. Keep passive capture cheap.

Passive learning should usually introduce:

```text
~0 additional external-agent tokens
```

### 4. Never treat AI output as user preference.

AI output is usually context, not evidence.

### 5. Separate technical success from user satisfaction.

A technically valid solution may still be wrong for this user.

### 6. Personalization is not authorization.

Soulmate must not bypass security boundaries.

### 7. Delegate gradually.

Use:

```text
context
recommend
auto
ask-on-uncertainty
always-human
```

instead of one autonomous mode.

### 8. Keep provider-specific logic outside the Personalization Kernel.

Codex, Claude Code, Git, VS Code, etc. should remain adapters.

### 9. Collect only authorized data.

Local-first does not justify invasive collection.

### 10. Optimize for non-technical users.

The final experience should be:

```text
Connect Codex
Connect Claude Code
```

not:

```text
manually configure MCP JSON
install hook scripts
edit daemon configuration
```

---

# 42. Final Product Direction

The long-term architecture should increasingly resemble:

```text
                       USER'S DIGITAL WORK
                               │
           ┌───────────────────┼────────────────────┐
           │                   │                    │
           ▼                   ▼                    ▼
      Coding Agents       Applications         Connectors
           │                   │                    │
           └───────────────────┼────────────────────┘
                               ▼
                      EVENT ACQUISITION
                               │
                               ▼
                VALIDATION + TRUST POLICY
              source / consent / actor / scope
             eligibility / idempotency / retention
                               │
                               ▼
                   RawEvent / Observation
                               │
                     explicit promotion
                               ▼
                           Evidence
                               │
                               ▼
                 ┌─────────────────────────┐
                 │     PERSONAL MODEL      │
                 │                         │
                 │ preferences             │
                 │ goals                   │
                 │ constraints             │
                 │ decisions               │
                 │ corrections             │
                 │ outcomes                │
                 │ uncertainty             │
                 └────────────┬────────────┘
                              │
                 ┌────────────┴─────────────┐
                 ▼                          ▼
           Context Service            Decision Service
                 │                          │
        "What matters to            "What would the
         this owner here?"           owner choose?"
                 │                          │
                 └────────────┬─────────────┘
                              ▼
                  PREDICTION / ADVICE
                              │
                    not authorization
                              │
               delegated action request only
                              ▼
                    PHASE 12 POLICY ENGINE
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          AUTO APPROVE       PENDING       OWNER REVIEW
          low/medium only                  high/safety
```

The Policy Engine applies only to explicit delegated-action requests. Ordinary
predictions, advice, context retrieval, and observations neither grant authority
nor bypass the external runtime's security boundary.

The strategic positioning is:

> **Soulmate is not primarily another AI agent.**

It is:

> **a user-owned Personal Decision Model and Owner Decision Service that other agents can consult.**

The most important long-term principle is:

> **Other agents know how to do things. Soulmate knows how the owner wants things done.**
