# Open Personal Decision Agent
## Technical Product Specification & Implementation Plan

**Document status:** Initial implementation specification  
**Target:** Open-source, local-first, self-hosted personal AI agent  
**Primary implementation audience:** software engineers / open-source contributors  
**Working project name:** `Soulmate`  
**License recommendation:** Apache-2.0  
**Architecture style:** Local-first modular monolith + hexagonal architecture  
**Primary language:** Python for core/service, TypeScript for clients

---

# 1. Product Vision

Soulmate is an open-source personal AI system whose primary goal is not to be the smartest general-purpose agent, but to understand one specific person as accurately as possible.

The system learns:

- what the owner likes and dislikes;
- what they value;
- their goals;
- their constraints;
- their behavioral patterns;
- how they weigh trade-offs;
- what decisions they made previously;
- whether they were satisfied with those decisions;
- how their preferences change depending on context;
- how confident the system should be about each belief.

The long-term goal is to create a **Personal Decision Model** capable of answering questions such as:

> What would I probably choose?

> Which option best matches my preferences?

> Knowing me and my long-term goals, what should I choose?

> If another AI needs to make this decision on my behalf, what would I likely want it to do?

The system must remain under the user's ownership and control.

There is no central Soulmate cloud service holding user profiles.

Each user runs their own Soulmate service.

---

# 2. Core Product Philosophy

The architecture MUST follow these principles.

## 2.1 Local First

All persistent personal data is stored on infrastructure controlled by the user.

Default:

```text
User's computer
    │
    ├── Soulmate daemon
    ├── SQLite database
    ├── embeddings
    ├── attachments
    ├── Personal Model
    └── encryption keys
```

No personal data is uploaded to a Soulmate-operated server.

---

## 2.2 Self Hosted

Users must be able to run Soulmate on:

```text
Mac
Windows
Linux
Home server
NAS
Raspberry Pi-class device where feasible
Personal VPS
```

Primary non-technical installation path:

```text
Install Desktop App
        ↓
Desktop launches local daemon
        ↓
Database created locally
        ↓
User starts chatting
```

Advanced installation paths:

```text
Docker Compose

or

soulmate serve
```

---

# 3. Explicit Non-Goals

The project is NOT initially intended to become:

- a SaaS personalization platform;
- a multi-tenant cloud product;
- a general autonomous agent framework;
- a replacement for OpenClaw/Hermes;
- a general knowledge assistant;
- a cloud synchronization service;
- a distributed microservice system;
- a Kubernetes platform.

Do not introduce infrastructure intended for millions of centralized users.

Do not introduce:

```text
Kafka
Kubernetes
Redis cluster
Neo4j
Elasticsearch
dedicated vector database
microservices
```

unless a future local use case provides a clear reason.

---

# 4. Key Architectural Idea

The most important architectural rule is:

```text
Agent != Personal Model
```

The system must be structured as:

```text
               Applications
                    │
       ┌────────────┼─────────────┐
       │            │             │
    Desktop       Mobile         Web
       │            │             │
       └────────────┼─────────────┘
                    │
                 API/MCP
                    │
                    ▼
          ┌───────────────────┐
          │ Personal Agent    │
          │ / Conversation    │
          └─────────┬─────────┘
                    │
                    ▼
╔══════════════════════════════════════════╗
║       PERSONALIZATION KERNEL             ║
║                                          ║
║ Memory Engine                            ║
║ Evidence Engine                          ║
║ User Model                               ║
║ Preference Learner                       ║
║ Decision Predictor                       ║
║ Context Compiler                         ║
║ Active Learning                          ║
║ Evaluation Engine                        ║
╚══════════════════════════════════════════╝
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
    SQLite      Model APIs    Local files
```

The Personalization Kernel MUST NOT depend on:

- FastAPI;
- MCP;
- desktop UI;
- mobile UI;
- OpenAI;
- Anthropic;
- Ollama;
- OpenClaw;
- Hermes;
- LangGraph.

These systems must depend on the kernel, not the other way around.

---

# 5. Personal Model vs Memory

Conversation history is NOT the Personal Model.

Architecture:

```text
Raw information
      ↓
RawEvent
      ↓
Evidence extraction
      ↓
Evidence
      ↓
Beliefs / Preferences / Goals / Constraints
      ↓
UserModelSnapshot
```

Example:

User says:

```text
"I don't really like subscription products."
```

Do NOT directly store:

```json
{
  "likes_subscription": false
}
```

Store evidence:

```json
{
  "target": "payment.subscription",
  "value": -0.6,
  "confidence": 0.72,
  "source_type": "explicit_statement",
  "context": {},
  "timestamp": "..."
}
```

Later the user repeatedly pays subscriptions for professional developer tools.

Those events produce additional evidence.

The derived Personal Model may eventually conclude:

```text
General subscription preference:
negative

Developer-tool subscription preference:
neutral/positive when productivity gain is high
```

Contradictory evidence is preserved rather than overwritten.

---

# 6. Event-Sourcing-Lite Principle

Original evidence should be immutable whenever practical.

Derived state must be rebuildable.

```text
RawEvent
   ↓
Evidence
   ↓
Derived Personal Model
```

Therefore:

```text
Delete source
      ↓
Delete evidence derived from source
      ↓
Rebuild model
```

This is essential for privacy and explainability.

A user must be able to ask:

> Why does the system think I prefer X?

The system must be able to return the supporting evidence.

---

# 7. Runtime Architecture

The local installation consists of several logical components.

