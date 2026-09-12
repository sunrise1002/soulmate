import { CheckCircle2, Clock3, Gauge, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "../components/EmptyState.tsx";
import { apiRequest } from "../runtime.ts";
import type { DecisionHistoryItem } from "../types.ts";
import { formatDate, percentage } from "../utils.ts";

export function HistoryScreen() {
  const [items, setItems] = useState<DecisionHistoryItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await apiRequest<DecisionHistoryItem[]>("GET", "/v1/decisions"));
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Decision history is unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load]);

  async function deleteOutcome(decisionId: string) {
    try {
      await apiRequest("DELETE", `/v1/decisions/${decisionId}/outcome`);
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The outcome could not be deleted.",
      );
    }
  }

  return (
    <section className="screen history-screen">
      <header className="screen-header">
        <div>
          <p className="eyebrow">Choices over time</p>
          <h1>Decision History</h1>
          <p>
            Predictions and actual choices stay together, so your model can keep
            learning.
          </p>
        </div>
      </header>
      {error ? <div className="inline-error">{error}</div> : null}
      {items.length ? (
        <div className="history-timeline">
          {items.map((item) => {
            const chosen = item.decision.options.find(
              (option) => option.id === item.resolution?.chosen_option_id,
            );
            return (
              <article className="history-item" key={item.decision.id}>
                <div className="timeline-marker">
                  {item.resolution !== null ? (
                    <CheckCircle2 size={18} />
                  ) : (
                    <Clock3 size={18} />
                  )}
                </div>
                <div className="card history-card">
                  <div className="history-meta">
                    <span>{item.decision.domain}</span>
                    <time>{formatDate(item.decision.created_at)}</time>
                  </div>
                  <h2>{item.decision.question}</h2>
                  <div className="history-outcomes">
                    <div>
                      <Sparkles size={16} />
                      <span>Predicted</span>
                      <strong>
                        {item.prediction?.predicted_choice ?? "Not predicted"}
                      </strong>
                    </div>
                    <div>
                      <CheckCircle2 size={16} />
                      <span>Chose</span>
                      <strong>{chosen?.label ?? "Still open"}</strong>
                    </div>
                    <div>
                      <Gauge size={16} />
                      <span>Confidence</span>
                      <strong>
                        {item.prediction === null
                          ? "—"
                          : percentage(item.prediction.confidence)}
                      </strong>
                    </div>
                    <div>
                      <Sparkles size={16} />
                      <span>Advised</span>
                      <strong>
                        {item.advice?.recommended_choice ?? "Not advised"}
                      </strong>
                    </div>
                  </div>
                  {item.outcome !== null ? (
                    <div>
                      <p className="muted">
                        Outcome: {percentage(item.outcome.satisfaction)}{" "}
                        satisfaction
                        {item.outcome.regret ? " · regret reported" : ""}
                      </p>
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => void deleteOutcome(item.decision.id)}
                      >
                        <Trash2 size={14} /> Delete outcome
                      </button>
                    </div>
                  ) : null}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={Clock3}
          title="No decisions yet"
          description="Use Decide to compare options. Predictions and your eventual choices will appear here."
        />
      )}
    </section>
  );
}
