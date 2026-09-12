import { useState } from "react";
import type {
  Decision,
  DecisionAdvice,
  DecisionPrediction,
  SoulmateClient,
} from "@soulmate/sdk";

interface Props {
  client: SoulmateClient;
  onAuthError: (error: unknown) => void;
}

const EMPTY_OPTIONS = ["", ""];

export function DecideScreen({ client, onAuthError }: Props) {
  const [domain, setDomain] = useState("general");
  const [question, setQuestion] = useState("");
  const [options, setOptions] = useState<string[]>(EMPTY_OPTIONS);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [prediction, setPrediction] = useState<DecisionPrediction | null>(null);
  const [advice, setAdvice] = useState<DecisionAdvice | null>(null);
  const [resolved, setResolved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const usable = options.filter((option) => option.trim().length > 0);

  const predict = async () => {
    setPending(true);
    setError(null);
    try {
      const created = await client.createDecision(
        domain.trim(),
        question.trim(),
        usable.map((option) => ({
          label: option.trim(),
          description: option.trim(),
        })),
      );
      setDecision(created);
      setPrediction(await client.predictDecision(created.id));
      setAdvice(await client.adviseDecision(created.id));
    } catch (caught) {
      onAuthError(caught);
      setError(
        caught instanceof Error ? caught.message : "The prediction failed.",
      );
    } finally {
      setPending(false);
    }
  };

  const resolve = async (optionId: string) => {
    if (decision === null) {
      return;
    }
    try {
      await client.resolveDecision(decision.id, optionId);
      setResolved(true);
    } catch (caught) {
      onAuthError(caught);
      setError(
        caught instanceof Error
          ? caught.message
          : "The choice could not be recorded.",
      );
    }
  };

  const recordOutcome = async (satisfaction: number, regret: boolean) => {
    if (decision === null) return;
    try {
      await client.recordOutcome(decision.id, satisfaction, regret);
      setDecision(null);
      setPrediction(null);
      setAdvice(null);
      setResolved(false);
      setQuestion("");
      setOptions(EMPTY_OPTIONS);
    } catch (caught) {
      onAuthError(caught);
      setError(
        caught instanceof Error
          ? caught.message
          : "The outcome could not be recorded.",
      );
    }
  };

  return (
    <section className="panel">
      <h2>Decide</h2>
      <label htmlFor="decision-domain">Area of life</label>
      <input
        id="decision-domain"
        value={domain}
        onChange={(event) => setDomain(event.target.value)}
      />
      <label htmlFor="decision-question">What are you deciding?</label>
      <input
        id="decision-question"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      {options.map((option, index) => (
        <input
          key={`option-${String(index)}`}
          aria-label={`Option ${String(index + 1)}`}
          value={option}
          onChange={(event) =>
            setOptions((current) =>
              current.map((item, position) =>
                position === index ? event.target.value : item,
              ),
            )
          }
        />
      ))}
      <button
        type="button"
        onClick={() => setOptions((current) => [...current, ""])}
      >
        Add option
      </button>
      <button
        type="button"
        disabled={pending || question.trim().length === 0 || usable.length < 2}
        onClick={() => void predict()}
      >
        {pending ? "Predicting…" : "Predict my choice"}
      </button>
      {prediction !== null && (
        <div className="prediction">
          <h3>{prediction.predicted_choice}</h3>
          <p className="hint">
            Confidence {(prediction.confidence * 100).toFixed(0)}%
          </p>
          <ul>
            {prediction.ranking.map((item) => (
              <li key={item.option_id}>
                {item.label} · {(item.probability * 100).toFixed(0)}%
                <button
                  disabled={resolved}
                  type="button"
                  onClick={() => void resolve(item.option_id)}
                >
                  I chose this
                </button>
              </li>
            ))}
          </ul>
          {advice !== null && (
            <div>
              <h3>Advise Me: {advice.recommended_choice}</h3>
              <p className="hint">
                Separate from Predict Me; informed by outcomes, goals, and
                constraints.
              </p>
            </div>
          )}
          {resolved && (
            <div>
              <p>How did the choice work out?</p>
              <button
                type="button"
                onClick={() => void recordOutcome(0.9, false)}
              >
                Satisfying
              </button>
              <button
                type="button"
                onClick={() => void recordOutcome(0.2, true)}
              >
                Disappointing / regret
              </button>
            </div>
          )}
        </div>
      )}
      {error !== null && <p role="alert">{error}</p>}
    </section>
  );
}
