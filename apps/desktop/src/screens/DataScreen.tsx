import {
  ArchiveRestore,
  DatabaseBackup,
  FileKey,
  FileUp,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { apiRequest, restartService } from "../runtime.ts";
import type {
  ChatImportResult,
  DataArchive,
  DataSource,
  ImportFormat,
  RestoreStaged,
  SourceDeletionResult,
} from "../types.ts";

interface DataScreenProps {
  onDataChanged: () => void;
  onServiceChanged: () => Promise<void>;
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function readArchive(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("The archive could not be read."));
    reader.onload = () => {
      if (typeof reader.result !== "string") {
        reject(new Error("The archive could not be encoded."));
        return;
      }
      const encoded = reader.result.split(",", 2)[1];
      if (!encoded) {
        reject(new Error("The archive could not be encoded."));
        return;
      }
      resolve(encoded);
    };
    reader.readAsDataURL(file);
  });
}

export function DataScreen({
  onDataChanged,
  onServiceChanged,
}: DataScreenProps) {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importFormat, setImportFormat] = useState<ImportFormat>("auto");
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSources = useCallback(async () => {
    try {
      setSources(await apiRequest<DataSource[]>("GET", "/v1/data/sources"));
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason, "Imported sources are unavailable."));
    }
  }, []);

  useEffect(() => void loadSources(), [loadSources]);

  async function createArchive(encrypted: boolean) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const archive = encrypted
        ? await apiRequest<DataArchive>("POST", "/v1/data/exports", {
            passphrase,
          })
        : await apiRequest<DataArchive>("POST", "/v1/data/backups");
      setNotice(`${archive.filename} saved locally at ${archive.path}`);
      if (encrypted) setPassphrase("");
    } catch (reason) {
      setError(errorMessage(reason, "The archive could not be created."));
    } finally {
      setBusy(false);
    }
  }

  async function importHistory() {
    if (busy || importFile === null) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest<ChatImportResult>(
        "POST",
        "/v1/data/imports",
        {
          name: importFile.name,
          format: importFormat,
          content: await importFile.text(),
        },
      );
      setNotice(
        `Imported ${String(result.message_count)} messages from ${result.source.name}.`,
      );
      setImportFile(null);
      await loadSources();
      onDataChanged();
    } catch (reason) {
      setError(errorMessage(reason, "The chat history could not be imported."));
    } finally {
      setBusy(false);
    }
  }

  async function deleteSource(source: DataSource) {
    if (
      busy ||
      !window.confirm(
        `Delete ${source.name} and all conversations and evidence derived from it?`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest<SourceDeletionResult>(
        "DELETE",
        `/v1/data/sources/${encodeURIComponent(source.id)}`,
      );
      setNotice(
        `Deleted ${String(result.message_count)} messages and rebuilt model snapshot ${String(result.snapshot_version)}.`,
      );
      await loadSources();
      onDataChanged();
    } catch (reason) {
      setError(
        errorMessage(reason, "The imported source could not be deleted."),
      );
    } finally {
      setBusy(false);
    }
  }

  async function restore() {
    if (
      busy ||
      restoreFile === null ||
      !window.confirm(
        "Restore this archive into the fresh installation and restart the local service?",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest<RestoreStaged>(
        "POST",
        "/v1/data/restores",
        {
          archive_base64: await readArchive(restoreFile),
          passphrase: passphrase || null,
        },
      );
      if (!result.restart_required) {
        throw new Error("The restore did not request the required restart.");
      }
      await restartService();
      await onServiceChanged();
      onDataChanged();
      setRestoreFile(null);
      setPassphrase("");
      setNotice(
        `Restored schema ${result.source_schema_revision}. The Personal Model is being rebuilt.`,
      );
    } catch (reason) {
      setError(errorMessage(reason, "The archive could not be restored."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen data-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">Local data ownership</p>
          <h1>Data &amp; Privacy</h1>
          <p>
            Back up, move, import, and remove your Personal Model without a
            cloud account.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={busy}
          type="button"
          onClick={() => void loadSources()}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </header>
      {error ? <div className="inline-error">{error}</div> : null}
      {notice ? <div className="inline-notice">{notice}</div> : null}

      <div className="data-grid">
        <article className="card data-card">
          <div className="settings-section-heading">
            <DatabaseBackup size={19} />
            <div>
              <span className="section-label">Resilience</span>
              <h2>Local backup</h2>
            </div>
          </div>
          <p>
            Create a consistent local archive. Device and API credentials are
            excluded.
          </p>
          <button
            className="primary-button"
            disabled={busy}
            type="button"
            onClick={() => void createArchive(false)}
          >
            <DatabaseBackup size={14} /> Back up now
          </button>
        </article>

        <article className="card data-card">
          <div className="settings-section-heading">
            <FileKey size={19} />
            <div>
              <span className="section-label">Portability</span>
              <h2>Encrypted export</h2>
            </div>
          </div>
          <label>
            <span>Passphrase · at least 12 characters</span>
            <input
              minLength={12}
              type="password"
              value={passphrase}
              onChange={(event) => setPassphrase(event.target.value)}
            />
          </label>
          <button
            className="secondary-button"
            disabled={busy || passphrase.length < 12}
            type="button"
            onClick={() => void createArchive(true)}
          >
            <FileKey size={14} /> Export encrypted archive
          </button>
        </article>

        <article className="card data-card">
          <div className="settings-section-heading">
            <FileUp size={19} />
            <div>
              <span className="section-label">Learning sources</span>
              <h2>Import chat history</h2>
            </div>
          </div>
          <label>
            <span>JSON, Markdown, or plain text</span>
            <input
              accept=".json,.md,.markdown,.txt,application/json,text/plain,text/markdown"
              type="file"
              onChange={(event) =>
                setImportFile(event.target.files?.item(0) ?? null)
              }
            />
          </label>
          <label>
            <span>Format</span>
            <select
              value={importFormat}
              onChange={(event) =>
                setImportFormat(event.target.value as ImportFormat)
              }
            >
              <option value="auto">Auto detect</option>
              <option value="json">Generic JSON</option>
              <option value="markdown">Markdown</option>
              <option value="text">Plain text</option>
              <option value="chatgpt">ChatGPT export</option>
              <option value="claude">Claude export</option>
            </select>
          </label>
          <button
            className="secondary-button"
            disabled={busy || importFile === null}
            type="button"
            onClick={() => void importHistory()}
          >
            <FileUp size={14} /> Import history
          </button>
        </article>

        <article className="card data-card">
          <div className="settings-section-heading">
            <ArchiveRestore size={19} />
            <div>
              <span className="section-label">Fresh installation</span>
              <h2>Restore archive</h2>
            </div>
          </div>
          <p>
            Restore only into an installation with no owner-created data. A
            restart migrates and rebuilds the model.
          </p>
          <label>
            <span>.dtwb or .dtw archive · desktop limit 64 MiB</span>
            <input
              accept=".dtw,.dtwb"
              type="file"
              onChange={(event) =>
                setRestoreFile(event.target.files?.item(0) ?? null)
              }
            />
          </label>
          <button
            className="secondary-button"
            disabled={busy || restoreFile === null}
            type="button"
            onClick={() => void restore()}
          >
            <ArchiveRestore size={14} /> Restore and restart
          </button>
        </article>
      </div>

      <section className="data-sources">
        <div className="card-heading">
          <div>
            <span className="section-label">Imported provenance</span>
            <h2>Sources</h2>
          </div>
          <span>{sources.length} total</span>
        </div>
        {sources.length === 0 ? (
          <p className="muted">No imported sources yet.</p>
        ) : (
          <ul className="source-list">
            {sources.map((source) => (
              <li className="card source-row" key={source.id}>
                <div>
                  <strong>{source.name}</strong>
                  <p>
                    {source.source_type.replace("import:", "")} ·{" "}
                    {new Date(source.created_at).toLocaleString()}
                  </p>
                </div>
                <button
                  aria-label={`Delete ${source.name}`}
                  className="icon-button danger"
                  disabled={busy}
                  type="button"
                  onClick={() => void deleteSource(source)}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
