import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "../runtime.ts";
import type { EmbeddingModel } from "../types.ts";
import { formatBytes, percentage } from "../utils.ts";

const POLL_INTERVAL_MS = 1000;

/** Explain why the download button is unavailable before the owner presses it. */
function blockedReason(model: EmbeddingModel): string | null {
  if (model.can_download) return null;
  if (model.privacy_mode === "offline") {
    return "Offline mode blocks every download. Import the files manually instead.";
  }
  return "The privacy settings do not allow downloading this model.";
}

export function EmbeddingModelPanel() {
  const [model, setModel] = useState<EmbeddingModel | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setModel(await apiRequest<EmbeddingModel>("GET", "/v1/embedding-model"));
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The local model is unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load]);

  // Progress lives in the daemon's memory only, so it is polled while it moves.
  useEffect(() => {
    if (model?.downloading !== true) return undefined;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [load, model?.downloading]);

  async function act(path: string, failure: string) {
    if (busy) return;
    setBusy(true);
    try {
      setModel(await apiRequest<EmbeddingModel>("POST", path));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : failure);
    } finally {
      setBusy(false);
    }
  }

  if (model === null) {
    return error === null ? null : <div className="inline-error">{error}</div>;
  }

  const blocked = blockedReason(model);
  const progress =
    model.expected_bytes === 0
      ? 0
      : model.downloaded_bytes / model.expected_bytes;

  return (
    <article className="card embedding-model" aria-label="Local language model">
      <span className="section-label">Key consistency</span>
      <h2>Multilingual key matching</h2>
      <p>
        An optional local model lets Soulmate recognize that a message in one
        language is about a key written in another. Nothing is downloaded until
        you ask, and the model never leaves this computer.
      </p>
      <dl className="embedding-facts">
        <div>
          <dt>Model</dt>
          <dd>
            {model.display_name} · {model.license}
          </dd>
        </div>
        <div>
          <dt>Download</dt>
          <dd>{formatBytes(model.download_bytes)}</dd>
        </div>
        <div>
          <dt>Memory while in use</dt>
          <dd>about {formatBytes(model.peak_memory_bytes)}</dd>
        </div>
      </dl>
      {error ? <div className="inline-error">{error}</div> : null}
      {model.error ? <div className="inline-error">{model.error}</div> : null}
      {blocked ? <p className="muted">{blocked}</p> : null}
      {model.installed && model.provider === "none" ? (
        <p className="muted">
          The model is installed but switched off. Set{" "}
          <code>embedding.provider = &quot;local&quot;</code> in the
          configuration to use it.
        </p>
      ) : null}
      {model.downloading ? (
        <>
          <div className="confidence-line">
            <span style={{ width: `${String(progress * 100)}%` }} />
          </div>
          <small>
            {formatBytes(model.downloaded_bytes)} of{" "}
            {formatBytes(model.expected_bytes)} · {percentage(progress)}
          </small>
        </>
      ) : null}
      <div className="resolve-actions">
        {model.downloading ? (
          <button
            className="secondary-button"
            disabled={busy}
            type="button"
            onClick={() =>
              void act(
                "/v1/embedding-model/cancel",
                "The download could not be stopped.",
              )
            }
          >
            Stop download
          </button>
        ) : null}
        {!model.installed && !model.downloading ? (
          <button
            className="secondary-button"
            disabled={busy || blocked !== null}
            type="button"
            onClick={() =>
              void act(
                "/v1/embedding-model/download",
                "The download could not be started.",
              )
            }
          >
            Download {formatBytes(model.download_bytes)}
          </button>
        ) : null}
        {model.installed || model.downloaded_bytes > 0 ? (
          <button
            className="secondary-button"
            disabled={busy || model.downloading}
            type="button"
            onClick={() =>
              void act(
                "/v1/embedding-model/remove",
                "The model files could not be removed.",
              )
            }
          >
            {model.installed ? "Remove model" : "Discard partial download"}
          </button>
        ) : null}
      </div>
    </article>
  );
}