```text
┌──────────────────────────────────────────────┐
│          Soulmate Local Host            │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ Soulmate Daemon                   │  │
│  │                                        │  │
│  │ API                                    │  │
│  │ Conversation                           │  │
│  │ Personalization Kernel                 │  │
│  │ Background Jobs                        │  │
│  │ Authentication                         │  │
│  │ MCP adapter                            │  │
│  └────────────────────────────────────────┘  │
│                     │                        │
│          ┌──────────┼──────────┐             │
│          ▼          ▼          ▼             │
│       SQLite     Vector     Filesystem       │
│                  Index                       │
│                                              │
└──────────────────────────────────────────────┘
                  ▲
                  │
       HTTPS / WebSocket / MCP
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
      Phone     Desktop    External
       App       App       Agents
```

---

# 8. Technology Stack

## 8.1 Core / Daemon

Use:

```text
Python 3.12+
FastAPI
Pydantic v2
SQLAlchemy 2
Alembic
NumPy
SciPy
scikit-learn where appropriate
```

Package/dependency manager:

```text
uv
```

Quality tools:

```text
ruff
mypy
pytest
```

---

# 9. Default Database

Use:

```text
SQLite
```

Reasons:

- zero setup;
- single local file;
- easy backup;
- easy export;
- works offline;
- cross-platform;
- well suited to one person's data;
- no background DB server;
- desktop packaging is much simpler.

Use SQLite WAL mode.

Recommended:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

---

# 10. Storage Abstraction

Core domain logic MUST NOT import SQLite-specific code.

Define interfaces such as:

```python
class EventRepository: ...


class EvidenceRepository: ...


class PreferenceRepository: ...


class DecisionRepository: ...


class MemoryRepository: ...


class SnapshotRepository: ...


class VectorStore: ...
```

Default implementation:

```text
SQLite repositories
```

Optional future implementation:

```text
PostgreSQL + pgvector
```

This is intended for advanced self-hosters, not centralized SaaS scaling.

---

# 11. Vector Search

Use a `VectorStore` abstraction.

Preferred default:

```text
SQLite + sqlite-vec
```

A fallback implementation should exist for systems where native extensions are unavailable:

```text
SQLite vectors
+
application-side cosine similarity
```

For a normal single-user installation, brute-force search over several thousand or tens of thousands of memories is acceptable initially.

Do not make the whole application depend on a vector extension.

---

# 12. Local File Storage

Do not introduce S3/MinIO for the standard installation.

Use:

```text
DATA_DIR/
├── soulmate.db
├── objects/
│   ├── ab/
│   │   └── <sha256>
│   └── ...
├── models/
├── indexes/
├── logs/
└── backups/
```

Objects should preferably be content-addressed using SHA-256.

---

# 13. Domain Model

Core entities:

```text
Profile

Source
RawEvent

Evidence

Memory

Preference
Goal
Constraint
Fact

DecisionEvent
DecisionOption
DecisionPrediction
DecisionResolution

Outcome
Regret

UserModelSnapshot

Conversation
Message

ActiveQuestion
QuestionAnswer

ClientDevice
ServiceIdentity
ApiCredential
Permission

AuditEvent

Job
```

The runtime initially supports one owner profile.

Internally, data MAY include:

```text
profile_id
```

to make testing and possible future multi-profile support easier.

This does NOT imply multi-tenancy.

---

# 14. RawEvent

Anything entering the learning system first becomes a `RawEvent`.

Example sources:

```text
conversation
explicit preference
decision
decision feedback
outcome
imported ChatGPT history
imported notes
external connector
manual profile entry
```

Suggested structure:

```json
{
  "id": "evt_...",
  "profile_id": "profile_default",
  "source_id": "source_...",
  "event_type": "conversation_message",
  "content": {},
  "created_at": "...",
  "ingested_at": "...",
  "sensitivity": "normal"
}
```

---

# 15. Evidence Model

Evidence is a claim that contributes toward understanding the user.

Example:

```json
{
  "id": "ev_...",
  "target_type": "preference",
  "target_key": "work.remote",
  "value": 0.85,
  "strength": 0.7,
  "confidence": 0.9,

  "context": {
    "domain": "career"
  },

  "source_type": "actual_choice",
  "source_event_id": "evt_...",

  "extractor_version": "preference-extractor-v1",

  "created_at": "..."
}
```

Evidence must record provenance.

---

# 16. Evidence Reliability

Initial evidence weighting strategy:

```text
casual inference           low
explicit user statement   medium
hypothetical scenario     medium
pairwise calibration      medium/high
actual decision           high
repeated actual decisions very high
user correction           very high
outcome/regret feedback   very high
```

Do NOT hardcode final scientific values into the domain model.

The weighting strategy must be configurable and versioned.

---

# 17. Preferences

A preference is derived state.

Example:

```json
{
  "key": "career.remote_work",

  "value": 0.82,
  "uncertainty": 0.14,
  "confidence": 0.87,

  "context": {
    "domain": "career"
  },

  "supporting_evidence_count": 14,

  "updated_at": "...",
  "model_version": 17
}
```

Preference scale:

```text
-1                       0                       +1
strongly dislike       neutral               strongly prefer
```

Every preference should include uncertainty.

---

# 18. Context-Dependent Preferences

Do NOT assume:

```text
preference(user) = constant
```

Instead model:

```text
preference(user, context)
```

Example:

```text
price sensitivity
```

may be high for:

```text
entertainment
```

but low for:

```text
professional tools used every day
```

Preference lookup should consider:

```text
global preference

domain preference

task-specific preference

similar historical contexts
```

---

# 19. Decision Event

A DecisionEvent represents an actual decision situation.

Example:

```json
{
  "id": "dec_123",

  "domain": "career",

  "question": "Which job should I choose?",

  "context": {
    "goal": "choose_next_job"
  },

  "status": "resolved",

  "created_at": "..."
}
```

---

# 20. Decision Options

Each decision has structured options.

Example:

