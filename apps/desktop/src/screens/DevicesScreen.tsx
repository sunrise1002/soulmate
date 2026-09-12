import { RefreshCw, ShieldCheck, Smartphone, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "../components/EmptyState.tsx";
import {
  apiRequest,
  getDesktopSettings,
  restartService,
  saveDesktopSettings,
} from "../runtime.ts";
import type {
  DesktopSettings,
  NetworkState,
  PairedDevice,
  PairingInvitation,
} from "../types.ts";
import { formatDate } from "../utils.ts";

interface DevicesScreenProps {
  onServiceChanged: () => Promise<void>;
}

export function DevicesScreen({ onServiceChanged }: DevicesScreenProps) {
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [network, setNetwork] = useState<NetworkState | null>(null);
  const [devices, setDevices] = useState<PairedDevice[]>([]);
  const [invitation, setInvitation] = useState<PairingInvitation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSettings(await getDesktopSettings());
      setNetwork(await apiRequest<NetworkState>("GET", "/v1/network/state"));
      setDevices(await apiRequest<PairedDevice[]>("GET", "/v1/devices"));
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Device access is unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load]);

  async function toggleLan(enabled: boolean) {
    if (settings === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      await saveDesktopSettings({
        privacyMode: settings.privacyMode,
        provider: settings.provider,
        ollamaBaseUrl: settings.ollamaBaseUrl,
        ollamaModel: settings.ollamaModel,
        openaiBaseUrl: settings.openaiBaseUrl,
        openaiModel: settings.openaiModel,
        lanEnabled: enabled,
        clearApiKey: false,
      });
      await restartService();
      await onServiceChanged();
      setInvitation(null);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The access setting could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function createInvitation() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setInvitation(
        await apiRequest<PairingInvitation>("POST", "/v1/pairing/start"),
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "A pairing code could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revoke(deviceId: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await apiRequest<PairedDevice>("DELETE", `/v1/devices/${deviceId}`);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The device could not be revoked.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen devices-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">Your devices</p>
          <h1>Devices</h1>
          <p>
            Your Personal Model stays on this computer. Other devices reach it
            over your own network, and you can revoke any of them here.
          </p>
        </div>
        <button
          className="secondary-button"
          type="button"
          disabled={busy}
          onClick={() => void load()}
        >
          <RefreshCw size={15} strokeWidth={1.8} />
          Refresh
        </button>
      </header>

      {error ? <div className="inline-error">{error}</div> : null}

      <div className="card device-card">
        <label className="device-toggle">
          <input
            type="checkbox"
            checked={settings?.lanEnabled ?? false}
            disabled={busy || settings === null}
            onChange={(event) => void toggleLan(event.target.checked)}
          />
          <span>Enable access from other devices</span>
        </label>
        <p className="muted">
          This restarts the local service and adds an encrypted listener on your
          local network. Turning it off removes that listener.
        </p>
        {network?.lan_enabled ? (
          <dl className="device-facts">
            <div>
              <dt>Address</dt>
              <dd>{network.lan_url}</dd>
            </div>
            <div>
              <dt>Certificate fingerprint</dt>
              <dd className="device-fingerprint">{network.fingerprint}</dd>
            </div>
            <div>
              <dt>Paired devices</dt>
              <dd>
                {network.active_device_count} active of{" "}
                {network.paired_device_count}
              </dd>
            </div>
          </dl>
        ) : null}
        {network?.error != null ? (
          <p className="muted">{network.error}</p>
        ) : null}
      </div>

      <div className="card device-card">
        <p className="section-label">Pair a device</p>
        <button
          className="primary-button"
          type="button"
          disabled={busy || network?.lan_enabled !== true}
          onClick={() => void createInvitation()}
        >
          <ShieldCheck size={15} strokeWidth={1.8} />
          Create pairing code
        </button>
        {invitation !== null ? (
          <div className="device-invitation">
            <p className="muted">
              Scan this with the Soulmate app, or type the code into the web
              client. It works once and expires at{" "}
              {formatDate(invitation.expires_at)}.
            </p>
            <code className="device-payload">{invitation.qr_payload}</code>
            <p className="muted">Pairing code: {invitation.token}</p>
          </div>
        ) : null}
      </div>

      {devices.length ? (
        <ul className="device-list">
          {devices.map((device) => (
            <li className="card device-row" key={device.id}>
              <div>
                <strong>{device.name}</strong>
                <p className="muted">
                  {device.platform} · paired {formatDate(device.created_at)}
                  {device.active ? "" : " · revoked"}
                </p>
              </div>
              {device.active ? (
                <button
                  className="secondary-button"
                  type="button"
                  disabled={busy}
                  onClick={() => void revoke(device.id)}
                >
                  <Trash2 size={15} strokeWidth={1.8} />
                  Revoke
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={Smartphone}
          title="No devices are paired"
          description="Create a pairing code to connect your phone or another browser."
        />
      )}
    </section>
  );
}
