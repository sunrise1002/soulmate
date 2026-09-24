import { Check, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { SyntheticEvent } from "react";

import { apiRequest } from "../runtime.ts";
import type { DecisionIoObservation } from "../types.ts";
import { formatDate } from "../utils.ts";

interface DecisionIoObservationsPanelProps {
  revision: number;
  onChanged: () => void;
}

const kindLabels: Record<DecisionIoObservation["kind"], string> = {
  resolution: "Reported choice",
  technical: "Technical result",
  user_behavior: "What you did with a proposal",
  owner_reported: "Reported satisfaction",
};

function describe(item: DecisionIoObservation): string {
  if (item.kind === "technical") return item.technical_status ?? "unknown";
  if (item.kind === "user_behavior") return item.disposition ?? "unknown";
  if (item.kind === "owner_reported" && item.satisfaction !== null) {
    const percent = Math.round(item.satisfaction * 100).toString();
    return `${percent}% satisfied${item.regret ? ", with regret" : ""}`;
  }
  return item.disposition ?? "reported";
}

/**
 * Observations are reports from agents, not confirmed facts. Only the owner's
 * own confirmation turns a satisfaction report into wellbeing.
 */
export function DecisionIoObservationsPanel({
  revision,
  onChanged,
}: DecisionIoObservationsPanelProps) {
  const [items, setItems] = useState<DecisionIoObservation[]>([]);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [satisfaction, setSatisfaction] = useState(0.7);
  const [regret, setRegret] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(
        await apiRequest<DecisionIoObservation[]>(
          "GET",
          "/v1/decision-io/observations",
        ),
      );
      setError(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Observations are unavailable.",
      );
    }
  }, []);

  useEffect(() => void load(), [load, revision]);

  async function change(path: string, body?: unknown) {
    if (busy) return;
    setBusy(true);
    try {
      await apiRequest("POST", path, body);
      setConfirming(null);
      await load();
      onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The observation could not be changed.",
      );
    } finally {
      setBusy(false);
    }
  }

  function confirm(event: SyntheticEvent<HTMLFormElement>, id: string) {
    event.preventDefault();
    void change(
      `/v1/decision-io/observations/${encodeURIComponent(id)}/confirm`,
      {
        satisfaction,
        regret,
        notes: null,
      },
    );
  }

  const open = (item: DecisionIoObservation) =>
    item.status === "pending" || item.status === "unmatched";

  return (
    <article className="card audit-card" aria-label="Observations">
      <p className="section-label">Decision I/O</p>
      <h2>Observations</h2>
      <p className="muted">
        Agents report what they saw. Nothing here changes your model or your
        wellbeing history until you confirm it.
      </p>
      {error ? <div className="inline-error">{error}</div> : null}
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <span>
                <strong>{kindLabels[item.kind]}</strong> · {describe(item)} ·{" "}
                <em>
                  {item.status === "confirmed"
                    ? "confirmed"
                    : `observed (${item.status})`}
                </em>
                <small> {formatDate(item.created_at)}</small>
              </span>
              {open(item) ? (
                <span className="approval-actions">
                  {item.kind === "owner_reported" && item.decision_id ? (
                    <button
                      className="text-button"
                      disabled={busy}
                      type="button"
                      onClick={() => setConfirming(item.id)}
                    >
                      <Check size={14} /> Confirm
                    </button>
                  ) : null}
                  <button
                    className="text-button danger"
                    disabled={busy}
                    type="button"
                    onClick={() =>
                      void change(
                        `/v1/decision-io/observations/${encodeURIComponent(item.id)}/reject`,
                      )
                    }
                  >
                    <X size={14} /> Reject
                  </button>
                </span>
              ) : null}
              {confirming === item.id ? (
                <form onSubmit={(event) => confirm(event, item.id)}>
                  <label>
                    Your satisfaction ({Math.round(satisfaction * 100)}%)
                    <input
                      max={1}
                      min={0}
                      step={0.05}
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
                    />
                    I regret this decision
                  </label>
                  <button
                    className="primary-button"
                    disabled={busy}
                    type="submit"
                  >
                    Save my outcome
                  </button>
                </form>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No observations have been reported.</p>
      )}
    </article>
  );
}