```json
{
  "id": "option_a",

  "label": "Company A",

  "features": {
    "salary": 4000,
    "remote": 1,
    "commute_minutes": 0,
    "career_growth": 0.7,
    "stability": 0.8,
    "technical_interest": 0.9
  }
}
```

LLMs may help extract these features from natural language.

The structured representation becomes the source used by the Decision Model.

---

# 21. Decision Prediction

Prediction output:

```json
{
  "decision_id": "dec_123",

  "ranking": [
    {
      "option_id": "option_a",
      "probability": 0.74
    },
    {
      "option_id": "option_b",
      "probability": 0.26
    }
  ],

  "confidence": 0.79,

  "important_factors": [
    "remote_work",
    "technical_interest"
  ],

  "uncertain_factors": [
    "short_term_income"
  ],

  "similar_decisions": [
    "dec_88",
    "dec_101"
  ],

  "model_version": 17
}
```

---

# 22. Two Separate Decision Modes

These MUST remain conceptually separate.

## Mode A — Predict Me

Question:

```text
What would I choose?
```

Model:

```text
P(choice | user, context)
```

This models actual human behavior.

---

## Mode B — Advise Me

Question:

```text
Knowing me, what should I choose?
```

This can combine:

```text
personal preferences
+
long-term goals
+
constraints
+
known outcomes
+
objective information
```

It is valid for the system to say:

```text
I predict that you would choose A.

However, based on your stated long-term goal,
I recommend B.
```

Never silently merge descriptive prediction with normative recommendation.

---

# 23. Decision Learning V1

Do not start with deep learning.

Initial utility function:

```text
U(option, context)
    =
preference weights
×
option features
+
similar-decision prior
```

Option probability:

```text
softmax(U)
```

Confidence should consider:

```text
probability margin
evidence quantity
evidence consistency
feature extraction confidence
similarity to historical decisions
out-of-distribution context
```

---

# 24. Pairwise Preference Learning

Later V1/V2 learning can use pairwise comparisons:

```text
A > B
```

Model:

```text
P(A > B) = sigmoid(U(A) - U(B))
```

Use online logistic / Bradley-Terry-style learning.

Suitable libraries:

```text
NumPy
SciPy
scikit-learn
```

Do not introduce PyTorch until there is evidence it is necessary.

---

# 25. Active Learning

The system should identify parts of the owner model that remain uncertain.

Example:

```text
speed vs quality:
uncertainty = high
```

Instead of asking many generic personality questions, generate a high-information comparison:

```text
A:
finish tomorrow
quality 80%

B:
finish four days later
quality 95%
```

The question selection subsystem should eventually optimize:

```text
Expected Information Gain
```

Initial implementation can use heuristics.

---

# 26. Outcome Learning

A decision does not end when an option is selected.

Support:

```text
Decision
    ↓
Choice
    ↓
Outcome
    ↓
Satisfaction
    ↓
Possible regret
```

Example:

```json
{
  "decision_id": "dec_123",
  "satisfaction": 0.3,
  "regret": true,
  "notes": "The maintenance cost was much higher than expected."
}
```

This allows Soulmate eventually to distinguish:

```text
what the user tends to choose
```

from:

```text
what tends to make the user happy afterward
```

---

# 27. Personal Model Snapshot

Derived model state must be versioned.

Example:

```json
{
  "version": 17,

  "preferences": {},
  "goals": {},
  "facts": {},
  "constraints": {},

  "uncertainty_summary": {},

  "evidence_revision": 2041,

  "created_at": "..."
}
```

Every prediction stores the model snapshot version used.

This makes decisions reproducible and debuggable.

---

# 28. Role of the LLM

LLMs are adapters and reasoning tools, NOT the authoritative Personal Model.

Approved LLM responsibilities:

```text
intent detection

extracting evidence

extracting decision options

extracting option features

summarization

natural-language explanations

generating active-learning questions

general reasoning
```

LLMs should NOT directly mutate preferences.

Instead:

```text
LLM
 ↓
structured Evidence proposal
 ↓
validation
 ↓
Evidence store
 ↓
Preference Learner
```

---

# 29. LLM Provider Abstraction

Define an interface similar to:

```python
class LLMProvider:
    async def generate(...)
    async def generate_structured(...)
    async def embed(...)
```

Application code must never contain provider-specific calls scattered through business logic.

Adapters may include:

```text
OpenAI-compatible API
Ollama
OpenAI
Anthropic
Gemini
LiteLLM
```

LiteLLM may be used as an adapter/library but MUST NOT become a dependency of the Personalization Kernel.

---

# 30. Privacy Modes

Support three explicit operating modes.

## STRICT_LOCAL

```text
All data local
All embeddings local
All inference local
No personal data sent externally
```

External network access from AI components should be denied unless explicitly enabled.

---

## HYBRID

User may configure external AI providers.

Only the minimum required context should leave the machine.

The UI must indicate when content will be sent to an external provider.

---

## OFFLINE

No network access.

Local inference only.

Suitable for highly privacy-sensitive installations.

---

# 31. Network Egress Policy

Implement a central `EgressPolicy`.

Do not let individual components independently perform arbitrary network requests.

Example:

```python
EgressPolicy.can_send(
    provider="anthropic",
    data_classification="personal",
)
```

All cloud model calls should pass through this layer.

Future connectors should also respect it.

---

# 32. Cloud Request Transparency

For hybrid mode, users should eventually be able to inspect:

```text
which provider was called
when
which model
why it was called
which data classes were included
token usage
```

Avoid unnecessarily storing raw prompts containing sensitive information in logs.

---

# 33. Local Service API

Initial API namespace:

```text
/v1
```

Core endpoints:

