import {
  CircleStop,
  CloudUpload,
  KeyRound,
  Play,
  RefreshCw,
  Save,
  Shield,
  TerminalSquare,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import {
  getDesktopSettings,
  getRemoteBackupSettings,
  getServiceLogs,
  restartService,
  saveDesktopSettings,
  saveRemoteBackupSettings,
  startService,
  stopService,
} from "../runtime.ts";
import type {
  DesktopSettings,
  PrivacyMode,
  ProviderKind,
  RemoteBackupDesktopSettings,
  ServiceStatus,
} from "../types.ts";

interface SettingsScreenProps {
  serviceStatus: ServiceStatus;
  onServiceChanged: () => Promise<void>;
}

const defaultSettings: DesktopSettings = {
  privacyMode: "strict_local",
  provider: "ollama",
  ollamaBaseUrl: "http://127.0.0.1:11434",
  ollamaModel: "",
  openaiBaseUrl: "http://127.0.0.1:8000/v1",
  openaiModel: "",
  hasApiKey: false,
  lanEnabled: false,
};

const defaultRemoteBackupSettings: RemoteBackupDesktopSettings = {
  enabled: false,
  automaticDaily: false,
  intervalHours: 24,
  endpointUrl: "",
  region: "auto",
  bucket: "",
  prefix: "soulmate",
  hasPassphrase: false,
  hasAccessKeyId: false,
  hasSecretAccessKey: false,
};

export function SettingsScreen({
  serviceStatus,
  onServiceChanged,
}: SettingsScreenProps) {
  const [settings, setSettings] = useState(defaultSettings);
  const [remoteBackup, setRemoteBackup] = useState(defaultRemoteBackupSettings);
  const [apiKey, setApiKey] = useState("");
  const [clearApiKey, setClearApiKey] = useState(false);
  const [backupPassphrase, setBackupPassphrase] = useState("");
  const [backupAccessKeyId, setBackupAccessKeyId] = useState("");
  const [backupSecretAccessKey, setBackupSecretAccessKey] = useState("");
  const [clearBackupCredentials, setClearBackupCredentials] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [configuration, backupConfiguration, output] = await Promise.all([
        getDesktopSettings(),
        getRemoteBackupSettings(),
        getServiceLogs(),
      ]);
      setSettings(configuration);
      setRemoteBackup(backupConfiguration);
      setLogs(output);
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Desktop settings are unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load]);

  async function save(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await saveDesktopSettings({
        privacyMode: settings.privacyMode,
        provider: settings.provider,
        ollamaBaseUrl: settings.ollamaBaseUrl,
        ollamaModel: settings.ollamaModel,
        openaiBaseUrl: settings.openaiBaseUrl,
        openaiModel: settings.openaiModel,
        lanEnabled: settings.lanEnabled,
        ...(apiKey ? { apiKey } : {}),
        clearApiKey,
      });
      setSettings(saved);
      setApiKey("");
      setClearApiKey(false);
      await restartService();
      await onServiceChanged();
      setNotice(
        "Settings saved. The local service restarted with the new privacy boundary.",
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Settings could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function saveBackup(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await saveRemoteBackupSettings({
        enabled: remoteBackup.enabled,
        automaticDaily: remoteBackup.automaticDaily,
        intervalHours: remoteBackup.intervalHours,
        endpointUrl: remoteBackup.endpointUrl,
        region: remoteBackup.region,
        bucket: remoteBackup.bucket,
        prefix: remoteBackup.prefix,
        ...(backupPassphrase ? { passphrase: backupPassphrase } : {}),
        ...(backupAccessKeyId ? { accessKeyId: backupAccessKeyId } : {}),
        ...(backupSecretAccessKey
          ? { secretAccessKey: backupSecretAccessKey }
          : {}),
        clearCredentials: clearBackupCredentials,
      });
      setRemoteBackup(saved);
      setBackupPassphrase("");
      setBackupAccessKeyId("");
      setBackupSecretAccessKey("");
      setClearBackupCredentials(false);
      await restartService();
      await onServiceChanged();
      setNotice(
        saved.enabled
          ? "Encrypted remote backup is configured. The local service restarted."
          : "Remote backup is disabled. Your data remains local.",
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Remote backup settings could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function serviceAction(action: "start" | "stop" | "restart") {
    setBusy(true);
    setError(null);
    try {
      if (action === "start") await startService();
      else if (action === "stop") await stopService();
      else await restartService();
      await onServiceChanged();
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The service action failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen settings-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">Local control center</p>
          <h1>Settings</h1>
          <p>
            Choose where inference happens and keep control of the private
            daemon.
          </p>
        </div>
      </header>
      {error ? <div className="inline-error">{error}</div> : null}
      {notice ? <div className="inline-notice">{notice}</div> : null}
      <div className="settings-grid">
        <form
          className="card settings-card"
          onSubmit={(event) => void save(event)}
        >
          <div className="settings-section-heading">
            <Shield size={19} />
            <div>
              <span className="section-label">Privacy</span>
              <h2>Data boundary</h2>
            </div>
          </div>
          <div className="segmented-control">
            {(["strict_local", "offline", "hybrid"] as PrivacyMode[]).map(
              (mode) => (
                <button
                  className={settings.privacyMode === mode ? "active" : ""}
                  key={mode}
                  type="button"
                  onClick={() =>
                    setSettings({ ...settings, privacyMode: mode })
                  }
                >
                  {mode === "strict_local"
                    ? "Strict local"
                    : mode === "offline"
                      ? "Offline"
                      : "Hybrid"}
                </button>
              ),
            )}
          </div>
          <p className="setting-help">
            {settings.privacyMode === "hybrid"
              ? "External HTTPS model endpoints are allowed. Only context required for a request is sent."
              : settings.privacyMode === "offline"
                ? "Only local model endpoints are allowed. The app makes no external inference requests."
                : "Local model endpoints only. This is the default privacy mode."}
          </p>
          <div className="settings-section-heading provider-heading">
            <KeyRound size={19} />
            <div>
              <span className="section-label">Model provider</span>
              <h2>Inference</h2>
            </div>
          </div>
          <label>
            <span>Provider</span>
            <select
              value={settings.provider}
              onChange={(event) =>
                setSettings({
                  ...settings,
                  provider: event.target.value as ProviderKind,
                })
              }
            >
              <option value="ollama">Ollama · local</option>
              <option value="openai_compatible">
                OpenAI-compatible · hosted or local
              </option>
            </select>
          </label>
          {settings.provider === "ollama" ? (
            <>
              <label>
                <span>Base URL</span>
                <input
                  required
                  type="url"
                  value={settings.ollamaBaseUrl}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      ollamaBaseUrl: event.target.value,
                    })
                  }
                />
              </label>
              <label>
                <span>Model</span>
                <input
                  required
                  placeholder="llama3.2"
                  value={settings.ollamaModel}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      ollamaModel: event.target.value,
                    })
                  }
                />
              </label>
            </>
          ) : (
            <>
              <label>
                <span>Base URL</span>
                <input
                  required
                  type="url"
                  value={settings.openaiBaseUrl}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      openaiBaseUrl: event.target.value,
                    })
                  }
                />
              </label>
              <label>
                <span>Model</span>
                <input
                  required
                  placeholder="model-name"
                  value={settings.openaiModel}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      openaiModel: event.target.value,
                    })
                  }
                />
              </label>
              <p className="setting-help">
                Use the compatibility endpoint published by GPT, Claude, Gemini,
                DeepSeek, GLM, Kimi, vLLM, LM Studio, or another compatible
                service. Soulmate negotiates the model&apos;s JSON capabilities
                automatically.
              </p>
              <label>
                <span>
                  API key{" "}
                  {settings.hasApiKey ? "· stored in system keychain" : ""}
                </span>
                <input
                  autoComplete="off"
                  placeholder={
                    settings.hasApiKey
                      ? "Leave blank to keep current key"
                      : "Optional for local endpoints"
                  }
                  type="password"
                  value={apiKey}
                  onChange={(event) => {
                    setApiKey(event.target.value);
                    setClearApiKey(false);
                  }}
                />
              </label>
              {settings.hasApiKey ? (
                <label className="check-label">
                  <input
                    checked={clearApiKey}
                    type="checkbox"
                    onChange={(event) => setClearApiKey(event.target.checked)}
                  />
                  <span>Remove stored API key</span>
                </label>
              ) : null}
            </>
          )}
          <button className="primary-button" disabled={busy} type="submit">
            <Save size={16} /> Save and restart
          </button>
        </form>
        <div className="settings-side">
          <article className="card service-card">
            <div className="settings-section-heading">
              <TerminalSquare size={19} />
              <div>
                <span className="section-label">Daemon</span>
                <h2>Local service</h2>
              </div>
            </div>
            <div className={`service-state large ${serviceStatus.state}`}>
              <span />
              {serviceStatus.state}
            </div>
            <p>{serviceStatus.message}</p>
            <div className="service-actions">
              <button
                className="secondary-button"
                disabled={busy || serviceStatus.state === "running"}
                type="button"
                onClick={() => void serviceAction("start")}
              >
                <Play size={15} /> Start
              </button>
              <button
                className="secondary-button"
                disabled={busy || serviceStatus.state === "stopped"}
                type="button"
                onClick={() => void serviceAction("stop")}
              >
                <CircleStop size={15} /> Stop
              </button>
              <button
                className="secondary-button"
                disabled={busy}
                type="button"
                onClick={() => void serviceAction("restart")}
              >
                <RefreshCw size={15} /> Restart
              </button>
            </div>
          </article>
          <article className="card logs-card">
            <div className="card-heading">
              <div>
                <span className="section-label">Private diagnostics</span>
                <h2>Recent logs</h2>
              </div>
              <button
                className="text-button"
                type="button"
                onClick={() => void load()}
              >
                Refresh
              </button>
            </div>
            <pre>
              {logs.length
                ? logs.join("\n")
                : "No daemon output recorded in this session."}
            </pre>
          </article>
        </div>
      </div>
      <form
        className="card settings-card remote-backup-settings"
        onSubmit={(event) => void saveBackup(event)}
      >
        <div className="settings-section-heading">
          <CloudUpload size={19} />
          <div>
            <span className="section-label">Off-device recovery</span>
            <h2>Encrypted remote backup</h2>
          </div>
        </div>
        <p className="setting-help remote-backup-help">
          Works with Cloudflare R2 and other S3-compatible private buckets.
          Create a bucket and a token with object read/write access, then paste
          the values below. Soulmate encrypts the archive before uploading it.
        </p>
        <label className="check-label">
          <input
            aria-label="Enable encrypted remote backup"
            checked={remoteBackup.enabled}
            type="checkbox"
            onChange={(event) =>
              setRemoteBackup({
                ...remoteBackup,
                enabled: event.target.checked,
              })
            }
          />
          <span>Enable encrypted remote backup</span>
        </label>
        {remoteBackup.enabled ? (
          <>
            <p className="setting-help remote-backup-help">
              An external endpoint automatically enables Hybrid privacy mode so
              the encrypted archive can leave this device.
            </p>
            <div className="settings-fields-grid">
              <label>
                <span>S3 endpoint URL</span>
                <input
                  required
                  placeholder="https://ACCOUNT_ID.r2.cloudflarestorage.com"
                  type="url"
                  value={remoteBackup.endpointUrl}
                  onChange={(event) =>
                    setRemoteBackup({
                      ...remoteBackup,
                      endpointUrl: event.target.value,
                    })
                  }
                />
              </label>
              <label>
                <span>Private bucket name</span>
                <input
                  required
                  placeholder="soulmate-backups"
                  value={remoteBackup.bucket}
                  onChange={(event) =>
                    setRemoteBackup({
                      ...remoteBackup,
                      bucket: event.target.value,
                    })
                  }
                />
              </label>
              <label>
                <span>
                  Access key ID
                  {remoteBackup.hasAccessKeyId ? " · stored in keychain" : ""}
                </span>
                <input
                  autoComplete="off"
                  placeholder={
                    remoteBackup.hasAccessKeyId
                      ? "Leave blank to keep the saved key"
                      : "Required"
                  }
                  required={!remoteBackup.hasSecretAccessKey}
                  type="password"
                  value={backupAccessKeyId}
                  onChange={(event) => {
                    setBackupAccessKeyId(event.target.value);
                    setClearBackupCredentials(false);
                  }}
                />
              </label>
              <label>
                <span>
                  Secret access key
                  {remoteBackup.hasSecretAccessKey
                    ? " · stored in keychain"
                    : ""}
                </span>
                <input
                  autoComplete="off"
                  placeholder={
                    remoteBackup.hasSecretAccessKey
                      ? "Leave blank to keep the saved key"
                      : "Required"
                  }
                  type="password"
                  value={backupSecretAccessKey}
                  onChange={(event) => {
                    setBackupSecretAccessKey(event.target.value);
                    setClearBackupCredentials(false);
                  }}
                />
              </label>
              <label>
                <span>
                  Encryption passphrase · at least 12 characters
                  {remoteBackup.hasPassphrase ? " · stored in keychain" : ""}
                </span>
                <input
                  autoComplete="new-password"
                  minLength={12}
                  placeholder={
                    remoteBackup.hasPassphrase
                      ? "Leave blank to keep the saved passphrase"
                      : "Required — keep a separate copy"
                  }
                  required={!remoteBackup.hasPassphrase}
                  type="password"
                  value={backupPassphrase}
                  onChange={(event) => {
                    setBackupPassphrase(event.target.value);
                    setClearBackupCredentials(false);
                  }}
                />
              </label>
              <label>
                <span>Backup every (hours)</span>
                <input
                  disabled={!remoteBackup.automaticDaily}
                  max={168}
                  min={1}
                  type="number"
                  value={remoteBackup.intervalHours}
                  onChange={(event) =>
                    setRemoteBackup({
                      ...remoteBackup,
                      intervalHours: Number(event.target.value),
                    })
                  }
                />
              </label>
            </div>
            <label className="check-label">
              <input
                checked={remoteBackup.automaticDaily}
                type="checkbox"
                onChange={(event) =>
                  setRemoteBackup({
                    ...remoteBackup,
                    automaticDaily: event.target.checked,
                  })
                }
              />
              <span>Back up automatically while Soulmate is running</span>
            </label>
            <details className="advanced-settings">
              <summary>Advanced S3 settings</summary>
              <div className="settings-fields-grid">
                <label>
                  <span>Signing region</span>
                  <input
                    required
                    value={remoteBackup.region}
                    onChange={(event) =>
                      setRemoteBackup({
                        ...remoteBackup,
                        region: event.target.value,
                      })
                    }
                  />
                </label>
                <label>
                  <span>Object prefix</span>
                  <input
                    value={remoteBackup.prefix}
                    onChange={(event) =>
                      setRemoteBackup({
                        ...remoteBackup,
                        prefix: event.target.value,
                      })
                    }
                  />
                </label>
              </div>
            </details>
          </>
        ) : null}
        {remoteBackup.hasPassphrase ||
        remoteBackup.hasAccessKeyId ||
        remoteBackup.hasSecretAccessKey ? (
          <label className="check-label">
            <input
              checked={clearBackupCredentials}
              type="checkbox"
              onChange={(event) =>
                setClearBackupCredentials(event.target.checked)
              }
            />
            <span>Remove saved backup credentials</span>
          </label>
        ) : null}
        <button className="primary-button" disabled={busy} type="submit">
          <Save size={16} /> Save backup settings and restart
        </button>
      </form>
    </section>
  );
}
