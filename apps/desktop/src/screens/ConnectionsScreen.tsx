import { FolderOpen, PlugZap, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../runtime.ts";
import type {
  ConnectorManifest,
  ConnectorRegistration,
  ConnectorRemoval,
  ConnectorSync,
  ConnectorSyncStatus,
} from "../types.ts";

interface ConnectionsScreenProps {
  onDataChanged: () => void;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "The connector operation failed.";
}

function pause(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function ConnectionsScreen({ onDataChanged }: ConnectionsScreenProps) {
  const [catalog, setCatalog] = useState<ConnectorManifest[]>([]);
  const [registrations, setRegistrations] = useState<ConnectorRegistration[]>(
    [],
  );
  const [notesPath, setNotesPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [available, configured] = await Promise.all([
        apiRequest<ConnectorManifest[]>("GET", "/v1/connectors/catalog"),
        apiRequest<ConnectorRegistration[]>("GET", "/v1/connectors"),
      ]);
      setCatalog(available);
      setRegistrations(configured);
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, []);

  useEffect(() => void load(), [load]);

  async function configure(manifest: ConnectorManifest) {
    if (busy) return;
    if (manifest.connector_id === "soulmate.local-notes" && !notesPath.trim()) {
      setError("Choose a local notes directory first.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiRequest<ConnectorRegistration>("POST", "/v1/connectors", {
        connector_id: manifest.connector_id,
        permissions: manifest.permissions,
        configuration:
          manifest.connector_id === "soulmate.local-notes"
            ? { path: notesPath.trim() }
            : {},
      });
      setNotice(`${manifest.name} is ready to synchronize.`);
      await load();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function synchronize(registration: ConnectorRegistration) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const queued = await apiRequest<ConnectorSync>(
        "POST",
        `/v1/connectors/${encodeURIComponent(registration.connector_id)}/sync`,
      );
      let status: ConnectorSyncStatus | null = null;
      for (let attempt = 0; attempt < 240; attempt += 1) {
        await pause(250);
        status = await apiRequest<ConnectorSyncStatus>(
          "GET",
          `/v1/connectors/syncs/${encodeURIComponent(queued.job_id)}`,
        );
        if (status.status !== "queued" && status.status !== "running") break;
      }
      if (status?.status !== "succeeded") {
        throw new Error(status?.error ?? "Connector synchronization failed.");
      }
      setNotice(`${registration.name} synchronized locally.`);
      await load();
      onDataChanged();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function remove(registration: ConnectorRegistration) {
    if (
      busy ||
      !window.confirm(
        `Remove ${registration.name} and all RawEvents and evidence derived from it?`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const removed = await apiRequest<ConnectorRemoval>(
        "DELETE",
        `/v1/connectors/${encodeURIComponent(registration.connector_id)}`,
      );
      setNotice(
        `Removed ${String(removed.raw_event_count)} source events and rebuilt model snapshot ${String(removed.snapshot_version)}.`,
      );
      await load();
      onDataChanged();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen connections-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">Optional local integrations</p>
          <h1>Connections</h1>
          <p>
            Review every requested permission before a connector can add local
            source events.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={busy}
          type="button"
          onClick={() => void load()}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </header>
      {error ? <div className="inline-error">{error}</div> : null}
      {notice ? <div className="inline-notice">{notice}</div> : null}

      <div className="connector-list">
        {catalog.map((manifest) => {
          const registration = registrations.find(
            (item) => item.connector_id === manifest.connector_id,
          );
          return (
            <article
              className="card connector-card"
              key={manifest.connector_id}
            >
              <div className="card-heading">
                <div className="settings-section-heading">
                  <PlugZap size={19} />
                  <div>
                    <span className="section-label">v{manifest.version}</span>
                    <h2>{manifest.name}</h2>
                  </div>
                </div>
                <span
                  className={`status-chip ${registration?.sync_status ?? "never"}`}
                >
                  {registration?.sync_status ?? "not configured"}
                </span>
              </div>
              <p>{manifest.description}</p>
              <div className="connector-permissions">
                {manifest.permissions.map((permission) => (
                  <span key={permission}>{permission}</span>
                ))}
              </div>
              <small>Reads: {manifest.data_access.join("; ")}</small>
              {manifest.network_hosts.length > 0 ? (
                <small>Network: {manifest.network_hosts.join(", ")}</small>
              ) : (
                <small>Network: none</small>
              )}
              {manifest.connector_id === "soulmate.local-notes" &&
              !registration ? (
                <label>
                  <span>Local notes directory</span>
                  <div className="path-input">
                    <FolderOpen size={16} />
                    <input
                      aria-label="Local notes directory"
                      placeholder="/Users/you/Documents/Notes"
                      type="text"
                      value={notesPath}
                      onChange={(event) => setNotesPath(event.target.value)}
                    />
                  </div>
                </label>
              ) : null}
              <div className="connector-actions">
                {registration ? (
                  <>
                    <button
                      className="primary-button"
                      disabled={busy || !registration.enabled}
                      type="button"
                      onClick={() => void synchronize(registration)}
                    >
                      <RefreshCw size={14} /> Sync now
                    </button>
                    <button
                      className="secondary-button danger"
                      disabled={busy}
                      type="button"
                      onClick={() => void remove(registration)}
                    >
                      <Trash2 size={14} /> Remove
                    </button>
                  </>
                ) : (
                  <button
                    className="primary-button"
                    disabled={busy}
                    type="button"
                    onClick={() => void configure(manifest)}
                  >
                    <PlugZap size={14} /> Review &amp; enable
                  </button>
                )}
              </div>
            </article>
          );
        })}
        {catalog.length === 0 ? (
          <div className="card empty-state">
            No connector plugins are installed in this daemon.
          </div>
        ) : null}
      </div>
    </section>
  );
}
