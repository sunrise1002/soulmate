import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Conversation, MessageLearning } from "../types.ts";
import { ChatScreen, LEARNING_POLL_MS } from "./ChatScreen.tsx";

interface ApiCall {
  method: string;
  path: string;
}

const invoke = vi.fn<(command: string, args?: unknown) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string, args?: unknown) => invoke(command, args),
}));

function conversation(learning: MessageLearning): Conversation {
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
        learning,
      },
      {
        id: "message_2",
        role: "assistant",
        content: "Noted.",
        provider_model: "gemini",
        created_at: "2026-09-18T16:46:40Z",
        learning: null,
      },
    ],
  };
}

function learning(
  status: MessageLearning["status"],
  attempts = 0,
): MessageLearning {
  return { message_id: "message_1", status, attempts, max_attempts: 8 };
}

function serve(
  conversations: () => Conversation[],
  retry: { status: number; body: unknown } = {
    status: 200,
    body: learning("pending"),
  },
): ApiCall[] {
  const calls: ApiCall[] = [];
  invoke.mockImplementation((command: string, args?: unknown) => {
    if (command !== "api_request") {
      return Promise.reject(new Error(`Unexpected command: ${command}`));
    }
    const request = (args as { request: ApiCall }).request;
    calls.push({ method: request.method, path: request.path });
    if (request.method === "GET") {
      return Promise.resolve({ status: 200, body: conversations() });
    }
    return Promise.resolve(retry);
  });
  return calls;
}

beforeEach(() => {
  invoke.mockReset();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ChatScreen learning", () => {
  it("retries failed learning and shows it pending again", async () => {
    // Given: a message whose learning failed
    const calls = serve(() => [conversation(learning("failed", 8))]);
    render(<ChatScreen onModelChanged={vi.fn()} />);
    const retry = await screen.findByRole("button", {
      name: /retry learning/i,
    });

    // When: the owner retries
    fireEvent.click(retry);

    // Then: the daemon is asked to requeue and the status becomes pending
    await screen.findByText("Learning…");
    expect(calls).toContainEqual({
      method: "POST",
      path: "/v1/messages/message_1/learning/retry",
    });
    expect(screen.queryByText("Learning failed")).toBeNull();
  });

  it("shows the daemon error when a retry is rejected", async () => {
    // Given: a retry the daemon rejects
    serve(() => [conversation(learning("failed", 8))], {
      status: 409,
      body: { detail: "Only failed learning can be retried." },
    });
    render(<ChatScreen onModelChanged={vi.fn()} />);

    // When: the owner retries
    fireEvent.click(
      await screen.findByRole("button", { name: /retry learning/i }),
    );

    // Then: the error is shown and the failed status stays
    await screen.findByText("Only failed learning can be retried.");
    expect(screen.getByText("Learning failed")).toBeTruthy();
  });

  it("polls while learning is pending and reports a changed model", async () => {
    // Given: learning that is pending and later succeeds
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current = learning("pending");
    const calls = serve(() => [conversation(current)]);
    const onModelChanged = vi.fn();
    render(<ChatScreen onModelChanged={onModelChanged} />);
    await screen.findByText("Learning…");

    // When: the background job succeeds and the poll interval passes
    current = learning("learned", 1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LEARNING_POLL_MS);
    });

    // Then: the new status is shown and the shell refreshes the model
    await screen.findByText("Learned");
    expect(calls.filter((call) => call.method === "GET").length).toBe(2);
    await waitFor(() => expect(onModelChanged).toHaveBeenCalledTimes(1));
  });

  it("does not poll when no learning is in progress", async () => {
    // Given: learning that already failed
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = serve(() => [conversation(learning("failed", 8))]);
    render(<ChatScreen onModelChanged={vi.fn()} />);
    await screen.findByText("Learning failed");

    // When: several poll intervals pass
    await act(async () => {
      await vi.advanceTimersByTimeAsync(LEARNING_POLL_MS * 3);
    });

    // Then: conversations were fetched only once
    expect(calls.filter((call) => call.method === "GET").length).toBe(1);
  });
});
