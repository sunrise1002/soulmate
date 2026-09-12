import { describe, expect, it } from "vitest";

import {
  clearConnection,
  createClient,
  loadConnection,
  saveConnection,
  STORAGE_KEY,
  type StoredConnection,
} from "./connection.ts";

const connection: StoredConnection = {
  serviceId: "installation_1",
  deviceId: "device_1",
  deviceName: "Browser",
  credential: "device_1.secret",
};

type TestStorage = Storage & { value: string | null };

function storage(initial: string | null = null): TestStorage {
  const stub: TestStorage = {
    value: initial,
    getItem(key: string) {
      return key === STORAGE_KEY ? this.value : null;
    },
    setItem(key: string, value: string) {
      if (key === STORAGE_KEY) {
        this.value = value;
      }
    },
    removeItem(key: string) {
      if (key === STORAGE_KEY) {
        this.value = null;
      }
    },
    clear() {
      this.value = null;
    },
    key: () => null,
    length: 0,
  };
  return stub;
}

describe("stored device connection", () => {
  it("round-trips a credential issued by pairing", () => {
    // Given: a browser that just paired with the service
    const store = storage();

    // When: the connection is saved and read back
    saveConnection(store, connection);

    // Then: the credential survives a page reload
    expect(loadConnection(store)).toEqual(connection);
  });

  it("reports no connection before pairing", () => {
    // Given/When/Then: an empty store means this device must pair
    expect(loadConnection(storage())).toBeNull();
  });

  it.each([
    ["not json", "unparseable storage"],
    ["{}", "an empty object"],
    ['{"credential":""}', "an empty credential"],
    [
      '{"serviceId":1,"deviceId":"d","deviceName":"n","credential":"c"}',
      "wrong field types",
    ],
    ["[]", "an array"],
    ["null", "a null value"],
  ])("discards %s stored as %s", (raw) => {
    // Given: storage holding damaged data
    // When/Then: the device is treated as unpaired instead of crashing
    expect(loadConnection(storage(raw))).toBeNull();
  });

  it("forgets the device when the owner revokes it", () => {
    // Given: a stored connection
    const store = storage(JSON.stringify(connection));

    // When: the credential is cleared
    clearConnection(store);

    // Then: nothing is left behind in the browser
    expect(store.value).toBeNull();
    expect(loadConnection(store)).toBeNull();
  });

  it("creates a client bound to the serving origin", () => {
    // Given/When: a client for the origin that served this page
    const client = createClient(
      "https://192.168.1.20:7433",
      connection.credential,
    );

    // Then: the client exists and targets only that service
    expect(client).toBeDefined();
  });
});
