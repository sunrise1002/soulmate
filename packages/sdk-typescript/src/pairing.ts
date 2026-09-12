import type { PairingResult } from "./types.ts";

export const PAIRING_URI_SCHEME = "soulmate://pair?data=";
export const PAIRING_PAYLOAD_VERSION = 1;
const FINGERPRINT_PATTERN = /^sha256:[0-9a-f]{64}$/;

/** Everything a phone reads from a pairing QR code before it trusts a service. */
export interface PairingPayload {
  v: number;
  service_url: string;
  service_id: string;
  fingerprint: string;
  token: string;
  expires_at: string;
}

/** A credential plus the service identity the device pinned when pairing. */
export interface DeviceConnection {
  serviceUrl: string;
  serviceId: string;
  fingerprint: string;
  credential: string;
  deviceId: string;
  deviceName: string;
}

export class PairingPayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PairingPayloadError";
  }
}

function decodeBase64Url(value: string): string {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(
    padded.padEnd(padded.length + ((4 - (padded.length % 4)) % 4), "="),
  );
  return new TextDecoder().decode(
    Uint8Array.from(binary, (character) => character.charCodeAt(0)),
  );
}

function encodeBase64Url(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function requireString(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new PairingPayloadError(`Pairing payload is missing ${key}.`);
  }
  return value;
}

/** Encode an invitation the same way the daemon renders its QR code. */
export function encodePairingPayload(payload: PairingPayload): string {
  return `${PAIRING_URI_SCHEME}${encodeBase64Url(JSON.stringify(payload))}`;
}

/**
 * Parse scanned QR data, rejecting anything that is not a supported, complete
 * invitation to a service reachable over TLS.
 */
export function parsePairingPayload(scanned: string): PairingPayload {
  const trimmed = scanned.trim();
  if (!trimmed.startsWith(PAIRING_URI_SCHEME)) {
    throw new PairingPayloadError("This code is not a Soulmate pairing code.");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(
      decodeBase64Url(trimmed.slice(PAIRING_URI_SCHEME.length)),
    );
  } catch {
    throw new PairingPayloadError(
      "This pairing code is damaged or incomplete.",
    );
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new PairingPayloadError(
      "This pairing code is damaged or incomplete.",
    );
  }
  const source = parsed as Record<string, unknown>;
  if (source["v"] !== PAIRING_PAYLOAD_VERSION) {
    throw new PairingPayloadError(
      "This pairing code was made by another version.",
    );
  }
  const payload: PairingPayload = {
    v: PAIRING_PAYLOAD_VERSION,
    service_url: requireString(source, "service_url"),
    service_id: requireString(source, "service_id"),
    fingerprint: requireString(source, "fingerprint"),
    token: requireString(source, "token"),
    expires_at: requireString(source, "expires_at"),
  };
  if (!payload.service_url.startsWith("https://")) {
    throw new PairingPayloadError(
      "Pairing requires an encrypted service address.",
    );
  }
  if (!FINGERPRINT_PATTERN.test(payload.fingerprint)) {
    throw new PairingPayloadError(
      "Pairing requires a valid service fingerprint.",
    );
  }
  return payload;
}

/** Report whether an invitation can still be redeemed at the given moment. */
export function isPairingPayloadExpired(
  payload: PairingPayload,
  now: Date,
): boolean {
  const expiry = Date.parse(payload.expires_at);
  return Number.isNaN(expiry) || expiry <= now.getTime();
}

/** Reject a service whose certificate no longer matches the pinned fingerprint. */
export function assertPinnedFingerprint(
  expected: string,
  observed: string,
): void {
  if (expected !== observed) {
    throw new PairingPayloadError(
      "The service certificate changed. Pair again from the owner's machine.",
    );
  }
}

/** Combine a scanned invitation and a pairing result into a stored connection. */
export function connectionFrom(
  payload: PairingPayload,
  result: PairingResult,
): DeviceConnection {
  assertPinnedFingerprint(payload.fingerprint, result.fingerprint);
  if (payload.service_id !== result.service_id) {
    throw new PairingPayloadError(
      "The service identity changed during pairing.",
    );
  }
  return {
    serviceUrl: payload.service_url,
    serviceId: result.service_id,
    fingerprint: result.fingerprint,
    credential: result.credential,
    deviceId: result.device_id,
    deviceName: result.device_name,
  };
}
