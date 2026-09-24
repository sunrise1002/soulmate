import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { apiRequest } from "../runtime.ts";
import type {
  DecisionIoDataClass,
  DecisionIoRetention,
  DecisionIoSource,
  DecisionIoSourceRemoval,
  ServiceIdentity,
} from "../types.ts";
import { formatDate } from "../utils.ts";

interface DecisionIoSourcesPanelProps {
  identities: ServiceIdentity[];
  onChanged: () => void;
}

const dataClassLabels: Record<DecisionIoDataClass, string> = {
  metadata: "Activity metadata",
  decision: "Decisions",
  correction: "Corrections",
  outcome: "Outcomes",
  prompt: "Full prompts",
  response: "Full responses",
  file_content: "File contents",
  diff: "Diffs",
};

const retentionLabels: Record<DecisionIoRetention, string> = {
  metadata_only: "Metadata only",
  structured_only: "Structured records",
  full_content: "Full content",
};

const defaultClasses: DecisionIoDataClass[] = [
  "metadata",
  "decision",
  "outcome",
];

function message(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

/** Owner approval, inspection, and removal of pushed Decision I/O sources. */
export function DecisionIoSourcesPanel({
  identities,
  onChanged,
}: DecisionIoSourcesPanelProps) {
  const [sources, setSources] = useState<DecisionIoSource[]>([]);
  const [identityId, setIdentityId] = useState("");
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [classes, setClasses] = useState(defaultClasses);
  const [retention, setRetention] =
    useState<DecisionIoRetention>("metadata_only");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const active = identities.filter((item) => item.active);
  const selectedIdentity = identityId || active[0]?.id || "";

  const load = useCallback(async () => {
    try {
      setSources(
        await apiRequest<DecisionIoSource[]>("GET", "/v1/decision-io/sources"),
      );
      setError(null);
    } catch (reason) {
      setError(message(reason, "Connected sources are unavailable."));
    }
  }, []);

  useEffect(() => void load(), [load]);

  function toggle(value: DecisionIoDataClass) {
    setClasses((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  }

  async function register(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !selectedIdentity || !classes.length) return;
    setBusy(true);
    setNotice(null);
    try {
      await apiRequest("POST", "/v1/decision-io/sources", {
        name,
        provider,
        service_identity_id: selectedIdentity,
        data_classes: classes,
        raw_retention_policy: retention,
      });
      setName("");
      setProvider("");
      await load();
      onChanged();
    } catch (reason) {
      setError(message(reason, "The source could not be approved."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(source: DecisionIoSource) {
    const consequence =
      `Remove ${source.name}? This deletes ${String(source.raw_event_count)} events, ` +
      `${String(source.decision_count)} decisions, and every observation and ` +
      "Evidence derived from them, then rebuilds the model.";
    if (busy || !window.confirm(consequence)) return;
    setBusy(true);
    try {
      const removed = await apiRequest<DecisionIoSourceRemoval>(
        "DELETE",
        `/v1/decision-io/sources/${encodeURIComponent(source.id)}`,
      );
      setNotice(
        `Removed ${String(removed.raw_event_count)} events and ${String(removed.evidence_count)} Evidence items.`,
      );
      await load();
      onChanged();
    } catch (reason) {
      setError(message(reason, "The source could not be removed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card" aria-label="Connected sources">
      <p className="section-label">Decision I/O</p>
      <h2>Connected sources</h2>
      {error ? <div className="inline-error">{error}</div> : null}
      {notice ? <p className="muted">{notice}</p> : null}
      {sources.length ? (
        <ul className="source-list">
          {sources.map((source) => (
            <li key={source.id}>
              <div>
                <strong>{source.name}</strong> · {source.provider ?? "unknown"}
                <small>
                  {" "}
                  approved{" "}
                  {source.consent_at ? formatDate(source.consent_at) : "—"}
                </small>
                <p className="muted">
                  May send:{" "}
                  {source.data_classes
                    .map((item) => dataClassLabels[item])
                    .join(", ")}{" "}
                  · Keeps: {retentionLabels[source.raw_retention_policy]} ·
                  Authors: {source.author_scope.replaceAll("_", " ")}
                </p>
                <p className="muted">
                  {source.raw_event_count} events · {source.decision_count}{" "}
                  decisions ·{" "}
                  {source.resolution_observation_count +
                    source.outcome_observation_count}{" "}
                  observations ({source.unmatched_observation_count} unmatched)
                </p>
              </div>
              <button
                aria-label={`Remove ${source.name}`}
                className="text-button danger"
                disabled={busy}
                type="button"
                onClick={() => void remove(source)}
              >
                <Trash2 size={14} /> Remove
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No agent is allowed to send events yet.</p>
      )}
      <form onSubmit={(event) => void register(event)}>
        <h3>Approve a source</h3>
        <label>
          Service identity
          <select
            value={selectedIdentity}
            onChange={(event) => setIdentityId(event.target.value)}
          >
            {active.map((identity) => (
              <option key={identity.id} value={identity.id}>
                {identity.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Name
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          Provider
          <input
            required
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          />
        </label>
        <fieldset>
          <legend>Allowed data</legend>
          {Object.entries(dataClassLabels).map(([value, label]) => (
            <label key={value}>
              <input
                checked={classes.includes(value as DecisionIoDataClass)}
                type="checkbox"
                onChange={() => toggle(value as DecisionIoDataClass)}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <label>
          Retention
          <select
            value={retention}
            onChange={(event) =>
              setRetention(event.target.value as DecisionIoRetention)
            }
          >
            {Object.entries(retentionLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary-button"
          disabled={busy || !selectedIdentity || !classes.length}
          type="submit"
        >
          Approve source
        </button>
      </form>
    </article>
  );
}
