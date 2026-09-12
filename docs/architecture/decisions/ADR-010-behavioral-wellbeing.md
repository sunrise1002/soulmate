# ADR-010: Separate behavioral prediction from wellbeing advice

Status: Implemented in Phase 8.

## Context

Actual choices are strong evidence of what the owner tends to choose, but a choice
can later produce low satisfaction or regret. Feeding outcomes back into the same
preference weights would silently turn Predict Me into a normative model and make
its meaning ambiguous (specification sections 22, 26, and Phase 8).

## Decision

Keep Predict Me descriptive. Resolutions continue to produce preference Evidence
and update behavioral learning. Store owner-reported outcomes as separate,
provenance-linked observations. Advise Me uses a separately versioned deterministic
algorithm that combines the current behavioral prediction with similar historical
outcomes and matching goals or constraints. Advice records both the Personal Model
snapshot and the behavioral prediction it used.

Active-learning answers remain preference Evidence because they directly describe
the owner's trade-offs. Outcome notes and answers stay local and pass through the
existing authorization boundary.

## Consequences

The product can explicitly disagree with its own behavioral prediction without
corrupting that prediction's interpretation. Advice quality is limited when no
outcomes, goals, or constraints match the current options, and the response exposes
component scores and supporting outcome identifiers so that limitation is visible.
Future advice algorithms can change independently while stored predictions and
recommendations remain reproducible by version.
