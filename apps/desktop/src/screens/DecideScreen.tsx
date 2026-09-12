import { ArrowLeft, Check, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import type { SyntheticEvent } from "react";

import { apiRequest } from "../runtime.ts";
import type {
  Decision,
  DecisionAdvice,
  DecisionOutcome,
  DecisionPrediction,
  Resolution,
} from "../types.ts";
import { percentage } from "../utils.ts";

interface DraftOption {
  key: string;
  label: string;
  description: string;
}

interface DecideScreenProps {
  onDecisionSaved: () => void;
}

function newOption(index: number): DraftOption {
  return {
    key: crypto.randomUUID(),
    label: `Option ${String(index + 1)}`,
    description: "",
  };
}

export function DecideScreen({ onDecisionSaved }: DecideScreenProps) {
  const [question, setQuestion] = useState("");
  const [domain, setDomain] = useState("general");
  const [options, setOptions] = useState<DraftOption[]>([
    newOption(0),
    newOption(1),
  ]);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [prediction, setPrediction] = useState<DecisionPrediction | null>(null);
  const [advice, setAdvice] = useState<DecisionAdvice | null>(null);
  const [resolution, setResolution] = useState<Resolution | null>(null);
  const [outcome, setOutcome] = useState<DecisionOutcome | null>(null);
  const [satisfaction, setSatisfaction] = useState(0.5);
  const [regret, setRegret] = useState(false);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setQuestion("");
    setDomain("general");
    setOptions([newOption(0), newOption(1)]);
    setDecision(null);
    setPrediction(null);
    setAdvice(null);
    setResolution(null);
    setOutcome(null);
    setSatisfaction(0.5);
    setRegret(false);
    setNotes("");
    setError(null);
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiRequest<Decision>("POST", "/v1/decisions", {
        domain,
        question,
        context: {},
        options: options.map((item) => ({
          label: item.label,
          description: item.description,
          features: {},
        })),
      });
      const result = await apiRequest<DecisionPrediction>(
        "POST",
        `/v1/decisions/${created.id}/predict`,
      );
      const recommendation = await apiRequest<DecisionAdvice>(
        "POST",
        `/v1/decisions/${created.id}/advise`,
      );
      setDecision(created);
      setPrediction(result);
      setAdvice(recommendation);
      onDecisionSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The decision could not be predicted.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function recordOutcome(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (decision === null || resolution === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiRequest<DecisionOutcome>(
        "POST",
        `/v1/decisions/${decision.id}/outcome`,
        {
          satisfaction,
          regret,
          notes: notes.trim() || null,
        },
      );
      setOutcome(result);
      onDecisionSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The outcome could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function resolve(optionId: string) {
    if (decision === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiRequest<
        Resolution & { snapshot_version: number }
      >("POST", `/v1/decisions/${decision.id}/resolve`, {
        chosen_option_id: optionId,
      });
      setResolution(result);
      setDecision({ ...decision, status: "resolved" });
      onDecisionSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The choice could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (decision !== null && prediction !== null) {
    return (
      <section className="screen decision-result-screen">
        <header className="screen-header">
          <button className="text-button" type="button" onClick={reset}>
            <ArrowLeft size={16} /> New decision
          </button>
        </header>
        <div className="result-hero">
          <div className="result-orbit">
            <Sparkles size={28} />
          </div>
          <p className="eyebrow">Predict Me</p>
          <h1>I think you would choose {prediction.predicted_choice}.</h1>
          <p>
            {percentage(prediction.ranking[0]?.probability ?? 0)} likelihood ·{" "}
            {percentage(prediction.confidence)} confidence
          </p>
        </div>
        <div className="result-grid">
          <article className="card ranking-card">
            <div className="card-heading">
              <div>
                <span className="section-label">Your likely ranking</span>
                <h2>{decision.question}</h2>
              </div>
            </div>
            {prediction.ranking.map((item, index) => (
              <div className="ranking-row" key={item.option_id}>
                <span className="rank-number">{index + 1}</span>
                <div>
                  <strong>{item.label}</strong>
                  <div className="probability-track">
                    <span
                      style={{ width: `${String(item.probability * 100)}%` }}
                    />
                  </div>
                </div>
                <b>{percentage(item.probability)}</b>
              </div>
            ))}
          </article>
          <article className="card factors-card">
            <span className="section-label">What shaped this</span>
            <h2>Important factors</h2>
            <div className="tag-list">
              {prediction.important_factors.length ? (
                prediction.important_factors.map((factor) => (
                  <span key={factor}>{factor}</span>
                ))
              ) : (
                <p>More choices will make the model's reasoning richer.</p>
              )}
            </div>
            <p className="muted">
              Model snapshot {prediction.model_snapshot_version}
            </p>
          </article>
          {advice !== null ? (
            <article className="card factors-card">
              <span className="section-label">Advise Me</span>
              <h2>Consider {advice.recommended_choice}</h2>
              <p>
                Predict Me remains {advice.predicted_choice}; this
                recommendation separately weighs your reported outcomes, goals,
                and constraints.
              </p>
              <div className="tag-list">
                {advice.rationale.map((reason) => (
                  <span key={reason}>{reason}</span>
                ))}
              </div>
            </article>
          ) : null}
        </div>
        <article className="card resolve-card">
          <div>
            <span className="section-label">Teach your model</span>
            <h2>What did you actually choose?</h2>
          </div>
          <div className="resolve-actions">
            {decision.options.map((option) => (
              <button
                className={
                  resolution?.chosen_option_id === option.id
                    ? "choice selected"
                    : "choice"
                }
                disabled={resolution !== null || busy}
                key={option.id}
                type="button"
                onClick={() => void resolve(option.id)}
              >
                {resolution?.chosen_option_id === option.id ? (
                  <Check size={16} />
                ) : null}
                {option.label}
              </button>
            ))}
          </div>
        </article>
        {resolution !== null ? (
          <form
            className="card resolve-card"
            onSubmit={(event) => void recordOutcome(event)}
          >
            <div>
              <span className="section-label">Outcome</span>
              <h2>How did this choice work out?</h2>
              {outcome !== null ? (
                <p>
                  Outcome saved. It will inform future advice, not Predict Me.
                </p>
              ) : null}
            </div>
            {outcome === null ? (
              <div className="resolve-actions">
                <label>
                  Satisfaction {percentage(satisfaction)}
                  <input
                    aria-label="Satisfaction"
                    max="1"
                    min="0"
                    step="0.05"
                    type="range"
                    value={satisfaction}
                    onChange={(event) =>
                      setSatisfaction(Number(event.target.value))
                    }
                  />
                </label>
                <label>
                  <input
                    checked={regret}
                    type="checkbox"
                    onChange={(event) => setRegret(event.target.checked)}
                  />{" "}
                  I regret this choice
                </label>
                <textarea
                  maxLength={10000}
                  placeholder="Optional notes about what happened"
                  rows={2}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                />
                <button
                  className="secondary-button"
                  disabled={busy}
                  type="submit"
                >
                  Save outcome
                </button>
              </div>
            ) : null}
          </form>
        ) : null}
        {error ? <div className="inline-error">{error}</div> : null}
      </section>
    );
  }

  return (
    <section className="screen decide-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">Predict Me</p>
          <h1>What are you deciding?</h1>
          <p>
            Describe the options. Soulmate will rank what you would most likely
            choose.
          </p>
        </div>
      </header>
      <form className="decision-form" onSubmit={(event) => void submit(event)}>
        <article className="card form-card">
          <label>
            <span>The decision</span>
            <textarea
              maxLength={10000}
              placeholder="Which role should I take?"
              required
              rows={2}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </label>
          <label>
            <span>Life area</span>
            <select
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
            >
              <option value="general">General</option>
              <option value="career">Career</option>
              <option value="travel">Travel</option>
              <option value="finance">Finance</option>
              <option value="health">Health</option>
              <option value="relationships">Relationships</option>
              <option value="software">Technology</option>
            </select>
          </label>
        </article>
        <div className="options-heading">
          <div>
            <span className="section-label">Options</span>
            <h2>Give each possibility a little context</h2>
          </div>
          <button
            className="secondary-button"
            disabled={options.length >= 20}
            type="button"
            onClick={() =>
              setOptions((items) => [...items, newOption(items.length)])
            }
          >
            <Plus size={16} /> Add option
          </button>
        </div>
        <div className="option-grid">
          {options.map((option, index) => (
            <article className="card option-card" key={option.key}>
              <div className="option-number">
                {String(index + 1).padStart(2, "0")}
              </div>
              <label>
                <span>Name</span>
                <input
                  maxLength={200}
                  required
                  value={option.label}
                  onChange={(event) =>
                    setOptions((items) =>
                      items.map((item) =>
                        item.key === option.key
                          ? { ...item, label: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
              </label>
              <label>
                <span>What is it like?</span>
                <textarea
                  maxLength={10000}
                  placeholder="Cost, pace, trade-offs, what attracts you…"
                  required
                  rows={4}
                  value={option.description}
                  onChange={(event) =>
                    setOptions((items) =>
                      items.map((item) =>
                        item.key === option.key
                          ? { ...item, description: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
              </label>
              {options.length > 2 ? (
                <button
                  aria-label={`Remove ${option.label}`}
                  className="icon-button remove-option"
                  type="button"
                  onClick={() =>
                    setOptions((items) =>
                      items.filter((item) => item.key !== option.key),
                    )
                  }
                >
                  <Trash2 size={16} />
                </button>
              ) : null}
            </article>
          ))}
        </div>
        {error ? <div className="inline-error">{error}</div> : null}
        <button
          className="primary-button predict-button"
          disabled={busy}
          type="submit"
        >
          <Sparkles size={17} />{" "}
          {busy ? "Reading the trade-offs…" : "Predict my choice"}
        </button>
      </form>
    </section>
  );
}
