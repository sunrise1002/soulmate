export type EvidenceTargetType = "fact" | "preference" | "goal" | "constraint";

export interface Evidence {
  id: string;
  target_type: EvidenceTargetType;
  target_key: string;
  value: unknown;
  strength: number;
  confidence: number;
  context: Record<string, unknown>;
  source_type: string;
  source_event_id: string;
  extractor_version: string;
  extractor_model: string | null;
  source_message_id: string | null;
  created_at: string;
}

export interface Preference {
  key: string;
  value: number;
  uncertainty: number;
  confidence: number;
  context: Record<string, unknown>;
  supporting_evidence_ids: string[];
  updated_at: string;
  model_version: number;
}

export interface ModelSummary {
  version: number | null;
  algorithm_version: string | null;
  evidence_revision: number;
  preference_count: number;
  fact_count: number;
  goal_count: number;
  constraint_count: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  provider_model: string | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
}

export interface ChatResponse {
  conversation_id: string;
  user_message_id: string;
  message: Message;
  accepted_evidence: Evidence[];
  rejected_evidence_count: number;
  snapshot_version: number | null;
}

export interface DecisionOption {
  id: string;
  label: string;
  description: string;
  features: Record<string, number>;
  feature_confidence: number;
}

export interface Decision {
  id: string;
  domain: string;
  question: string;
  context: Record<string, unknown>;
  status: "open" | "resolved";
  options: DecisionOption[];
  created_at: string;
}

export interface Ranking {
  option_id: string;
  label: string;
  probability: number;
  utility: number;
}

export interface DecisionPrediction {
  id: string;
  decision_id: string;
  mode: "predict_me";
  predicted_option_id: string;
  predicted_choice: string;
  ranking: Ranking[];
  confidence: number;
  important_factors: string[];
  uncertain_factors: string[];
  supporting_evidence: Evidence[];
  similar_decision_ids: string[];
  model_snapshot_version: number;
  algorithm_version: string;
  created_at: string;
}

export interface AdviceRanking {
  option_id: string;
  label: string;
  recommendation_score: number;
  behavioral_probability: number;
  wellbeing_score: number | null;
  goal_alignment: number | null;
}

export interface DecisionAdvice {
  id: string;
  decision_id: string;
  mode: "advise_me";
  predicted_option_id: string;
  predicted_choice: string;
  recommended_option_id: string;
  recommended_choice: string;
  ranking: AdviceRanking[];
  confidence: number;
  rationale: string[];
  supporting_outcome_ids: string[];
  model_snapshot_version: number;
  algorithm_version: string;
  created_at: string;
}

export interface Resolution {
  id: string;
  decision_id: string;
  chosen_option_id: string;
  created_at: string;
}

export interface DecisionOutcome {
  id: string;
  decision_id: string;
  satisfaction: number;
  regret: boolean;
  notes: string | null;
  created_at: string;
}

export interface DecisionHistoryItem {
  decision: Decision;
  prediction: DecisionPrediction | null;
  resolution: Resolution | null;
  advice: DecisionAdvice | null;
  outcome: DecisionOutcome | null;
}

export interface UncertaintySignal {
  preference_key: string;
  context: Record<string, unknown>;
  uncertainty: number;
  confidence: number;
  information_value: number;
}

export interface ActiveQuestion {
  id: string;
  prompt: string;
  preference_keys: string[];
  context: Record<string, unknown>;
  option_a_label: string;
  option_b_label: string;
  information_gain_score: number;
  model_snapshot_version: number;
  algorithm_version: string;
  status: "pending" | "answered";
  created_at: string;
}

export interface ActiveQuestionAnswer {
  question_id: string;
  choice: "a" | "b";
  learned_evidence: Evidence[];
  snapshot_version: number;
  created_at: string;
}

export interface Health {
  status: string;
  database: string;
  migration: string;
}

export interface SystemInfo {
  service: string;
  version: string;
  installation_id: string;
  profile_id: string;
  privacy_mode: "strict_local" | "hybrid" | "offline";
}

export interface Session {
  actor: "owner" | "device";
  device_id: string | null;
  device_name: string | null;
  service_id: string;
  profile_id: string;
}

export interface PairedDevice {
  id: string;
  name: string;
  platform: string;
  created_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
  active: boolean;
}

export interface PairingInvitation {
  token: string;
  expires_at: string;
  service_url: string;
  service_id: string;
  fingerprint: string;
  qr_payload: string;
}

export interface PairingResult {
  device_id: string;
  device_name: string;
  platform: string;
  credential: string;
  service_id: string;
  fingerprint: string;
  created_at: string;
}

export interface NetworkState {
  lan_enabled: boolean;
  lan_url: string | null;
  fingerprint: string | null;
  certificate_expires_at: string | null;
  paired_device_count: number;
  active_device_count: number;
  web_client_available: boolean;
  error: string | null;
}

export interface DecisionOptionInput {
  label: string;
  description: string;
  features?: Record<string, number>;
}
