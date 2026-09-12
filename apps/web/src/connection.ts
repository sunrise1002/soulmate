import { SoulmateClient } from "@soulmate/sdk";

export const STORAGE_KEY = "soulmate.connection";

/** A device credential stored by a browser that is not on the owner's machine. */
export interface StoredConnection {
  serviceId: string;
  deviceId: string;
  deviceName: string;
  credential: string;
}

function isConnection(value: unknown): value is StoredConnection {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record["serviceId"] === "string" &&
    typeof record["deviceId"] === "string" &&
    typeof record["deviceName"] === "string" &&
    typeof record["credential"] === "string" &&
    record["credential"].length > 0
  );
}

/** Read the stored credential, discarding anything unusable. */
export function loadConnection(
  storage: Pick<Storage, "getItem">,
): StoredConnection | null {
  const raw = storage.getItem(STORAGE_KEY);
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

export function saveConnection(
  storage: Pick<Storage, "setItem">,
  connection: StoredConnection,
): void {
  storage.setItem(STORAGE_KEY, JSON.stringify(connection));
}

export function clearConnection(storage: Pick<Storage, "removeItem">): void {
  storage.removeItem(STORAGE_KEY);
}

/**
 * Build a client for the service that served this page. The daemon is the only
 * origin this client ever talks to, so a browser on the owner's machine needs
 * no credential while a browser on another device must present one.
 */
export function createClient(
  origin: string,
  credential?: string,
): SoulmateClient {
  return new SoulmateClient({ baseUrl: origin, credential });
}