```text
POST /v1/chat

POST /v1/decisions
POST /v1/decisions/{id}/predict
POST /v1/decisions/{id}/resolve

POST /v1/decisions/{id}/outcome

GET  /v1/model/summary
GET  /v1/preferences
GET  /v1/goals
GET  /v1/memories

POST /v1/preferences/corrections

GET  /v1/evidence/{id}
GET  /v1/preferences/{key}/evidence

POST /v1/pairing/start
POST /v1/pairing/complete

GET  /v1/health
GET  /v1/system/info
```

---

# 34. Corrections Must Create Evidence

If the user changes:

```text
Remote work preference:
0.8 → 0.3
```

do NOT simply update the database value.

Create correction evidence:

```text
User correction
      ↓
Evidence
      ↓
Model rebuild/update
```

This preserves history and explainability.

---

# 35. Context Compiler

Do not send the entire personal database to an LLM.

Pipeline:

```text
Current task
     ↓
detect domain
     ↓
retrieve relevant preferences
     ↓
retrieve relevant goals
     ↓
retrieve relevant constraints
     ↓
retrieve similar decisions
     ↓
retrieve relevant memories
     ↓
build minimal Personal Context
```

Example:

```json
{
  "domain": "career",

  "preferences": [
    ["remote_work", 0.84],
    ["career_growth", 0.91]
  ],

  "goals": [
    "become engineering lead"
  ],

  "similar_decisions": [
    "..."
  ]
}
```

Benefits:

```text
lower token usage
better privacy
better explanations
less hallucination
better reproducibility
```

---

# 36. Memory Types

Support logical memory categories:

```text
Working memory
Episodic memory
Semantic memory
Preference memory
Decision memory
Outcome memory
Meta-memory
```

Decision, Preference and Outcome memory should receive higher architectural importance than generic conversational memories.

---

# 37. Desktop Application

Preferred stack:

```text
Tauri 2
React
TypeScript
Vite
```

Desktop app responsibilities:

```text
install/manage daemon
start/stop daemon
display system health
chat UI
decision UI
Personal Model UI
history
privacy settings
provider settings
pair mobile devices
manage API credentials
backup/export
update application
```

The daemon should be packaged as a Tauri sidecar executable.

---

# 38. Daemon Packaging

Development:

```bash
uv run soulmate serve
```

Release:

Build standalone daemon using a suitable packaging mechanism such as:

```text
PyInstaller
or
Nuitka
```

Bundle per platform.

Desktop users should NOT be required to separately install:

```text
Python
PostgreSQL
Docker
Node.js
```

---

# 39. Mobile Client

Recommended:

```text
React Native
Expo where practical
```

The mobile application is a client.

It does NOT contain the primary Personal Model.

```text
Phone
   │
   │ secure connection
   ▼
Soulmate service
running on owner's machine
```

Initial mobile functionality:

```text
chat
submit decision
view recommendation
view model summary
provide feedback
record outcome
```

---

# 40. Web Client

Provide a lightweight web client served by the daemon.

Example:

```text
http://localhost:PORT
```

or secure LAN URL.

This gives users an interface without requiring the desktop shell.

Desktop can reuse much of the same React UI.

---

# 41. Network Binding

Default daemon behavior:

```text
127.0.0.1 only
```

LAN access must require explicit user activation.

Never bind to:

```text
0.0.0.0
```

silently.

---

# 42. Mobile Pairing

Recommended pairing flow:

```text
Desktop:
Enable mobile access
      ↓
Daemon creates one-time pairing secret
      ↓
Desktop displays QR code

Phone:
Scan QR
      ↓
Verify service fingerprint
      ↓
Exchange pairing secret
      ↓
Receive device credential
```

QR data may include:

```text
service URL
service ID
certificate fingerprint
one-time pairing token
```

Pairing tokens:

```text
short expiration
one use only
high entropy
```

---

# 43. LAN Encryption

When accessing over LAN, traffic must be encrypted.

The daemon may generate its own local TLS certificate.

Mobile client can use certificate fingerprint pinning established during QR pairing.

This avoids sending private conversations over plain HTTP on Wi-Fi.

---

# 44. Remote Access

Remote Internet exposure is NOT required for initial versions.

Supported documented approaches may include:

```text
VPN
Tailscale-like private networks
WireGuard
SSH tunnel
reverse proxy with HTTPS
```

Do not build a proprietary relay service initially.

Users remain responsible for deciding whether their instance should be reachable remotely.

---

# 45. External Agent Integration

Soulmate should eventually operate as a Personal Intelligence Layer.

External systems should be able to ask questions such as:

```text
Which option would the owner prefer?

Rank these products.

Would the owner accept this meeting?

What trade-offs matter to the owner here?
```

Expose through:

```text
REST API
MCP
```

---

# 46. MCP Server

Provide MCP tools such as:

```text
predict_choice

rank_options

ask_owner_model

get_preference_summary

find_similar_decisions

record_decision

record_outcome
```

Raw memory access should NOT automatically be exposed.

External agents usually need the result of personalization, not the entire user's private history.

---

# 47. External Service Identities

External agents/services receive separate identities.

Example:

```text
Claude
OpenClaw
Home Assistant
shopping-agent
calendar-agent
```

Each gets independent credentials and permissions.

---

# 48. Permission Scopes

Possible scopes:

```text
model:summary:read

decision:predict

decision:record

outcome:record

preference:summary:read

memory:read

memory:write

agent:delegate
```

Principle of least privilege must be applied.

---

# 49. Delegated Decision Making

Do NOT allow arbitrary external agents to automatically make irreversible decisions in early phases.

Future delegation policy:

```text
low impact:
automatic allowed

medium impact:
automatic only when confidence > threshold

high impact:
user confirmation required

safety-critical / irreversible:
confirmation required regardless of confidence
```

Delegation policy belongs to a separate Policy Engine.

---

# 50. Audit Log

Record important actions locally:

```text
external API calls

prediction requests

credential creation

pairing

permission changes

data exports

model provider calls

data deletion
```

