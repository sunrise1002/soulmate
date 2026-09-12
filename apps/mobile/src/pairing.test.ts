import { describe, expect, it, vi } from "vitest";

import { encodePairingPayload, type PairingPayload } from "@soulmate/sdk";

import { pairWithScannedCode } from "./pairing.ts";
import type { FetchLike } from "./pinning.ts";

const FINGERPRINT = `sha256:${"a".repeat(64)}`;
const NOW = new Date("2026-09-12T08:00:00Z");

const payload: PairingPayload = {
  v: 1,
  service_url: "https://192.168.1.20:7433",
  service_id: "installation_1",
  fingerprint: FINGERPRINT,
  token: "pairing-token-value",
  expires_at: "2026-09-12T08:05:00+00:00",
};

function daemon(body: unknown, status = 201): FetchLike {
  return () =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
}

const result = {
  device_id: "device_1",
  device_name: "Phone",
  platform: "ios",
  credential: "device_1.secret",
  service_id: "installation_1",
  fingerprint: FINGERPRINT,
  created_at: "2026-09-12T08:01:00+00:00",
};

describe("pairing from a scanned code", () => {
  it("stores a pinned connection after the daemon accepts the code", async () => {
    // Given: a freshly scanned pairing code
    const scanned = encodePairingPayload(payload);

    // When: the phone redeems it
    const connection = await pairWithScannedCode({
      scanned,
      deviceName: "Phone",
      platform: "ios",
      now: NOW,
      fetchImpl: daemon(result),
    });

    // Then: the credential is stored together with the pinned identity
    expect(connection.credential).toBe("device_1.secret");
    expect(connection.fingerprint).toBe(FINGERPRINT);
    expect(connection.serviceUrl).toBe(payload.service_url);
  });

  it("sends the scanned token to the pairing endpoint of the pinned service", async () => {
    // Given: a scanned pairing code
    const fetchImpl = vi.fn<FetchLike>(daemon(result));

    // When: the phone redeems it
    await pairWithScannedCode({
      scanned: encodePairingPayload(payload),
      deviceName: "Phone",
      platform: "ios",
      now: NOW,
      fetchImpl,
    });

    // Then: only the pinned service receives the token
    expect(fetchImpl.mock.calls[0]?.[0]).toBe(
      "https://192.168.1.20:7433/v1/pairing/complete",
    );
    expect(fetchImpl.mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({
        token: payload.token,
        device_name: "Phone",
        platform: "ios",
      }),
    );
  });

  it("refuses an expired code before contacting the service", async () => {
    // Given: a code that expired while the owner was away
    const fetchImpl = vi.fn<FetchLike>(daemon(result));

    // When/Then: nothing is sent and the user is told to retry
    await expect(
      pairWithScannedCode({
        scanned: encodePairingPayload(payload),
        deviceName: "Phone",
        platform: "ios",
        now: new Date("2026-09-12T08:06:00Z"),
        fetchImpl,
      }),
    ).rejects.toThrow("expired");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a code that is not a Soulmate invitation", async () => {
    // Given: an unrelated QR code
    const fetchImpl = vi.fn<FetchLike>(daemon(result));

    // When/Then: scanning a random code does nothing
    await expect(
      pairWithScannedCode({
        scanned: "https://example.test/promo",
        deviceName: "Phone",
        platform: "ios",
        now: NOW,
        fetchImpl,
      }),
    ).rejects.toThrow("not a Soulmate pairing code");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("surfaces a rejected or already used token", async () => {
    // Given: a daemon that refuses the token
    const fetchImpl = daemon(
      { detail: "Pairing token was already used." },
      401,
    );

    // When/Then: the phone reports why pairing failed
    await expect(
      pairWithScannedCode({
        scanned: encodePairingPayload(payload),
        deviceName: "Phone",
        platform: "ios",
        now: NOW,
        fetchImpl,
      }),
    ).rejects.toThrow("already used");
  });

  it("refuses a result whose fingerprint differs from the scanned code", async () => {
    // Given: a service answering with another certificate
    const fetchImpl = daemon({
      ...result,
      fingerprint: `sha256:${"b".repeat(64)}`,
    });

    // When/Then: the connection is not stored
    await expect(
      pairWithScannedCode({
        scanned: encodePairingPayload(payload),
        deviceName: "Phone",
        platform: "ios",
        now: NOW,
        fetchImpl,
      }),
    ).rejects.toThrow("certificate changed");
  });
});
