import {
  SoulmateClient,
  assertPinnedFingerprint,
  type DeviceConnection,
} from "@soulmate/sdk";

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

export class PinnedServiceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PinnedServiceError";
  }
}

function originOf(url: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") {
      throw new PinnedServiceError(
        "Soulmate only talks to its service over TLS.",
      );
    }
    return parsed.origin;
  } catch (caught) {
    if (caught instanceof PinnedServiceError) {
      throw caught;
    }
    throw new PinnedServiceError("The stored service address is not usable.");
  }
}

/**
 * Restrict every request to the paired service origin. Certificate trust itself
 * is pinned in the native network configuration generated from the fingerprint
 * that was stored during pairing; this guard keeps the app from ever sending a
 * credential or personal data anywhere else.
 */
export function pinnedFetch(
  serviceUrl: string,
  fetchImpl: FetchLike,
): FetchLike {
  const expected = originOf(serviceUrl);
  return (input, init) => {
    try {
      if (originOf(input) !== expected) {
        throw new PinnedServiceError(
          "Soulmate refused a request to an unpaired service.",
        );
      }
    } catch (caught) {
      return Promise.reject(
        caught instanceof Error
          ? caught
          : new PinnedServiceError(String(caught)),
      );
    }
    return fetchImpl(input, init);
  };
}

/** Build a client that can only reach the service this device paired with. */
export function createPinnedClient(
  connection: DeviceConnection,
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
): SoulmateClient {
  return new SoulmateClient({
    baseUrl: connection.serviceUrl,
    credential: connection.credential,
    fetch: pinnedFetch(connection.serviceUrl, fetchImpl),
  });
}

/**
 * Confirm the reachable service is still the one this device paired with before
 * any personal data is requested or displayed.
 */
export async function verifyPinnedService(
  client: SoulmateClient,
  connection: DeviceConnection,
): Promise<void> {
  const info = await client.systemInfo();
  if (info.installation_id !== connection.serviceId) {
    throw new PinnedServiceError(
      "This is a different Soulmate service. Pair again from your computer.",
    );
  }
}

/** Re-check the pinned fingerprint after the owner re-issues a certificate. */
export function verifyPinnedFingerprint(
  connection: DeviceConnection,
  observed: string,
): void {
  assertPinnedFingerprint(connection.fingerprint, observed);
}