Audit logs must remain local.

---

# 51. Local Background Jobs

Do not initially add Redis/RabbitMQ.

Use:

```text
asyncio worker
+
durable SQLite jobs table
```

Possible jobs:

```text
extract evidence
generate embeddings
summarize conversation
rebuild model
evaluate prediction
process imported history
backup
```

Incomplete durable jobs should resume after restart.

---

# 52. Connector Architecture

Future integrations must use an adapter:

```python
class SourceConnector:
    async def authenticate(...)
    async def sync(...)
    async def normalize(...) -> list[RawEvent]
```

Possible future connectors:

```text
ChatGPT history export
Claude history
notes
calendar
email
browser history
GitHub
Spotify
shopping history
personal documents
```

Connectors output `RawEvent`.

They do not directly modify the Personal Model.

---

# 53. Import First, Live Connectors Later

Privacy-friendly prioritization:

First support static imports:

```text
ChatGPT export
JSON
Markdown
plain text
decision history
```

Only later implement live external connectors requiring credentials.

---

# 54. Backup

Provide:

```bash
soulmate backup
```

Backup should include:

```text
database
objects
vector index if required
model snapshots
```

Secrets should either:

- not be included; or
- require explicit encrypted export.

---

# 55. Portable Export

Define a portable archive format later, e.g.:

```text
.dtw
```

Possible layout:

```text
manifest.json
database.sqlite
objects/
model/
```

Archive must support encryption using a user-provided passphrase.

A user should eventually be able to move their Personal Model from one machine to another without a cloud service.

---

# 56. Secrets

Store provider API keys and sensitive credentials using:

```text
macOS Keychain
Windows Credential Manager
Linux Secret Service
```

Fallback:

encrypted local secrets store.

Do NOT store provider API keys in plaintext SQLite records.

---

# 57. Telemetry

Default:

```text
no analytics
no tracking
no remote telemetry
```

Any future diagnostics must be explicitly opt-in.

The open-source project must remain fully usable without connecting to Soulmate infrastructure.

---

# 58. Observability

Local debugging should use:

```text
structured logs
OpenTelemetry-compatible tracing
```

But do not persist complete private prompts by default.

Example trace:

```text
decision.predict
 ├── context.compile
 ├── preferences.retrieve
 ├── similar_decisions.retrieve
 ├── options.extract
 ├── utility.calculate
 └── explanation.generate
```

---

# 59. User-Facing Explainability

Prediction:

```text
I think you would choose B — 78%.
```

Should be able to expand:

```text
Why?

1. You strongly prefer remote work.
2. You have prioritized technical growth over short-term salary
   in 4 similar decisions.
3. Your price/salary preference is less certain.
```

Each explanation should map back to real internal evidence where possible.

---

# 60. Personal Model UI

A key screen:

```text
MY MODEL
```

Examples:

```text
Remote work
strong preference
confidence: high

Career growth
very strong preference
confidence: high

Price sensitivity
moderate preference
confidence: medium

Speed vs quality
unknown
confidence: low
```

User actions:

```text
Why?
Correct this
See evidence
Remove evidence
Ask me about this
```

This screen is a major product differentiator.

---

# 61. Main Product Screens

Initial interfaces:

```text
Chat

Decide

My Model

Decision History

Settings
```

Later:

```text
Connections

External Agents

Audit Log

Data & Privacy
```

---

# 62. Repository Structure

Recommended monorepo:

```text
soulmate/
│
├── apps/
│   ├── daemon/
│   ├── desktop/
│   ├── mobile/
│   ├── web/
│   └── mcp/
│
├── packages/
│   ├── core-python/
│   │   ├── domain/
│   │   ├── evidence/
│   │   ├── memory/
│   │   ├── preferences/
│   │   ├── decisions/
│   │   ├── learning/
│   │   ├── context/
│   │   └── evaluation/
│   │
│   ├── storage-sqlite/
│   ├── llm-providers/
│   ├── sdk-typescript/
│   └── sdk-python/
│
├── migrations/
│
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── security/
│   └── contributor-guide/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── evaluation/
│   └── fixtures/
│
├── scripts/
│
├── docker/
│
├── pyproject.toml
├── pnpm-workspace.yaml
├── docker-compose.yml
├── LICENSE
├── CONTRIBUTING.md
└── README.md
```

---

# 63. Hexagonal Architecture

Dependencies:

```text
Domain
  ▲
  │
Application services
  ▲
  │
Adapters
  ▲
  │
FastAPI / SQLite / LLM / MCP
```

The domain package MUST have no dependency on infrastructure packages.

---

# 64. Testing Strategy

Four test layers.

## Unit

Test:

```text
preference aggregation
utility scoring
confidence calculation
evidence handling
model rebuild
permissions
```

No network.

No real LLM.

---

## Integration

Test:

```text
SQLite
API
migrations
background jobs
LLM adapters with fake provider
```

---

## Evaluation

Maintain synthetic/pseudonymous decision datasets.

Compare:

```text
LLM only

LLM + conversation history

LLM + retrieved memories

structured Personal Model

Soulmate Decision Model
```

Metrics:

```text
Top-1 accuracy
Top-2 accuracy
log loss
Brier score
calibration error
ranking correlation
```

---

## End-to-End

Test:

```text
install
start daemon
create profile
chat
extract evidence
make decision
predict
resolve
update model
restart daemon
verify persistence
```

---

# 65. Architecture Decision Records

Significant decisions must receive an ADR under:

```text
docs/architecture/decisions/
```

Initial ADRs:

```text
ADR-001 Local-first architecture

ADR-002 SQLite as default persistence

ADR-003 Personalization Kernel independent of agent runtime

ADR-004 Evidence-based derived Personal Model

ADR-005 LLM provider abstraction

ADR-006 No cloud telemetry by default

ADR-007 Desktop daemon model

ADR-008 REST + MCP external integration
```

