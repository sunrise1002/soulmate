import type { DeviceConnection } from "@soulmate/sdk";

export const CONNECTION_KEY = "soulmate.connection";

/** The subset of expo-secure-store this client depends on. */
export interface SecureStore {
  getItemAsync: (key: string) => Promise<string | null>;
  setItemAsync: (key: string, value: string) => Promise<void>;
  deleteItemAsync: (key: string) => Promise<void>;
}

function isConnection(value: unknown): value is DeviceConnection {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  const required = [
    "serviceUrl",
    "serviceId",
    "fingerprint",
    "credential",
    "deviceId",
    "deviceName",
  ];
  return required.every((key) => {
    const field = record[key];
    return typeof field === "string" && field.length > 0;
  });
}

/** Read the paired connection, treating damaged data as "not paired". */
export async function loadConnection(
  store: SecureStore,
): Promise<DeviceConnection | null> {
  const raw = await store.getItemAsync(CONNECTION_KEY);
  if (raw === null) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return isConnection(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function saveConnection(
  store: SecureStore,
  connection: DeviceConnection,
): Promise<void> {
  await store.setItemAsync(CONNECTION_KEY, JSON.stringify(connection));
}

export async function clearConnection(store: SecureStore): Promise<void> {
  await store.deleteItemAsync(CONNECTION_KEY);
}
