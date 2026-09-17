import { useCallback, useEffect, useState } from "react";
import type {
  ActiveQuestion,
  ModelSummary,
  Preference,
  SoulmateClient,
} from "@soulmate/sdk";

import { DuplicateKeys } from "./DuplicateKeys.tsx";

interface Props {
  client: SoulmateClient;
  /** Key alias review is owner-only; paired devices would be refused. */
  isOwner: boolean;
  onAuthError: (error: unknown) => void;
}

export function ModelScreen({ client, isOwner, onAuthError }: Props) {
  const [summary, setSummary] = useState<ModelSummary | null>(null);
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [question, setQuestion] = useState<ActiveQuestion | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([
      client.modelSummary(),
      client.preferences(),
      client.activeQuestions(),
    ])
      .then(([nextSummary, nextPreferences, questions]) => {
        setSummary(nextSummary);
        setPreferences(nextPreferences);
        setQuestion(
          questions.find((item) => item.status === "pending") ?? null,
        );
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

  const generateQuestion = async () => {
    try {
      const generated = await client.generateActiveQuestions(1);
      setQuestion(generated[0] ?? null);
      if (generated.length === 0)
        setStatus("No new question is available yet.");
    } catch (caught) {
      onAuthError(caught);
    }
  };

  const answerQuestion = async (choice: "a" | "b") => {
    if (question === null) return;
    try {
      await client.answerActiveQuestion(question.id, choice);
      setQuestion(null);
      setStatus("Your answer was added as preference evidence.");
      load();
    } catch (caught) {
      onAuthError(caught);
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
      <div className="prediction">
        <h3>Clarify uncertain trade-offs</h3>
        {question === null ? (
          <button type="button" onClick={() => void generateQuestion()}>
            Ask me a question
          </button>
        ) : (
          <div>
            <p>{question.prompt}</p>
            <button type="button" onClick={() => void answerQuestion("a")}>
              {question.option_a_label}
            </button>
            <button type="button" onClick={() => void answerQuestion("b")}>
              {question.option_b_label}
            </button>
          </div>
        )}
      </div>
      {isOwner && <DuplicateKeys client={client} onChanged={load} />}
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