---

# 66. CLI

Provide:

```bash
soulmate serve

soulmate status

soulmate doctor

soulmate pair

soulmate backup

soulmate export

soulmate import

soulmate rebuild-model
```

`doctor` should detect:

```text
database problems
port conflicts
LLM provider configuration
filesystem permissions
migration status
vector backend
```

---

# 67. Configuration

Example:

```toml
[server]
host = "127.0.0.1"
port = 7432

[privacy]
mode = "strict_local"

[storage]
backend = "sqlite"
path = "./data/soulmate.db"

[vector]
backend = "sqlite_vec"

[llm]
provider = "ollama"

[llm.ollama]
base_url = "http://127.0.0.1:11434"
model = "..."

[embedding]
provider = "local"
```

Environment variables may override configuration.

---

# 68. Development Principle

Every feature should answer:

```text
Can this work completely locally?

Can the user inspect what it learned?

Can the user delete it?

Can the model explain why it believes it?

Can another provider replace the current LLM?

Can another client use the same Personal Model?
```

If not, reconsider the implementation.

---

# 69. Implementation Roadmap

The following phases are intended to be implemented sequentially.

Do not begin later phases until the previous phase's acceptance criteria pass.

---

# PHASE 0 — Repository & Architecture Foundation

## Goal

Create a clean project skeleton and freeze architectural boundaries before implementing product logic.

## Tasks

### P0-01 Repository

Create monorepo structure.

Configure:

```text
uv
pnpm
pytest
ruff
mypy
pre-commit
GitHub Actions
```

### P0-02 Core Domain Package

Create infrastructure-independent domain package.

No FastAPI imports.

No SQLAlchemy imports.

No LLM provider imports.

### P0-03 Configuration

Implement typed configuration.

Support:

```text
config.toml
environment overrides
DATA_DIR
```

### P0-04 ADRs

Add ADR-001 through ADR-008.

### P0-05 CI

Run:

```text
lint
type check
unit tests
```

on Linux/macOS/Windows where practical.

## Exit Criteria

```text
repository installs successfully

empty daemon starts

core package does not depend on infrastructure

test suite executes

CI passes
```

---

# PHASE 1 — Local Daemon & Persistence

## Goal

Produce the first functioning local Soulmate service.

## Tasks

### P1-01 SQLite

Implement:

```text
SQLite engine
WAL
migrations
repository interfaces
```

### P1-02 Base Tables

Implement:

```text
profiles
sources
raw_events
audit_events
jobs
system_metadata
```

### P1-03 Daemon

Create FastAPI daemon.

Endpoints:

```text
GET /v1/health
GET /v1/system/info
```

### P1-04 Local Security

Default:

```text
127.0.0.1
```

Generate local installation identity.

### P1-05 CLI

Implement:

```text
serve
status
doctor
```

### P1-06 Durable Jobs

Implement simple local background worker.

## Exit Criteria

A developer can run:

```bash
uv run soulmate serve
```

and receive:

```text
healthy local service
persistent SQLite DB
successful restart
automatic migration
```

---

# PHASE 2 — Evidence & Personal Model Foundation

## Goal

Implement the fundamental model of how Soulmate understands a user.

## Tasks

### P2-01 RawEvent

Implement schema and repository.

### P2-02 Evidence

Implement:

```text
Evidence
provenance
confidence
strength
context
source linkage
```

### P2-03 Derived State

Implement:

```text
Fact
Preference
Goal
Constraint
```

### P2-04 Evidence Aggregation

Implement first deterministic aggregation algorithm.

Do not use an LLM for aggregation.

### P2-05 Model Snapshot

Implement versioned `UserModelSnapshot`.

### P2-06 Rebuild

Implement:

```bash
soulmate rebuild-model
```

Given the same evidence and algorithm version, rebuild must be deterministic.

### P2-07 Explainability

API must return supporting evidence for a derived preference.

## Exit Criteria

Tests demonstrate:

```text
multiple evidence items produce a preference

contradictory evidence is preserved

correction changes derived preference

removing evidence and rebuilding changes model

snapshot versions are created
```

---

# PHASE 3 — Conversation & Evidence Extraction

## Goal

Allow users to communicate naturally with Soulmate and learn basic information from conversations.

## Tasks

### P3-01 LLM Provider Interface

Implement provider abstraction.

### P3-02 Fake Provider

Create deterministic fake LLM for tests.

### P3-03 Ollama Adapter

Implement local provider.

### P3-04 OpenAI-Compatible Adapter

Implement generic compatible endpoint.

### P3-05 Conversation

Tables:

```text
conversations
messages
```

API:

```text
POST /v1/chat
```

### P3-06 Evidence Extractor

LLM returns structured proposals:

```text
facts
preferences
goals
constraints
```

Validate with Pydantic.

### P3-07 Evidence Review

Initially allow automatic acceptance for low-risk ordinary preferences.

Mark all extracted evidence with:

```text
extractor model
extractor version
source message
```

### P3-08 Context Compiler v1

Retrieve only relevant Personal Model information for chat.

## Exit Criteria

User can:

```text
chat with daemon

state preferences naturally

see structured preferences appear

inspect why the system learned them

restart daemon without losing information
```

---

# PHASE 4 — Decision MVP

## Goal

Implement the first core differentiating feature:

```text
"What would I choose?"
```

## Tasks

### P4-01 Decision Schema

Implement:

```text
DecisionEvent
DecisionOption
DecisionPrediction
DecisionResolution
```

### P4-02 Decision Detection

Support explicit decision API first.

Chat auto-detection can follow.

### P4-03 Feature Extraction

Convert natural options into structured option features.

### P4-04 Preference Matching

Map option features to relevant Personal Model preferences.

