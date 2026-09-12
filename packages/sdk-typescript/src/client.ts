import type {
  ActiveQuestion,
  ActiveQuestionAnswer,
  ApiCredential,
  AuditEvent,
  ChatResponse,
  ChatImportResult,
  Conversation,
  Decision,
  DataArchive,
  DataSource,
  DecisionAdvice,
  DecisionHistoryItem,
  DecisionOptionInput,
  DecisionPrediction,
  DecisionOutcome,
  Evidence,
  ExternalDecision,
  ExternalDecisionInput,
  ExternalOutcome,
  ExternalPrediction,
  Health,
  ModelSummary,
  NetworkState,
  PairedDevice,
  PairingInvitation,
  PairingResult,
  Preference,
  PreferenceSummary,
  Resolution,
  Session,
  ServiceIdentity,
  SimilarDecision,
  SystemInfo,
  UncertaintySignal,
  IssuedApiCredential,
  IssuedServiceIdentity,
  ImportFormat,
  RestoreStaged,
  SourceDeletionResult,
} from "./types.ts";

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

export interface SoulmateClientOptions {
  /** Base service address, such as `https://192.168.1.20:7433`. */
  baseUrl: string;
  /** Device credential or external service API key; absent for local owner calls. */
  credential?: string | undefined;
  fetch?: FetchLike | undefined;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }

  /** True when the credential is missing, unknown, or revoked by the owner. */
  get requiresPairing(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

interface ErrorBody {
  detail?: unknown;
}

function detailOf(body: unknown, status: number): string {
  if (typeof body === "object" && body !== null) {
    const detail = (body as ErrorBody).detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }
  return `The service request failed with status ${String(status)}.`;
}

/** Typed client for the local Soulmate service used by web and mobile clients. */
export class SoulmateClient {
  private readonly baseUrl: string;
  private readonly credential: string | undefined;
  private readonly fetchImpl: FetchLike;

  constructor(options: SoulmateClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.credential = options.credential;
    this.fetchImpl = options.fetch ?? ((input, init) => fetch(input, init));
  }

  /** Return a client for the same service using a different credential. */
  withCredential(credential: string | undefined): SoulmateClient {
    return new SoulmateClient({
      baseUrl: this.baseUrl,
      credential,
      fetch: this.fetchImpl,
    });
  }

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    if (this.credential !== undefined && this.credential.length > 0) {
      headers.Authorization = `Bearer ${this.credential}`;
    }
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method,
      headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const text = await response.text();
    const parsed: unknown = text.length === 0 ? null : JSON.parse(text);
    if (!response.ok) {
      throw new ApiError(response.status, detailOf(parsed, response.status));
    }
    return parsed as T;
  }

  health(): Promise<Health> {
    return this.request<Health>("GET", "/v1/health");
  }

  systemInfo(): Promise<SystemInfo> {
    return this.request<SystemInfo>("GET", "/v1/system/info");
  }

  session(): Promise<Session> {
    return this.request<Session>("GET", "/v1/session");
  }

  modelSummary(): Promise<ModelSummary> {
    return this.request<ModelSummary>("GET", "/v1/model/summary");
  }

  preferences(): Promise<Preference[]> {
    return this.request<Preference[]>("GET", "/v1/preferences");
  }

  uncertainties(): Promise<UncertaintySignal[]> {
    return this.request<UncertaintySignal[]>("GET", "/v1/model/uncertainties");
  }

  activeQuestions(): Promise<ActiveQuestion[]> {
    return this.request<ActiveQuestion[]>("GET", "/v1/active-questions");
  }

  generateActiveQuestions(
    limit = 3,
    targetKey?: string,
  ): Promise<ActiveQuestion[]> {
    return this.request<ActiveQuestion[]>(
      "POST",
      "/v1/active-questions/generate",
      { limit, target_key: targetKey ?? null },
    );
  }

  answerActiveQuestion(
    questionId: string,
    choice: "a" | "b",
  ): Promise<ActiveQuestionAnswer> {
    return this.request<ActiveQuestionAnswer>(
      "POST",
      `/v1/active-questions/${encodeURIComponent(questionId)}/answer`,
      { choice },
    );
  }

  preferenceEvidence(key: string): Promise<Evidence[]> {
    return this.request<Evidence[]>(
      "GET",
      `/v1/preferences/${encodeURIComponent(key)}/evidence`,
    );
  }

  correctPreference(
    targetKey: string,
    value: number,
    context: Record<string, unknown> = {},
  ): Promise<{ evidence: Evidence; snapshot_version: number }> {
    return this.request("POST", "/v1/preferences/corrections", {
      target_key: targetKey,
      value,
      context,
    });
  }

  conversations(): Promise<Conversation[]> {
    return this.request<Conversation[]>("GET", "/v1/conversations");
  }

  chat(content: string, conversationId?: string): Promise<ChatResponse> {
    return this.request<ChatResponse>("POST", "/v1/chat", {
      content,
      conversation_id: conversationId ?? null,
    });
  }

  decisionHistory(): Promise<DecisionHistoryItem[]> {
    return this.request<DecisionHistoryItem[]>("GET", "/v1/decisions");
  }

  createDecision(
    domain: string,
    question: string,
    options: DecisionOptionInput[],
    context: Record<string, unknown> = {},
  ): Promise<Decision> {
    return this.request<Decision>("POST", "/v1/decisions", {
      domain,
      question,
      context,
      options: options.map((option) => ({
        label: option.label,
        description: option.description,
        features: option.features ?? {},
      })),
    });
  }

  predictDecision(decisionId: string): Promise<DecisionPrediction> {
    return this.request<DecisionPrediction>(
      "POST",
      `/v1/decisions/${encodeURIComponent(decisionId)}/predict`,
    );
  }

  adviseDecision(decisionId: string): Promise<DecisionAdvice> {
    return this.request<DecisionAdvice>(
      "POST",
      `/v1/decisions/${encodeURIComponent(decisionId)}/advise`,
    );
  }

  resolveDecision(
    decisionId: string,
    chosenOptionId: string,
  ): Promise<Resolution> {
    return this.request<Resolution>(
      "POST",
      `/v1/decisions/${encodeURIComponent(decisionId)}/resolve`,
      { chosen_option_id: chosenOptionId },
    );
  }

  recordOutcome(
    decisionId: string,
    satisfaction: number,
    regret: boolean,
    notes?: string,
  ): Promise<ExternalOutcome> {
    return this.request<ExternalOutcome>(
      "POST",
      `/v1/decisions/${encodeURIComponent(decisionId)}/outcome`,
      { satisfaction, regret, notes: notes ?? null },
    );
  }

  deleteOutcome(decisionId: string): Promise<{ removed_outcome_id: string }> {
    return this.request<{ removed_outcome_id: string }>(
      "DELETE",
      `/v1/decisions/${encodeURIComponent(decisionId)}/outcome`,
    );
  }

  startPairing(): Promise<PairingInvitation> {
    return this.request<PairingInvitation>("POST", "/v1/pairing/start");
  }

  completePairing(
    token: string,
    deviceName: string,
    platform: string,
  ): Promise<PairingResult> {
    return this.request<PairingResult>("POST", "/v1/pairing/complete", {
      token,
      device_name: deviceName,
      platform,
    });
  }

  devices(): Promise<PairedDevice[]> {
    return this.request<PairedDevice[]>("GET", "/v1/devices");
  }

  revokeDevice(deviceId: string): Promise<PairedDevice> {
    return this.request<PairedDevice>(
      "DELETE",
      `/v1/devices/${encodeURIComponent(deviceId)}`,
    );
  }

  networkState(): Promise<NetworkState> {
    return this.request<NetworkState>("GET", "/v1/network/state");
  }

  serviceIdentityScopes(): Promise<string[]> {
    return this.request<string[]>("GET", "/v1/service-identities/scopes");
  }

  serviceIdentities(): Promise<ServiceIdentity[]> {
    return this.request<ServiceIdentity[]>("GET", "/v1/service-identities");
  }

  createServiceIdentity(
    name: string,
    scopes: string[],
    description?: string,
  ): Promise<IssuedServiceIdentity> {
    return this.request<IssuedServiceIdentity>(
      "POST",
      "/v1/service-identities",
      { name, scopes, description: description ?? null },
    );
  }

  updateServiceIdentityScopes(
    identityId: string,
    scopes: string[],
  ): Promise<ServiceIdentity> {
    return this.request<ServiceIdentity>(
      "POST",
      `/v1/service-identities/${encodeURIComponent(identityId)}/scopes`,
      { scopes },
    );
  }

  issueApiCredential(identityId: string): Promise<IssuedApiCredential> {
    return this.request<IssuedApiCredential>(
      "POST",
      `/v1/service-identities/${encodeURIComponent(identityId)}/credentials`,
    );
  }

  revokeApiCredential(
    identityId: string,
    credentialId: string,
  ): Promise<ApiCredential> {
    return this.request<ApiCredential>(
      "DELETE",
      `/v1/service-identities/${encodeURIComponent(identityId)}/credentials/${encodeURIComponent(credentialId)}`,
    );
  }

  revokeServiceIdentity(identityId: string): Promise<ServiceIdentity> {
    return this.request<ServiceIdentity>(
      "DELETE",
      `/v1/service-identities/${encodeURIComponent(identityId)}`,
    );
  }

  auditEvents(limit = 100): Promise<AuditEvent[]> {
    return this.request<AuditEvent[]>(
      "GET",
      `/v1/audit/events?limit=${String(limit)}`,
    );
  }

  dataSources(): Promise<DataSource[]> {
    return this.request<DataSource[]>("GET", "/v1/data/sources");
  }

  importChatHistory(
    name: string,
    content: string,
    format: ImportFormat = "auto",
  ): Promise<ChatImportResult> {
    return this.request<ChatImportResult>("POST", "/v1/data/imports", {
      name,
      content,
      format,
    });
  }

  deleteDataSource(sourceId: string): Promise<SourceDeletionResult> {
    return this.request<SourceDeletionResult>(
      "DELETE",
      `/v1/data/sources/${encodeURIComponent(sourceId)}`,
    );
  }

  createBackup(): Promise<DataArchive> {
    return this.request<DataArchive>("POST", "/v1/data/backups");
  }

  createEncryptedExport(passphrase: string): Promise<DataArchive> {
    return this.request<DataArchive>("POST", "/v1/data/exports", {
      passphrase,
    });
  }

  stageRestore(
    archiveBase64: string,
    passphrase?: string,
  ): Promise<RestoreStaged> {
    return this.request<RestoreStaged>("POST", "/v1/data/restores", {
      archive_base64: archiveBase64,
      passphrase: passphrase ?? null,
    });
  }

  predictChoice(input: ExternalDecisionInput): Promise<ExternalPrediction> {
    return this.request<ExternalPrediction>(
      "POST",
      "/v1/external/predict-choice",
      input,
    );
  }

  rankOptions(input: ExternalDecisionInput): Promise<ExternalPrediction> {
    return this.request<ExternalPrediction>(
      "POST",
      "/v1/external/rank-options",
      input,
    );
  }

  preferenceSummary(): Promise<PreferenceSummary[]> {
    return this.request<PreferenceSummary[]>(
      "GET",
      "/v1/external/preference-summary",
    );
  }

  externalModelSummary(): Promise<ModelSummary> {
    return this.request<ModelSummary>("GET", "/v1/external/model-summary");
  }

  findSimilarDecisions(
    input: ExternalDecisionInput,
  ): Promise<SimilarDecision[]> {
    return this.request<SimilarDecision[]>(
      "POST",
      "/v1/external/find-similar-decisions",
      input,
    );
  }

  recordExternalDecision(
    input: ExternalDecisionInput,
  ): Promise<ExternalDecision> {
    return this.request<ExternalDecision>(
      "POST",
      "/v1/external/record-decision",
      input,
    );
  }

  recordExternalOutcome(
    decisionId: string,
    satisfaction: number,
    regret: boolean,
    notes?: string,
  ): Promise<DecisionOutcome> {
    return this.request<DecisionOutcome>(
      "POST",
      "/v1/external/record-outcome",
      {
        decision_id: decisionId,
        satisfaction,
        regret,
        notes: notes ?? null,
      },
    );
  }
}
