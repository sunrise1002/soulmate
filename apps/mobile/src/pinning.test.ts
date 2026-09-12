import { describe, expect, it, vi } from "vitest";

import type { DeviceConnection } from "@soulmate/sdk";

import {
  createPinnedClient,
  PinnedServiceError,
  pinnedFetch,
  verifyPinnedFingerprint,
  verifyPinnedService,
  type FetchLike,
} from "./pinning.ts";

const FINGERPRINT = `sha256:${"a".repeat(64)}`;

const connection: DeviceConnection = {
  serviceUrl: "https://192.168.1.20:7433",
  serviceId: "installation_1",
  fingerprint: FINGERPRINT,
  credential: "device_1.secret",
  deviceId: "device_1",
  deviceName: "Phone",
};

function respond(body: unknown): FetchLike {
  return () =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
}

describe("pinned transport", () => {
  it("allows requests to the paired service", async () => {
    // Given: a transport pinned to the paired service
    const inner = vi.fn<FetchLike>(respond({ status: "healthy" }));
    const guarded = pinnedFetch(connection.serviceUrl, inner);

    // When: the app calls that service
    await guarded("https://192.168.1.20:7433/v1/health");

    // Then: the request goes through unchanged
    expect(inner).toHaveBeenCalledOnce();
  });

  it.each([
    "https://192.168.1.21:7433/v1/health",
    "https://192.168.1.20:7434/v1/health",
    "https://attacker.test/v1/health",
  ])("refuses a request to %s", async (url) => {
    // Given: a transport pinned to the paired service
    const inner = vi.fn<FetchLike>(respond({}));
    const guarded = pinnedFetch(connection.serviceUrl, inner);

    // When/Then: no credential is ever sent to another origin
    await expect(guarded(url)).rejects.toBeInstanceOf(PinnedServiceError);
    expect(inner).not.toHaveBeenCalled();
  });

  it.each(["http://192.168.1.20:7433", "not-a-url", ""])(
    "refuses to pin the unusable address %s",
    (serviceUrl) => {
      // Given/When/Then: pinning requires an encrypted, parseable address
      expect(() => pinnedFetch(serviceUrl, respond({}))).toThrow(
        PinnedServiceError,
      );
    },
  );

  it("rejects a plaintext request even to the pinned host", async () => {
    // Given: a transport pinned to the paired service
    const guarded = pinnedFetch(connection.serviceUrl, respond({}));

    // When/Then: downgrading to plaintext is refused
    await expect(
      guarded("http://192.168.1.20:7433/v1/health"),
    ).rejects.toBeInstanceOf(PinnedServiceError);
  });

  it("sends the stored credential through the pinned client", async () => {
    // Given: a pinned client for a paired device
    const inner = vi.fn<FetchLike>(respond({ status: "healthy" }));
    const client = createPinnedClient(connection, inner);

    // When: it calls the service
    await client.health();

    // Then: the credential travels only to the pinned origin
    const headers = inner.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer device_1.secret");
  });
});

describe("pinned service identity", () => {
  it("accepts the service this device paired with", async () => {
    // Given: the paired service answering with its own identity
    const client = createPinnedClient(
      connection,
      respond({
        service: "soulmate-daemon",
        version: "0.1.0",
        installation_id: "installation_1",
        profile_id: "profile_default",
        privacy_mode: "strict_local",
      }),
    );

    // When/Then: verification passes
    await expect(
      verifyPinnedService(client, connection),
    ).resolves.toBeUndefined();
  });

  it("refuses a different service at the same address", async () => {
    // Given: another installation answering on the paired address
    const client = createPinnedClient(
      connection,
      respond({
        service: "soulmate-daemon",
        version: "0.1.0",
        installation_id: "installation_other",
        profile_id: "profile_default",
        privacy_mode: "strict_local",
      }),
    );

    // When/Then: the app stops before requesting personal data
    await expect(verifyPinnedService(client, connection)).rejects.toThrow(
      "different Soulmate service",
    );
  });

  it.each([
    [FINGERPRINT, false],
    [`sha256:${"b".repeat(64)}`, true],
  ])(
    "detects a changed certificate fingerprint %s",
    (observed, shouldThrow) => {
      // Given: a certificate observed during a later connection
      const check = () => {
        verifyPinnedFingerprint(connection, observed);
      };

      // When/Then: only the pinned fingerprint is accepted
      if (shouldThrow) {
        expect(check).toThrow("certificate changed");
      } else {
        expect(check).not.toThrow();
      }
    },
  );
});