### P4-05 Utility Scoring

Implement deterministic V1 utility model.

### P4-06 Probability Ranking

Output probabilities.

### P4-07 Confidence

Implement initial confidence estimator.

### P4-08 Similar Decision Retrieval

Retrieve previous decisions based on:

```text
domain
structured features
semantic similarity
```

### P4-09 Explanation

Generate:

```text
predicted choice
probability
confidence
important factors
uncertain factors
supporting evidence
similar decisions
```

### P4-10 Resolution

User records actual choice.

That creates high-value evidence.

## Exit Criteria

Full flow works:

```text
user submits A/B/C

system predicts B

user resolves actual choice C

new evidence is created

Personal Model updates

next prediction uses new evidence
```

This is the first true Soulmate MVP.

---

# PHASE 5 — Preference Learning & Evaluation

## Goal

Move from heuristic personalization toward measurable preference learning.

## Tasks

### P5-01 Evaluation Dataset

Create fixture decisions with known owner choices.

### P5-02 Metrics

Implement:

```text
accuracy
Top-2 accuracy
log loss
Brier score
calibration
```

### P5-03 Baselines

Evaluate:

```text
random

LLM-only

memory-only

Personal Model

Decision Model
```

### P5-04 Pairwise Learning

Implement online Bradley-Terry/logistic preference updates.

### P5-05 Contextual Preferences

Add:

```text
global
domain-specific
context-specific
```

weights.

### P5-06 Confidence Calibration

Evaluate whether:

```text
80% confidence predictions
```

are actually correct approximately 80% of the time.

### P5-07 Model Algorithm Versioning

Predictions store learning algorithm version.

## Exit Criteria

Automated evaluation command such as:

```bash
soulmate evaluate
```

produces reproducible metrics.

Every change to decision-learning logic can be objectively compared.

---

# PHASE 6 — Desktop Product

## Goal

Allow normal users to install and use Soulmate without developer tools.

## Tasks

### P6-01 Tauri Shell

Create desktop app.

### P6-02 Daemon Sidecar

Package daemon for:

```text
macOS
Windows
Linux
```

### P6-03 Service Management

Desktop controls:

```text
start
stop
restart
health
logs
```

### P6-04 Main UI

Implement:

```text
Chat
Decide
My Model
Decision History
Settings
```

### P6-05 Provider Configuration

Support:

```text
local Ollama
custom OpenAI-compatible API
optional cloud providers
```

### P6-06 Privacy Mode

UI for:

```text
STRICT_LOCAL
HYBRID
OFFLINE
```

### P6-07 My Model Screen

User can:

```text
inspect
correct
see evidence
delete evidence
```

## Exit Criteria

A non-developer can install Soulmate and use it without:

```text
Docker
Python
Node
terminal
```

---

# PHASE 7 — Mobile/Web Clients & Secure Pairing

## Goal

Allow the user to access their personal agent from another device while keeping data on their own machine.

## Tasks

### P7-01 Web Client

Serve web client from daemon.

### P7-02 LAN Mode

Explicit setting:

```text
Enable access from other devices
```

### P7-03 Local TLS

Generate service certificate.

### P7-04 Pairing

Implement one-time QR pairing.

### P7-05 Device Credentials

Store paired devices and allow revocation.

### P7-06 Mobile Client

React Native app.

Initial screens:

```text
Connect
Chat
Decide
My Model
History
```

### P7-07 Certificate Pinning

Phone pins paired server fingerprint.

## Exit Criteria

User can:

```text
install Soulmate on PC

scan QR with phone

communicate securely over LAN

revoke phone from desktop

keep all Personal Model data on PC
```

---

# PHASE 8 — Active Learning & Outcome Intelligence

## Goal

Make Soulmate deliberately improve areas where it does not understand the user.

## Tasks

### P8-01 Uncertainty Model

Track preference uncertainty.

### P8-02 Active Question Generator

Generate questions targeting uncertain trade-offs.

### P8-03 Question Ranking

Initial heuristic information-gain score.

### P8-04 Outcome Tracking

Implement:

```text
decision outcomes
satisfaction
regret
```

### P8-05 Behavioral vs Wellbeing Model

Separate:

```text
What will I choose?
```

from:

```text
What historically gives me better outcomes?
```

### P8-06 Advise Me

Implement initial normative recommendation mode.

## Exit Criteria

Soulmate can explain:

```text
I know you tend to choose A.

However, similar choices previously had low satisfaction,
so I recommend considering B.
```

---

# PHASE 9 — MCP & External Personal Intelligence API

## Goal

Allow other applications and agents to consult Soulmate.

## Tasks

### P9-01 Service Identity

Create credentials for external applications.

### P9-02 Scope System

Implement permission scopes.

### P9-03 API Keys

Store only secure hashes.

### P9-04 MCP Server

Implement tools:

```text
predict_choice

rank_options

get_preference_summary

find_similar_decisions

record_decision

record_outcome
```

### P9-05 Audit

Every external request appears in local audit log.

### P9-06 Permission UI

Desktop shows:

```text
OpenClaw

Allowed:
✓ predict decisions
✓ read preference summary

Denied:
✗ raw memories
✗ modify preferences
```

## Exit Criteria

An external MCP-compatible agent can ask:

```text
"Which laptop is the owner most likely to prefer?"
```

and receive an answer without receiving the owner's complete personal database.

---

# PHASE 10 — Import, Backup & Portability

## Goal

Make the Personal Model portable and resilient.

## Tasks

### P10-01 Backup

One-click local backup.

### P10-02 Restore

Restore into fresh installation.

### P10-03 Encrypted Export

Portable encrypted archive.

### P10-04 Chat History Import

Start with:

```text
JSON
Markdown
plain text
```

Then support common assistant export formats.

### P10-05 Source Deletion

