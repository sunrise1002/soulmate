import { useCallback, useEffect, useState } from "react";
import type { EmbeddingModel as Model, SoulmateClient } from "@soulmate/sdk";

interface Props {
  client: SoulmateClient;
}

const POLL_INTERVAL_MS = 1000;

function formatBytes(value: number): string {
  if (value < 1_000_000) return `${String(Math.round(value / 1000))} KB`;
  if (value < 1_000_000_000)
    return `${String(Math.round(value / 1_000_000))} MB`;
  return `${(value / 1_000_000_000).toFixed(1)} GB`;
}

/** Owner-only view of the optional local model; never render it for paired devices. */
export function EmbeddingModel({ client }: Props) {
  const [model, setModel] = useState<Model | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(() => {
    client
      .embeddingModel()
      .then(setModel)
      .catch(() => setStatus("The local model is unavailable."));
  }, [client]);

  useEffect(load, [load]);

  // The daemon keeps download progress in memory only, so it is polled.
  useEffect(() => {
    if (model?.downloading !== true) return undefined;
    const timer = window.setInterval(load, POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [load, model?.downloading]);

  const act = async (action: () => Promise<Model>, failure: string) => {
    try {
      setModel(await action());
      setStatus(null);
    } catch (caught) {
      setStatus(
        caught instanceof Error && caught.message ? caught.message : failure,
      );
    }
  };

  if (model === null) {
    return status === null ? null : <p role="alert">{status}</p>;
  }

  return (
    <div className="prediction">
      <h3>Multilingual key matching</h3>
      <p className="hint">
        An optional local model recognizes that a message in one language is
        about a key written in another. Nothing is downloaded until you ask.
      </p>
      <p className="hint">
        {model.display_name} · {model.license} ·{" "}
        {formatBytes(model.download_bytes)} to download · about{" "}
        {formatBytes(model.peak_memory_bytes)} of memory while in use
      </p>
      {model.error !== null && <p role="alert">{model.error}</p>}
      {model.downloading && (
        <p className="hint">
          Downloading {formatBytes(model.downloaded_bytes)} of{" "}
          {formatBytes(model.expected_bytes)}
        </p>
      )}
      {model.installed && model.provider === "none" && (
        <p className="hint">
          The model is installed but switched off. Set embedding.provider to
          &quot;local&quot; in the configuration to use it.
        </p>
      )}
      {!model.can_download && !model.installed && (
        <p className="hint">
          The configured privacy mode does not allow downloading a model here.
        </p>
      )}
      {model.downloading ? (
        <button
          type="button"
          onClick={() =>
            void act(
              () => client.cancelEmbeddingModelDownload(),
              "The download could not be stopped.",
            )
          }
        >
          Stop download
        </button>
      ) : (
        !model.installed && (
          <button
            type="button"
            disabled={!model.can_download}
            onClick={() =>
              void act(
                () => client.downloadEmbeddingModel(),
                "The download could not be started.",
              )
            }
          >
            Download {formatBytes(model.download_bytes)}
          </button>
        )
      )}
      {(model.installed || model.downloaded_bytes > 0) &&
        !model.downloading && (
          <button
            type="button"
            onClick={() =>
              void act(
                () => client.removeEmbeddingModel(),
                "The model files could not be removed.",
              )
            }
          >
            {model.installed ? "Remove model" : "Discard partial download"}
          </button>
        )}
      {status !== null && <p role="alert">{status}</p>}
    </div>
  );
}
