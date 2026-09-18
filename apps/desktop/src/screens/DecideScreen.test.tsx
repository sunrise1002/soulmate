import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionPrediction } from "../types.ts";
import { DecideScreen, NO_PREFERENCE_NOTICE } from "./DecideScreen.tsx";

const invoke = vi.fn<(command: string, args?: unknown) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string, args?: unknown) => invoke(command, args),
}));

const decision = {
  id: "decision_1",
  domain: "general",
  question: "Which theme should I choose",
  context: {},
  status: "open",
  options: [
    { id: "option_dark", label: "Dark theme", description: "Dark" },
    { id: "option_light", label: "Light theme", description: "Light" },
  ],
  created_at: "2026-09-18T16:48:35Z",
};

function prediction(importantFactors: string[]): DecisionPrediction {
  return {
    id: "prediction_1",
    decision_id: "decision_1",
    mode: "predict_me",
    predicted_option_id: "option_dark",
    predicted_choice: "Dark theme",
    ranking: [
      {
        option_id: "option_dark",
        label: "Dark theme",
        probability: 0.5,
        utility: 0,
      },
      {
        option_id: "option_light",
        label: "Light theme",
        probability: 0.5,
        utility: 0,
      },
    ],
    confidence: 0.5,
    important_factors: importantFactors,
    uncertain_factors: [],
    supporting_evidence: [],
    similar_decision_ids: [],
    model_snapshot_version: 1,
    algorithm_version: "test",
    created_at: "2026-09-18T16:48:35Z",
  };
}

function serve(predicted: DecisionPrediction) {
  invoke.mockImplementation((_command: string, args?: unknown) => {
    const { path } = (args as { request: { path: string } }).request;
    if (path.endsWith("/predict")) {
      return Promise.resolve({ status: 200, body: predicted });
    }
    if (path.endsWith("/advise")) {
      return Promise.resolve({
        status: 200,
        body: {
          recommended_choice: "Dark theme",
          predicted_choice: "Dark theme",
          rationale: [],
        },
      });
    }
    return Promise.resolve({ status: 200, body: decision });
  });
}

async function predict() {
  const { container } = render(<DecideScreen onDecisionSaved={vi.fn()} />);
  fireEvent.submit(container.querySelector("form") as HTMLFormElement);
  await screen.findByText("I think you would choose Dark theme.");
}

beforeEach(() => {
  invoke.mockReset();
});

afterEach(cleanup);

describe("DecideScreen prediction notice", () => {
  it("warns when no learned preference shaped the prediction", async () => {
    // Given: a prediction without important factors (boundary: empty list)
    serve(prediction([]));

    // When: the decision is predicted
    await predict();

    // Then: the owner is told the ranking is close to chance
    expect(screen.getByRole("status").textContent).toBe(NO_PREFERENCE_NOTICE);
  });

  it("shows no warning when learned preferences shaped the prediction", async () => {
    // Given: a prediction driven by one learned preference
    serve(prediction(["ui.theme.dark"]));

    // When: the decision is predicted
    await predict();

    // Then: no chance warning is shown
    expect(screen.queryByText(NO_PREFERENCE_NOTICE)).toBeNull();
    expect(screen.getByText("ui.theme.dark")).toBeTruthy();
  });
});
