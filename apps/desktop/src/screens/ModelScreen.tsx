import {
  BrainCircuit,
  ChevronRight,
  Pencil,
  Plus,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { DuplicateKeysPanel } from "../components/DuplicateKeysPanel.tsx";
import { EmbeddingModelPanel } from "../components/EmbeddingModelPanel.tsx";
import { KeyLabelEditor } from "../components/KeyLabelEditor.tsx";
import { EmptyState } from "../components/EmptyState.tsx";
import { apiRequest } from "../runtime.ts";
import type {
  ActiveQuestion,
  Evidence,
  ModelSummary,
  Preference,
} from "../types.ts";
import {
  formatDate,
  humanizeKey,
  percentage,
  preferenceLabel,
} from "../utils.ts";

interface ModelScreenProps {
  revision: number;
  onModelChanged: () => void;
}

interface CorrectionDraft {
  key: string;
  value: number;
  context: Record<string, unknown>;
}

export function ModelScreen({ revision, onModelChanged }: ModelScreenProps) {
  const [preferences, setPreferences] = useState<Preference[]>([]);
  const [questions, setQuestions] = useState<ActiveQuestion[]>([]);
  const [summary, setSummary] = useState<ModelSummary | null>(null);
  const [selected, setSelected] = useState<Preference | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [correction, setCorrection] = useState<CorrectionDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [model, items, activeQuestions] = await Promise.all([
        apiRequest<ModelSummary>("GET", "/v1/model/summary"),
        apiRequest<Preference[]>("GET", "/v1/preferences"),
        apiRequest<ActiveQuestion[]>("GET", "/v1/active-questions"),
      ]);
      setSummary(model);
      setPreferences(items);
      setQuestions(activeQuestions.filter((item) => item.status === "pending"));
      setSelected(
        (current) => items.find((item) => item.key === current?.key) ?? null,
      );
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Your model is unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load, revision]);

  async function inspect(item: Preference) {
    setSelected(item);
    setCorrection(null);
    try {
      setEvidence(
        await apiRequest<Evidence[]>(
          "GET",
          `/v1/preferences/${encodeURIComponent(item.key)}/evidence`,
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Evidence is unavailable.",
      );
    }
  }

  async function generateQuestion(targetKey?: string) {
    if (busy) return;
    setBusy(true);
    try {
      const generated = await apiRequest<ActiveQuestion[]>(
        "POST",
        "/v1/active-questions/generate",
        { limit: 1, target_key: targetKey ?? null },
      );
      setQuestions((items) => [...generated, ...items]);
      setError(
        generated.length === 0
          ? "Add more preference evidence before generating another question."
          : null,
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "A question could not be generated.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function answerQuestion(questionId: string, choice: "a" | "b") {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest("POST", `/v1/active-questions/${questionId}/answer`, {
        choice,
      });
      setQuestions((items) => items.filter((item) => item.id !== questionId));
      await load();
      onModelChanged();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The answer could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitCorrection(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (correction === null || busy) return;
    setBusy(true);
    try {
      await apiRequest("POST", "/v1/preferences/corrections", {
        target_key: correction.key,
        value: correction.value,
        context: correction.context,
      });
      const correctedKey = correction.key;
      setCorrection(null);
      await load();
      if (selected?.key === correctedKey) {
        setEvidence(
          await apiRequest<Evidence[]>(
            "GET",
            `/v1/preferences/${encodeURIComponent(correctedKey)}/evidence`,
          ),
        );
      }
      onModelChanged();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The correction could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function removeEvidence(evidenceId: string) {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest("DELETE", `/v1/evidence/${evidenceId}`);
      setEvidence((items) => items.filter((item) => item.id !== evidenceId));
      await load();
      onModelChanged();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The evidence could not be deleted.",
      );
    } finally {
      setBusy(false);
    }
  }

  const activeQuestion = questions[0];

  return (
    <section className="screen model-screen">
      <header className="screen-header model-header">
        <div>
          <p className="eyebrow">Built from your evidence</p>
          <h1>My Model</h1>
          <p>
            Inspect what Soulmate believes, why it believes it, and correct
            anything that feels off.
          </p>
        </div>
        <div className="snapshot-badge">
          <ShieldCheck size={17} />
          <span>
            Snapshot <strong>{summary?.version ?? "—"}</strong>
          </span>
        </div>
      </header>
      <div className="model-stats">
        <div>
          <strong>{summary?.preference_count ?? 0}</strong>
          <span>Preferences</span>
        </div>
        <div>
          <strong>{summary?.goal_count ?? 0}</strong>
          <span>Goals</span>
        </div>
        <div>
          <strong>{summary?.constraint_count ?? 0}</strong>
          <span>Constraints</span>
        </div>
        <div>
          <strong>{summary?.evidence_revision ?? 0}</strong>
          <span>Evidence revision</span>
        </div>
      </div>
      {error ? <div className="inline-error">{error}</div> : null}
      <article className="card resolve-card">
        <div>
          <span className="section-label">Active learning</span>
          <h2>Clarify uncertain trade-offs</h2>
          <p>
            Soulmate asks only about areas where stronger evidence is useful.
          </p>
        </div>
        {activeQuestion === undefined ? (
          <button
            className="secondary-button"
            disabled={busy || preferences.length === 0}
            type="button"
            onClick={() => void generateQuestion()}
          >
            Ask me a question
          </button>
        ) : (
          <div className="resolve-actions">
            <strong>{activeQuestion.prompt}</strong>
            <button
              className="choice"
              disabled={busy}
              type="button"
              onClick={() => void answerQuestion(activeQuestion.id, "a")}
            >
              {activeQuestion.option_a_label}
            </button>
            <button
              className="choice"
              disabled={busy}
              type="button"
              onClick={() => void answerQuestion(activeQuestion.id, "b")}
            >
              {activeQuestion.option_b_label}
            </button>
          </div>
        )}
      </article>
      <EmbeddingModelPanel />
      <DuplicateKeysPanel
        revision={revision}
        onChanged={() => {
          void load();
          onModelChanged();
        }}
      />
      {preferences.length ? (
        <div className="preference-grid">
          {preferences.map((item) => (
            <button
              className="preference-card"
              key={`${item.key}-${JSON.stringify(item.context)}`}
              type="button"
              onClick={() => void inspect(item)}
            >
              <div className="preference-card-top">
                <span
                  className={
                    item.value >= 0 ? "signal positive" : "signal negative"
                  }
                />
                <ChevronRight size={17} />
              </div>
              <h2>{humanizeKey(item.key)}</h2>
              <p>{preferenceLabel(item.value)}</p>
              <div className="confidence-line">
                <span style={{ width: `${String(item.confidence * 100)}%` }} />
              </div>
              <small>{percentage(item.confidence)} confidence</small>
            </button>
          ))}
          <button
            className="preference-card add-card"
            type="button"
            onClick={() => setCorrection({ key: "", value: 0.5, context: {} })}
          >
            <Plus size={22} />
            <span>Add a preference</span>
          </button>
        </div>
      ) : (
        <EmptyState
          icon={BrainCircuit}
          title="Your model is ready to learn"
          description="Chat about what you value, or add a preference directly. Every belief remains inspectable and correctable."
        />
      )}
      {selected !== null ? (
        <div
          className="drawer-backdrop"
          role="presentation"
          onMouseDown={() => setSelected(null)}
        >
          <aside
            className="model-drawer"
            aria-label="Preference evidence"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              className="icon-button drawer-close"
              aria-label="Close"
              type="button"
              onClick={() => setSelected(null)}
            >
              <X size={18} />
            </button>
            <p className="eyebrow">Preference detail</p>
            <h2>{humanizeKey(selected.key)}</h2>
            <div className="preference-value">
              <strong>{preferenceLabel(selected.value)}</strong>
              <span>
                {selected.value.toFixed(2)} · {percentage(selected.confidence)}{" "}
                confidence
              </span>
            </div>
            <button
              className="secondary-button"
              type="button"
              onClick={() =>
                setCorrection({
                  key: selected.key,
                  value: selected.value,
                  context: selected.context,
                })
              }
            >
              <Pencil size={15} /> Correct this
            </button>
            <button
              className="secondary-button"
              disabled={busy}
              type="button"
              onClick={() => void generateQuestion(selected.key)}
            >
              Ask me about this
            </button>
            <KeyLabelEditor
              key={selected.key}
              targetKey={selected.key}
              onChanged={onModelChanged}
            />
            <div className="evidence-heading">
              <span className="section-label">Why Soulmate thinks this</span>
              <b>{evidence.length} items</b>
            </div>
            <div className="evidence-list">
              {evidence.map((item) => (
                <article key={item.id}>
                  <div>
                    <strong>{item.source_type.replaceAll("_", " ")}</strong>
                    <span>{formatDate(item.created_at)}</span>
                  </div>
                  <p>
                    Value {String(item.value)} · strength{" "}
                    {percentage(item.strength)}
                  </p>
                  <button
                    className="icon-button danger"
                    aria-label="Delete evidence"
                    disabled={busy}
                    type="button"
                    onClick={() => void removeEvidence(item.id)}
                  >
                    <Trash2 size={15} />
                  </button>
                </article>
              ))}
            </div>
          </aside>
        </div>
      ) : null}
      {correction !== null ? (
        <div className="modal-backdrop">
          <form
            className="modal card"
            onSubmit={(event) => void submitCorrection(event)}
          >
            <button
              className="icon-button drawer-close"
              aria-label="Close"
              type="button"
              onClick={() => setCorrection(null)}
            >
              <X size={18} />
            </button>
            <p className="eyebrow">Direct evidence</p>
            <h2>{correction.key ? "Correct preference" : "Add preference"}</h2>
            <label>
              <span>Preference key</span>
              <input
                required
                placeholder="work.remote"
                value={correction.key}
                onChange={(event) =>
                  setCorrection({ ...correction, key: event.target.value })
                }
              />
            </label>
            <label>
              <span>Value: {correction.value.toFixed(2)}</span>
              <input
                min="-1"
                max="1"
                step="0.05"
                type="range"
                value={correction.value}
                onChange={(event) =>
                  setCorrection({
                    ...correction,
                    value: Number(event.target.value),
                  })
                }
              />
            </label>
            <div className="range-labels">
              <span>Strongly avoid</span>
              <span>Neutral</span>
              <span>Strongly prefer</span>
            </div>
            <button className="primary-button" disabled={busy} type="submit">
              Save correction
            </button>
          </form>
        </div>
      ) : null}
      {correction !== null ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={() => setCorrection(null)}
        >
          <form
            className="card correction-modal"
            onMouseDown={(event) => event.stopPropagation()}
            onSubmit={(event) => void submitCorrection(event)}
          >
            <button
              aria-label="Close"
              className="icon-button drawer-close"
              type="button"
              onClick={() => setCorrection(null)}
            >
              <X size={18} />
            </button>
            <p className="eyebrow">Direct evidence</p>
            <h2>{correction.key ? "Correct preference" : "Add preference"}</h2>
            <label>
              <span>Preference key</span>
              <input
                pattern="[a-z0-9_.-]+"
                placeholder="work.remote"
                required
                value={correction.key}
                onChange={(event) =>
                  setCorrection({ ...correction, key: event.target.value })
                }
              />
            </label>
            <label>
              <span>Preference strength: {correction.value.toFixed(2)}</span>
              <input
                max="1"
                min="-1"
                step="0.05"
                type="range"
                value={correction.value}
                onChange={(event) =>
                  setCorrection({
                    ...correction,
                    value: Number(event.target.value),
                  })
                }
              />
              <div className="range-labels">
                <span>Strongly avoid</span>
                <span>Neutral</span>
                <span>Strongly prefer</span>
              </div>
            </label>
            <label>
              <span>Context domain · optional</span>
              <input
                placeholder="career"
                value={
                  typeof correction.context.domain === "string"
                    ? correction.context.domain
                    : ""
                }
                onChange={(event) =>
                  setCorrection({
                    ...correction,
                    context: event.target.value
                      ? { domain: event.target.value }
                      : {},
                  })
                }
              />
            </label>
            <button className="primary-button" disabled={busy} type="submit">
              Save as correction evidence
            </button>
          </form>
        </div>
      ) : null}
    </section>
  );
}
