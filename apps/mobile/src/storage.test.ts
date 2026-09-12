import { describe, expect, it } from "vitest";

import type { DeviceConnection } from "@soulmate/sdk";

import {
  CONNECTION_KEY,
  clearConnection,
  loadConnection,
  saveConnection,
} from "./storage.ts";
import type { SecureStore } from "./storage.ts";

const connection: DeviceConnection = {
  serviceUrl: "https://192.168.1.20:7433",
  serviceId: "installation_1",
  fingerprint: `sha256:${"a".repeat(64)}`,
  credential: "device_1.secret",
  deviceId: "device_1",
  deviceName: "Phone",
};

function store(
  initial: string | null = null,
): SecureStore & { value: string | null } {
  const stub: SecureStore & { value: string | null } = {
    value: initial,
    getItemAsync: (key: string) =>
      Promise.resolve(key === CONNECTION_KEY ? stub.value : null),
    setItemAsync: (key: string, value: string) => {
      if (key === CONNECTION_KEY) {
        stub.value = value;
      }
      return Promise.resolve();
    },
    deleteItemAsync: (key: string) => {
      if (key === CONNECTION_KEY) {
        stub.value = null;
      }
      return Promise.resolve();
    },
  };
  return stub;
}

describe("secure connection storage", () => {
  it("round-trips a paired connection", async () => {
    // Given: a device that just paired
    const secure = store();

    // When: the connection is stored and read back
    await saveConnection(secure, connection);

    // Then: the credential survives an app restart
    await expect(loadConnection(secure)).resolves.toEqual(connection);
  });

  it("reports no connection before pairing", async () => {
    // Given/When/Then: an empty store means the device must pair
    await expect(loadConnection(store())).resolves.toBeNull();
  });

  it.each([
    ["not json"],
    ["{}"],
    ['{"serviceUrl":"https://a","serviceId":"b"}'],
    [
      '{"serviceUrl":"","serviceId":"b","fingerprint":"c","credential":"d","deviceId":"e","deviceName":"f"}',
    ],
    ["[]"],
  ])("discards the damaged stored value %s", async (raw) => {
    // Given: secure storage holding unusable data
    // When/Then: the device is treated as unpaired
    await expect(loadConnection(store(raw))).resolves.toBeNull();
  });

  it("forgets the device when the owner revokes it", async () => {
    // Given: a stored connection
    const secure = store(JSON.stringify(connection));

    // When: the connection is cleared
    await clearConnection(secure);

    // Then: no credential remains on the device
    expect(secure.value).toBeNull();
  });
});
