import { describe, expect, it } from "vitest";

import {
  assertPinnedFingerprint,
  connectionFrom,
  encodePairingPayload,
  isPairingPayloadExpired,
  PAIRING_URI_SCHEME,
  PairingPayloadError,
  parsePairingPayload,
  type PairingPayload,
} from "./pairing.ts";
import type { PairingResult } from "./types.ts";

const FINGERPRINT = `sha256:${"a".repeat(64)}`;

const payload: PairingPayload = {
  v: 1,
  service_url: "https://192.168.1.20:7433",
  service_id: "installation_1",
  fingerprint: FINGERPRINT,
  token: "pairing-token-value",
  expires_at: "2026-09-12T08:05:00+00:00",
};

const result: PairingResult = {
  device_id: "device_1",
  device_name: "Phone",
  platform: "ios",
  credential: "device_1.secret",
  service_id: "installation_1",
  fingerprint: FINGERPRINT,
  created_at: "2026-09-12T08:01:00+00:00",
};

function encodeWith(
  overrides: Partial<Record<keyof PairingPayload, unknown>>,
): string {
  return encodePairingPayload({ ...payload, ...overrides } as PairingPayload);
}

describe("pairing payloads", () => {
  it("round-trips an invitation produced by the daemon", () => {
    // Given: an invitation encoded as QR data
    const scanned = encodePairingPayload(payload);

    // When: a phone scans and parses it
    const parsed = parsePairingPayload(scanned);

    // Then: every pinned field survives the round trip
    expect(scanned.startsWith(PAIRING_URI_SCHEME)).toBe(true);
    expect(parsed).toEqual(payload);
  });

  it("ignores surrounding whitespace from a scanner", () => {
    // Given: scanner output with trailing whitespace
    const scanned = `  ${encodePairingPayload(payload)}\n`;

    // When/Then: the invitation still parses
    expect(parsePairingPayload(scanned).token).toBe(payload.token);
  });

  it.each([
    ["", "not a Soulmate pairing code"],
    ["https://example.test", "not a Soulmate pairing code"],
    [`${PAIRING_URI_SCHEME}not-base64!!`, "damaged or incomplete"],
    [`${PAIRING_URI_SCHEME}${btoa("[]")}`, "damaged or incomplete"],
    [`${PAIRING_URI_SCHEME}${btoa("null")}`, "damaged or incomplete"],
  ])("rejects unusable scanner input %s", (scanned, message) => {
    // Given: scanner output that is not a valid invitation
    // When/Then: parsing fails with a user-readable reason
    expect(() => parsePairingPayload(scanned)).toThrow(message);
  });

  it("rejects a payload from an unsupported version", () => {
    // Given: an invitation from a future client
    const scanned = encodeWith({ v: 2 });

    // When/Then: the phone refuses it instead of guessing
    expect(() => parsePairingPayload(scanned)).toThrow("another version");
  });

  it.each(["service_url", "service_id", "fingerprint", "token", "expires_at"])(
    "rejects a payload without %s",
    (key) => {
      // Given: an invitation missing a required field
      const scanned = encodeWith({ [key]: "" });

      // When/Then: the missing field is named
      expect(() => parsePairingPayload(scanned)).toThrow(key);
    },
  );

  it("refuses a plaintext service address", () => {
    // Given: an invitation pointing at an unencrypted address
    const scanned = encodeWith({ service_url: "http://192.168.1.20:7433" });

    // When/Then: pairing requires TLS
    expect(() => parsePairingPayload(scanned)).toThrow(
      "encrypted service address",
    );
  });

  it.each([
    "sha256:short",
    "md5:" + "a".repeat(64),
    "a".repeat(64),
    `sha256:${"A".repeat(64)}`,
  ])("refuses the malformed fingerprint %s", (fingerprint) => {
    // Given: an invitation with an unusable fingerprint
    const scanned = encodeWith({ fingerprint });

    // When/Then: nothing can be pinned, so pairing stops
    expect(() => parsePairingPayload(scanned)).toThrow(
      "valid service fingerprint",
    );
  });

  it.each([
    ["2026-09-12T08:04:59+00:00", false],
    ["2026-09-12T08:05:00+00:00", true],
    ["2026-09-12T08:05:01+00:00", true],
  ])("treats %s as expired=%s at the lifetime boundary", (now, expected) => {
    // Given: an invitation that expires at a known instant
    // When/Then: expiry is inclusive of the expiry timestamp
    expect(isPairingPayloadExpired(payload, new Date(now))).toBe(expected);
  });

  it("treats an unparseable expiry as expired", () => {
    // Given: an invitation with a damaged timestamp
    const damaged = { ...payload, expires_at: "not-a-date" };

    // When/Then: the phone refuses to use it
    expect(
      isPairingPayloadExpired(damaged, new Date("2026-09-12T08:00:00Z")),
    ).toBe(true);
  });
});

describe("certificate pinning", () => {
  it("accepts the fingerprint that was pinned during pairing", () => {
    // Given/When/Then: an unchanged certificate passes
    expect(() => {
      assertPinnedFingerprint(FINGERPRINT, FINGERPRINT);
    }).not.toThrow();
  });

  it("rejects a service whose certificate changed", () => {
    // Given: a service presenting a different certificate
    // When/Then: the phone refuses to talk to it
    expect(() => {
      assertPinnedFingerprint(FINGERPRINT, `sha256:${"b".repeat(64)}`);
    }).toThrow(PairingPayloadError);
  });

  it("stores the pinned connection after a successful pairing", () => {
    // Given: a scanned invitation and the daemon's pairing result
    // When: they are combined
    const connection = connectionFrom(payload, result);

    // Then: the credential is stored together with the pinned identity
    expect(connection).toEqual({
      serviceUrl: payload.service_url,
      serviceId: "installation_1",
      fingerprint: FINGERPRINT,
      credential: "device_1.secret",
      deviceId: "device_1",
      deviceName: "Phone",
    });
  });

  it("refuses a pairing result from a different service", () => {
    // Given: a result whose service identity does not match the QR code
    const other = { ...result, service_id: "installation_other" };

    // When/Then: the connection is not stored
    expect(() => connectionFrom(payload, other)).toThrow(
      "service identity changed",
    );
  });

  it("refuses a pairing result with a different fingerprint", () => {
    // Given: a result presenting another certificate
    const other = { ...result, fingerprint: `sha256:${"c".repeat(64)}` };

    // When/Then: the connection is not stored
    expect(() => connectionFrom(payload, other)).toThrow("certificate changed");
  });
});
