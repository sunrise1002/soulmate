import { useState } from "react";
import { ApiError, type SoulmateClient } from "@soulmate/sdk";

import type { StoredConnection } from "../connection.ts";

interface Props {
  client: SoulmateClient;
  onConnected: (connection: StoredConnection) => void;
}

const DEFAULT_NAME = "Browser";

export function ConnectScreen({ client, onConnected }: Props) {
  const [token, setToken] = useState("");
  const [deviceName, setDeviceName] = useState(DEFAULT_NAME);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async () => {
    setPending(true);
    setError(null);
    try {
      const result = await client.completePairing(
        token.trim(),
        deviceName.trim(),
        "web",
      );
      onConnected({
        serviceId: result.service_id,
        deviceId: result.device_id,
        deviceName: result.device_name,
        credential: result.credential,
      });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "The service could not be reached from this device.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="panel">
      <h2>Connect this device</h2>
      <p className="hint">
        Open Soulmate on the computer that holds your Personal Model, choose{" "}
        <strong>Enable access from other devices</strong>, and enter the pairing
        code shown there. Your data never leaves that computer.
      </p>
      <label htmlFor="device-name">Device name</label>
      <input
        id="device-name"
        value={deviceName}
        maxLength={100}
        onChange={(event) => setDeviceName(event.target.value)}
      />
      <label htmlFor="pairing-token">Pairing code</label>
      <input
        id="pairing-token"
        value={token}
        autoComplete="off"
        onChange={(event) => setToken(event.target.value)}
      />
      <button
        type="button"
        disabled={
          pending || token.trim().length === 0 || deviceName.trim().length === 0
        }
        onClick={() => void submit()}
      >
        {pending ? "Connecting…" : "Connect"}
      </button>
      {error !== null && <p role="alert">{error}</p>}
    </section>
  );
}
