export type PrivacyMode = "strict_local" | "hybrid" | "offline";
export type ProviderKind = "ollama" | "openai_compatible";

export interface DesktopSettings {
  privacyMode: PrivacyMode;
  provider: ProviderKind;
  ollamaBaseUrl: string;
  ollamaModel: string;
  openaiBaseUrl: string;
  openaiModel: string;
  hasApiKey: boolean;
}

export interface DesktopSettingsInput extends Omit<
  DesktopSettings,
  "hasApiKey"
> {
  apiKey?: string;
  clearApiKey: boolean;
}

export interface ServiceStatus {
  state: "starting" | "running" | "stopped" | "failed";
  pid: number | null;
  message: string;
}

export interface ApiResponse<T> {
  status: number;
  body: T;
}

export interface Health {
  status: string;
  database: string;
  migration: string;
}

export interface Evidence {
  id: string;
  target_type: "fact" | "preference" | "goal" | "constraint";
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

export interface Resolution {
  id: string;
  decision_id: string;
  chosen_option_id: string;
  created_at: string;
}

export interface DecisionHistoryItem {
  decision: Decision;
  prediction: DecisionPrediction | null;
  resolution: Resolution | null;
}
