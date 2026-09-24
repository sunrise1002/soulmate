/**
 * Decision I/O contracts (Phase 13, ADR-014).
 *
 * An adapter reports what it observed; the daemon assigns the actor trust,
 * evidence eligibility, and observation state returned here.
 */

export type AcquisitionMethod =
  | "owner_input"
  | "owner_import"
  | "connector_pull"
  | "agent_push"
  | "legacy_unverified";

export type ConsentMode =
  "owner_explicit" | "owner_implicit" | "legacy_unverified";

export type DataClass =
  | "metadata"
  | "decision"
  | "correction"
  | "outcome"
  | "prompt"
  | "response"
  | "file_content"
  | "diff";

export type AuthorScope = "owner_only" | "agent_only" | "mixed";

/** `delete_after_extraction` is not supported yet and is rejected by the daemon. */
export type RawRetentionPolicy =
  "metadata_only" | "structured_only" | "full_content";

export type EventActorType =
  "owner" | "agent" | "assistant" | "system" | "third_party" | "unknown";

export type EvidenceEligibility = "eligible" | "contextual_only" | "ignored";

export type ObservationStatus =
  "unmatched" | "pending" | "confirmed" | "rejected";

export type ObservationKind =
  "resolution" | "technical" | "user_behavior" | "owner_reported";

export type TechnicalOutcomeStatus =
  "succeeded" | "failed" | "partial" | "unknown";

export type UserDisposition =
  "accepted" | "modified" | "replaced" | "reverted" | "unknown";

export interface DecisionIoSourceInput {
  name: string;
  provider: string;
  service_identity_id: string;
  data_classes: DataClass[];
  author_scope?: AuthorScope;
  raw_retention_policy?: RawRetentionPolicy;
  adapter_version?: string | null;
  parser_version?: string | null;
}

export interface DecisionIoSource {
  id: string;
  name: string;
  source_type: string;
  provider: string | null;
  acquisition_method: AcquisitionMethod;
  consent_mode: ConsentMode;
  consent_at: string | null;
  data_classes: DataClass[];
  author_scope: AuthorScope;
  raw_retention_policy: RawRetentionPolicy;
  adapter_version: string | null;
  parser_version: string | null;
  policy_profile_version: string;
  service_identity_id: string | null;
  created_at: string;
  raw_event_count: number;
  decision_count: number;
  resolution_observation_count: number;
  outcome_observation_count: number;
  unmatched_observation_count: number;
}

export interface DecisionIoSourceRemoval {
  source_id: string;
  raw_event_count: number;
  decision_count: number;
  observation_count: number;
  evidence_count: number;
  model_rebuilt: boolean;
}

/** Fields every pushed event carries; `occurred_at` must include a UTC offset. */
export interface DecisionIoEnvelope {
  source_id: string;
  external_event_id: string;
  occurred_at: string;
  actor_type: EventActorType;
  content?: Record<string, unknown>;
  schema_version?: number;
  correlation_id?: string | null;
  causation_event_id?: string | null;
}

export interface DecisionIoInteractionInput extends DecisionIoEnvelope {
  event_type?: "interaction" | "action" | "context" | "agent_proposal";
}

export interface DecisionIoOptionInput {
  external_option_id: string;
  label: string;
  description: string;
  features: Record<string, number>;
}

export interface DecisionIoDecisionInput extends DecisionIoEnvelope {
  external_decision_id: string;
  domain: string;
  question: string;
  context?: Record<string, unknown>;
  options: DecisionIoOptionInput[];
}

export interface DecisionIoResolutionInput extends DecisionIoEnvelope {
  external_decision_id: string;
  external_option_id: string;
  disposition?: UserDisposition;
  event_type?: "decision_resolution" | "user_override";
}

/** Owner wellbeing cannot be reported here; it requires an owner confirmation. */
export interface DecisionIoOutcomeInput extends DecisionIoEnvelope {
  external_decision_id: string;
  kind: "technical" | "user_behavior";
  technical_status?: TechnicalOutcomeStatus | null;
  disposition?: UserDisposition | null;
}

export interface DecisionIoIngestion {
  event_id: string;
  duplicate: boolean;
  evidence_eligibility: EvidenceEligibility;
  actor_type: EventActorType;
  policy_profile_version: string;
  decision_id: string | null;
  observation_id: string | null;
  observation_status: ObservationStatus | null;
  promoted: boolean;
}

export interface DecisionIoObservation {
  id: string;
  kind: ObservationKind;
  source_id: string;
  source_event_id: string;
  actor_type: EventActorType;
  status: ObservationStatus;
  decision_id: string | null;
  external_decision_id: string | null;
  disposition: UserDisposition | null;
  technical_status: TechnicalOutcomeStatus | null;
  satisfaction: number | null;
  regret: boolean | null;
  reason_code: string | null;
  created_at: string;
  confirmed_at: string | null;
}

export interface OwnerOutcomeConfirmation {
  satisfaction: number;
  regret: boolean;
  notes?: string | null;
}

/** Response of the deprecated external `record-outcome` compatibility wrapper. */
export interface ExternalOutcomeObservation {
  id: string;
  decision_id: string;
  satisfaction: number;
  regret: boolean;
  created_at: string;
  status: ObservationStatus;
  kind: "owner_reported";
  requires_owner_confirmation: true;
}
