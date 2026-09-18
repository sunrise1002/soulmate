import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SoulmateClient,
  type Conversation,
  type DecisionPrediction,
  type MessageLearning,
} from "@soulmate/sdk";

import { ChatScreen, LEARNING_POLL_MS } from "./ChatScreen.tsx";
import { DecideScreen, NO_PREFERENCE_NOTICE } from "./DecideScreen.tsx";

interface Call {
  method: string;
  url: string;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function learning(
  status: MessageLearning["status"],
  attempts = 0,
): MessageLearning {
  return { message_id: "message_1", status, attempts, max_attempts: 8 };
}

function conversation(state: MessageLearning): Conversation {
  return {
    id: "conversation_1",
    created_at: "2026-09-18T16:46:39Z",
    updated_at: "2026-09-18T16:46:39Z",
    messages: [
      {
        id: "message_1",
        role: "user",
        content: "I like dark theme over light theme",
        provider_model: null,
        created_at: "2026-09-18T16:46:39Z",
        learning: state,
      },
    ],
  };
}

function clientFor(routes: (method: string, url: string) => Response): {
  client: SoulmateClient;
  calls: Call[];
} {
  const calls: Call[] = [];
  const client = new SoulmateClient({
    baseUrl: "http://127.0.0.1:7432",
    fetch: (url, init) => {
      const method = init?.method ?? "GET";
      calls.push({ method, url });
      return Promise.resolve(routes(method, url));
    },
  });
  return { client, calls };
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("web chat learning", () => {
  it("retries failed learning and shows it pending", async () => {
    // Given: a message whose learning failed
    const { client, calls } = clientFor((method) =>
      method === "GET"
        ? json([conversation(learning("failed", 8))])
        : json(learning("pending")),
    );
    render(<ChatScreen client={client} onAuthError={vi.fn()} />);

    // When: the owner retries
    fireEvent.click(
      await screen.findByRole("button", { name: "Retry learning" }),
    );

    // Then: the daemon requeues and the message shows pending learning
    await screen.findByText("Learning…");
    expect(calls).toContainEqual({
      method: "POST",
      url: "http://127.0.0.1:7432/v1/messages/message_1/learning/retry",
    });
  });

  it("shows an alert when the retry is rejected", async () => {
    // Given: a daemon that rejects the retry
    const { client } = clientFor((method) =>
      method === "GET"
        ? json([conversation(learning("failed", 8))])
        : json({ detail: "Only failed learning can be retried." }, 409),
    );
    const onAuthError = vi.fn();
    render(<ChatScreen client={client} onAuthError={onAuthError} />);

    // When: the owner retries
    fireEvent.click(
      await screen.findByRole("button", { name: "Retry learning" }),
    );

    // Then: the daemon detail is shown and failure remains
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Only failed learning can be retried.",
    );
    expect(screen.getByText("Learning failed")).toBeTruthy();
    expect(onAuthError).toHaveBeenCalledTimes(1);
  });

  it("polls pending learning until it finishes", async () => {
    // Given: pending learning that later succeeds
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current = learning("retrying", 1);
    const { client, calls } = clientFor(() => json([conversation(current)]));
    render(<ChatScreen client={client} onAuthError={vi.fn()} />);
    await screen.findByText("Model provider busy, retrying…");

    // When: learning succeeds and one poll interval passes
    current = learning("learned", 2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LEARNING_POLL_MS);
    });

    // Then: the new status is shown after exactly one extra fetch
    await screen.findByText("Learned");
    expect(calls.filter((call) => call.method === "GET").length).toBe(2);
  });
});

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

async function predictWith(importantFactors: string[]) {
  const { client } = clientFor((_method, url) => {
    if (url.endsWith("/predict")) return json(prediction(importantFactors));
    if (url.endsWith("/advise")) return json({ recommended_choice: "Dark" });
    return json({ id: "decision_1", options: [] });
  });
  render(<DecideScreen client={client} onAuthError={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("What are you deciding?"), {
    target: { value: "Which theme should I choose" },
  });
  fireEvent.change(screen.getByLabelText("Option 1"), {
    target: { value: "Dark theme" },
  });
  fireEvent.change(screen.getByLabelText("Option 2"), {
    target: { value: "Light theme" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Predict my choice" }));
  await screen.findByRole("heading", { name: "Dark theme" });
}

describe("web decide notice", () => {
  it("warns when no learned preference applies", async () => {
    // Given / When: a prediction without important factors (boundary: empty)
    await predictWith([]);

    // Then: the chance warning is shown
    expect(screen.getByRole("status").textContent).toBe(NO_PREFERENCE_NOTICE);
  });

  it("omits the warning when preferences shaped the prediction", async () => {
    // Given / When: a prediction driven by a learned preference
    await predictWith(["ui.theme.dark"]);

    // Then: no warning is shown
    expect(screen.queryByText(NO_PREFERENCE_NOTICE)).toBeNull();
  });
});
