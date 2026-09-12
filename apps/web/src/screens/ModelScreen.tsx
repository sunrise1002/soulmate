import { useCallback, useEffect, useState } from "react";
import type { ModelSummary, Preference, SoulmateClient } from "@soulmate/sdk";

interface Props {
  client: SoulmateClient;
  onAuthError: (error: unknown) => void;
}

export function ModelScreen({ client, onAuthError }: Props) {
  const [summary, setSummary] = useState<ModelSummary | null>(null);
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([client.modelSummary(), client.preferences()])
      .then(([nextSummary, nextPreferences]) => {
        setSummary(nextSummary);
        setPreferences(nextPreferences);
      })
      .catch(onAuthError);
  }, [client, onAuthError]);

  useEffect(load, [load]);

  const correct = async (key: string, value: number) => {
    try {
      await client.correctPreference(key, value);
      setStatus(`Saved your correction for ${key}.`);
      load();
    } catch (caught) {
      onAuthError(caught);
      setStatus("The correction could not be saved.");
    }
  };

  return (
    <section className="panel">
      <h2>My Model</h2>
      {summary !== null && (
        <p className="hint">
          Version {String(summary.version ?? 0)} · {summary.preference_count}{" "}
          preferences · evidence revision {summary.evidence_revision}
        </p>
      )}
      <ul className="preferences">
        {preferences.map((preference) => (
          <li key={`${preference.key}-${String(preference.model_version)}`}>
            <span className="key">{preference.key}</span>
            <span className="value">{preference.value.toFixed(2)}</span>
            <span className="hint">
              uncertainty {preference.uncertainty.toFixed(2)}
            </span>
            <button
              type="button"
              onClick={() => void correct(preference.key, 1)}
            >
              I like this
            </button>
            <button
              type="button"
              onClick={() => void correct(preference.key, -1)}
            >
              I do not
            </button>
          </li>
        ))}
      </ul>
      {preferences.length === 0 && (
        <p className="hint">No preferences have been learned yet.</p>
      )}
      {status !== null && <p role="status">{status}</p>}
    </section>
  );
}
