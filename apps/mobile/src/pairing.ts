import {
  SoulmateClient,
  connectionFrom,
  isPairingPayloadExpired,
  parsePairingPayload,
  PairingPayloadError,
  type DeviceConnection,
} from "@soulmate/sdk";

import { pinnedFetch, type FetchLike } from "./pinning.ts";

export interface PairingRequest {
  scanned: string;
  deviceName: string;
  platform: string;
  now: Date;
  fetchImpl?: FetchLike;
}

/**
 * Redeem a scanned pairing code and return the connection this device stores.
 * The invitation is validated before any network call so an expired or foreign
 * code never reaches the owner's machine.
 */
export async function pairWithScannedCode(
  request: PairingRequest,
): Promise<DeviceConnection> {
  const payload = parsePairingPayload(request.scanned);
  if (isPairingPayloadExpired(payload, request.now)) {
    throw new PairingPayloadError(
      "This pairing code expired. Create a new one on your computer.",
    );
  }
  const fetchImpl = request.fetchImpl ?? ((input, init) => fetch(input, init));
  const client = new SoulmateClient({
    baseUrl: payload.service_url,
    fetch: pinnedFetch(payload.service_url, fetchImpl),
  });
  const result = await client.completePairing(
    payload.token,
    request.deviceName,
    request.platform,
  );
  return connectionFrom(payload, result);
}
