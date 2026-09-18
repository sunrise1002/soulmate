import { RotateCcw } from "lucide-react";

import type { LearningStatus as Status, MessageLearning } from "../types.ts";

const LABELS: Record<Status, string> = {
  pending: "Learning…",
  retrying: "Model provider busy, retrying…",
  learned: "Learned",
  no_evidence: "Nothing new to learn",
  failed: "Learning failed",
};

export function isLearningActive(learning: MessageLearning | null | undefined) {
  return learning?.status === "pending" || learning?.status === "retrying";
}

interface LearningStatusProps {
  learning: MessageLearning;
  retrying: boolean;
  onRetry: (messageId: string) => void;
}

export function LearningStatus({
  learning,
  retrying,
  onRetry,
}: LearningStatusProps) {
  const attempt =
    learning.status === "retrying"
      ? ` (attempt ${String(learning.attempts + 1)} of ${String(learning.max_attempts)})`
      : "";
  return (
    <div className={`learning-status ${learning.status}`}>
      <span>
        {LABELS[learning.status]}
        {attempt}
      </span>
      {learning.status === "failed" ? (
        <button
          className="text-button"
          disabled={retrying}
          type="button"
          onClick={() => onRetry(learning.message_id)}
        >
          <RotateCcw size={12} /> Retry learning
        </button>
      ) : null}
    </div>
  );
}