Deleting imported source removes derivative evidence and triggers model rebuild.

### P10-06 Model Migration

Handle version changes safely.

## Exit Criteria

User can:

```text
backup machine A

install Soulmate on machine B

restore backup

retain Personal Model and decision history
```

without a Soulmate cloud service.

---

# PHASE 11 — Connector Ecosystem

## Goal

Allow optional local integrations without polluting the Personalization Kernel.

Implement connector SDK.

Example plugins:

```text
calendar
notes
email
browser
GitHub
other local data
```

Every connector must output:

```text
RawEvent
```

and declare:

```text
data read
network access
credentials required
learning permission
```

Connectors should eventually be independently installable.

---

# PHASE 12 — Delegated Decision Agent

## Goal

Allow approved agents to make limited decisions on behalf of the owner.

This phase MUST occur only after predictions and confidence calibration are reliable.

Implement:

```text
Policy Engine

impact classification

confidence threshold

agent permissions

approval workflow
```

Example:

```text
Incoming meeting request
       ↓
Calendar agent asks Soulmate
       ↓
Prediction:
Decline 92%
       ↓
Policy:
low-impact + confidence > 90%
       ↓
Agent may respond automatically
```

Higher impact decisions require confirmation.

---

# 70. MVP Definition

The real MVP is complete after roughly Phases 0–5.

It MUST prove one hypothesis:

> Can a structured Personal Decision Model predict a user's choices better than a generic LLM supplied with normal conversation context?

Required MVP loop:

```text
talk
 ↓
learn
 ↓
submit choice
 ↓
predict
 ↓
resolve
 ↓
learn
 ↓
measure
```

If this loop does not outperform simple baselines, do not spend significant effort building autonomous-agent functionality.

---

# 71. First Public Alpha Definition

Recommended public alpha:

```text
Phases 0–7
```

Users can:

```text
install desktop app

run everything locally

use Ollama or their own API key

chat

teach the system about themselves

submit decisions

see predictions

correct the model

inspect evidence

access from phone on LAN
```

No centralized account required.

---

# 72. First Open-Agent Release

Recommended milestone:

```text
Phases 0–10
```

At this point Soulmate becomes useful as infrastructure for other agents.

External systems can ask:

```text
What would the owner want?
```

while the Personal Model stays local.

---

# 73. Coding Rules

Should follow these rules throughout implementation.

1. Do not add infrastructure without an active requirement.

2. Prefer standard-library/simple solutions over new services.

3. Core domain code must remain infrastructure-independent.

4. Every persistent schema change requires migration.

5. Every derived Personal Model field must be traceable to Evidence.

6. Every prediction must store model version.

7. Every important algorithm must be testable without an LLM.

8. All LLM structured output must be validated.

9. Provider-specific code belongs only in adapters.

10. Network communication must pass privacy/security boundaries.

11. Default configuration must remain local-only.

12. No telemetry without explicit opt-in.

13. New external integrations must not directly mutate the User Model.

14. Do not implement later phases prematurely.

15. Add tests before considering a phase complete.

---

# 74. Phase Execution Protocol

For each phase:

```text
1. Read this specification.

2. Inspect current repository state.

3. Produce implementation plan for only the current phase.

4. Implement smallest coherent increments.

5. Add/update tests.

6. Run:
   lint
   typecheck
   unit tests
   integration tests relevant to phase

7. Update architecture docs if behavior changed.

8. Update CHANGELOG / phase status.

9. Do not begin next phase automatically unless instructed.
```

---

# 75. Definition of Done for Every Feature

A feature is not complete unless:

```text
implementation exists

tests exist

error handling exists

data ownership implications considered

privacy implications considered

restart persistence tested where relevant

documentation updated

no unnecessary external dependency added
```

---

# 76. Long-Term Architecture Target

The final conceptual system should resemble:

```text
                       ┌────────────────┐
                       │      User      │
                       └───────┬────────┘
                               │
                 ┌─────────────┼─────────────┐
                 ▼             ▼             ▼
             Desktop         Phone          Web
                 │             │             │
                 └─────────────┼─────────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │ Personal Agent   │
                    └────────┬─────────┘
                             │
                             ▼
╔════════════════════════════════════════════════════╗
║             PERSONAL INTELLIGENCE                 ║
║                                                    ║
║ Identity                                           ║
║ Memory                                             ║
║ Preferences                                        ║
║ Goals                                              ║
║ Decision history                                   ║
║ Outcome history                                    ║
║ Decision model                                     ║
║ Uncertainty model                                  ║
║ Learning                                           ║
╚════════════════════════════════════════════════════╝
                             ▲
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
           OpenClaw        Claude         Other
           Hermes          Codex          Agents
              │              │              │
              └──────────────┼──────────────┘
                             │
                             ▼
                  Ask Soulmate:
                 "What would they want?"
```

Soulmate should therefore eventually become a **local, user-owned Personal Intelligence Layer** that any authorized AI system can consult.

The model of the human belongs to the human.

The agent is replaceable.

The LLM is replaceable.

The UI is replaceable.

The Personal Model is the core asset.

---

# 77. Immediate Implementation Order

Should begin ONLY with:

```text
PHASE 0
Repository & Architecture Foundation
```

Then:

```text
PHASE 1
Local Daemon & Persistence

PHASE 2
Evidence & Personal Model Foundation

PHASE 3
Conversation & Evidence Extraction

PHASE 4
Decision MVP

PHASE 5
Preference Learning & Evaluation
```

Do not start desktop/mobile/MCP work before the Personal Model and Decision MVP have a working testable loop.

The first major technical objective is NOT:

```text
"Build an AI agent."
```

It is:

```text
"Build a Personal Decision Model whose predictions
can be measured against the owner's actual decisions."
```

Everything else is built around that kernel.
