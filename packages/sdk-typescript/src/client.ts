import type {
  ChatResponse,
  Conversation,
  Decision,
  DecisionHistoryItem,
  DecisionOptionInput,
  DecisionPrediction,
  Evidence,
  Health,
  ModelSummary,
  NetworkState,
  PairedDevice,
  PairingInvitation,
  PairingResult,
  Preference,
  Resolution,
  Session,
  SystemInfo,
} from "./types.ts";

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

export interface SoulmateClientOptions {
  /** Base service address, such as `https://192.168.1.20:7433`. */
  baseUrl: string;
  /** Device credential issued by pairing; absent on the owner's own machine. */
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
}
