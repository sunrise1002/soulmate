import { invoke } from "@tauri-apps/api/core";

import type {
  ApiResponse,
  DesktopSettings,
  DesktopSettingsInput,
  ServiceStatus,
} from "./types.ts";

interface ErrorBody {
  detail?: string;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiRequest<T>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await invoke<ApiResponse<T | ErrorBody>>("api_request", {
    request: { method, path, body: body ?? null },
  });
  if (response.status < 200 || response.status >= 300) {
    const errorBody = response.body as ErrorBody;
    throw new ApiError(
      response.status,
      errorBody.detail ?? "The local service request failed.",
    );
  }
  return response.body as T;
}

export function getDesktopSettings(): Promise<DesktopSettings> {
  return invoke<DesktopSettings>("get_desktop_settings");
}

export function saveDesktopSettings(
  settings: DesktopSettingsInput,
): Promise<DesktopSettings> {
  return invoke<DesktopSettings>("save_desktop_settings", { settings });
}

export function getServiceStatus(): Promise<ServiceStatus> {
  return invoke<ServiceStatus>("daemon_status");
}

export function startService(): Promise<ServiceStatus> {
  return invoke<ServiceStatus>("daemon_start");
}

export function stopService(): Promise<ServiceStatus> {
  return invoke<ServiceStatus>("daemon_stop");
}

export function restartService(): Promise<ServiceStatus> {
  return invoke<ServiceStatus>("daemon_restart");
}

export function getServiceLogs(): Promise<string[]> {
  return invoke<string[]>("daemon_logs");
}
