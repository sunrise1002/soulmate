import { useEffect, useState } from "react";
import type { DecisionHistoryItem, SoulmateClient } from "@soulmate/sdk";

interface Props {
  client: SoulmateClient;
  onAuthError: (error: unknown) => void;
}

export function HistoryScreen({ client, onAuthError }: Props) {
  const [items, setItems] = useState<DecisionHistoryItem[]>([]);

  useEffect(() => {
    client.decisionHistory().then(setItems).catch(onAuthError);
  }, [client, onAuthError]);

  return (
    <section className="panel">
      <h2>History</h2>
      {items.length === 0 && (
        <p className="hint">No decisions have been recorded yet.</p>
      )}
      <ul className="history">
        {items.map((item) => (
          <li key={item.decision.id}>
            <span className="key">{item.decision.question}</span>
            <span className="hint">
              {item.decision.domain} · {item.decision.status}
            </span>
            {item.prediction !== null && (
              <span className="hint">
                Predicted {item.prediction.predicted_choice}
              </span>
            )}
            {item.resolution !== null && (
              <span className="hint">
                Chose{" "}
                {item.decision.options.find(
                  (option) => option.id === item.resolution?.chosen_option_id,
                )?.label ?? "another option"}
              </span>
            )}
            {item.advice !== null && (
              <span className="hint">
                Advised {item.advice.recommended_choice}
              </span>
            )}
            {item.outcome !== null && (
              <span className="hint">
                Satisfaction {(item.outcome.satisfaction * 100).toFixed(0)}%
                {item.outcome.regret ? " · regret" : ""}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
