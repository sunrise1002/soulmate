import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LearningStatus as Status, MessageLearning } from "../types.ts";
import { LearningStatus, isLearningActive } from "./LearningStatus.tsx";

function learning(
  status: Status,
  overrides: Partial<MessageLearning> = {},
): MessageLearning {
  return {
    message_id: "message_1",
    status,
    attempts: 0,
    max_attempts: 8,
    ...overrides,
  };
}

afterEach(cleanup);

describe("LearningStatus", () => {
  it.each([
    ["pending", "Learning…"],
    ["learned", "Learned"],
    ["no_evidence", "Nothing new to learn"],
  ] as const)("labels %s without a retry action", (status, label) => {
    // Given: learning in a non-failed state
    // When: it is rendered
    render(
      <LearningStatus
        learning={learning(status)}
        retrying={false}
        onRetry={vi.fn()}
      />,
    );

    // Then: the label is shown and no retry is offered
    expect(screen.getByText(label)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the next attempt while the provider is busy", () => {
    // Given: learning that already failed once (boundary: attempt 1 of max)
    // When: it is rendered
    render(
      <LearningStatus
        learning={learning("retrying", { attempts: 1 })}
        retrying={false}
        onRetry={vi.fn()}
      />,
    );

    // Then: the owner sees which attempt comes next
    expect(
      screen.getByText("Model provider busy, retrying… (attempt 2 of 8)"),
    ).toBeTruthy();
  });

  it("offers a retry for failed learning", () => {
    // Given: failed learning
    const onRetry = vi.fn();
    render(
      <LearningStatus
        learning={learning("failed", { attempts: 8 })}
        retrying={false}
        onRetry={onRetry}
      />,
    );

    // When: the owner retries
    fireEvent.click(screen.getByRole("button", { name: /retry learning/i }));

    // Then: the message id is passed on
    expect(screen.getByText("Learning failed")).toBeTruthy();
    expect(onRetry).toHaveBeenCalledWith("message_1");
  });

  it("disables the retry while one is in flight", () => {
    // Given: a retry already in progress
    const onRetry = vi.fn();
    render(
      <LearningStatus
        learning={learning("failed")}
        retrying
        onRetry={onRetry}
      />,
    );

    // When: the owner clicks again
    const button = screen.getByRole("button", { name: /retry learning/i });
    fireEvent.click(button);

    // Then: no duplicate retry is sent
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(onRetry).not.toHaveBeenCalled();
  });
});

describe("isLearningActive", () => {
  it.each([
    ["pending", true],
    ["retrying", true],
    ["learned", false],
    ["no_evidence", false],
    ["failed", false],
  ] as const)("reports %s as active=%s", (status, expected) => {
    // Given / When / Then: only unfinished learning is active
    expect(isLearningActive(learning(status))).toBe(expected);
  });

  it("treats missing learning as inactive", () => {
    // Given: messages without a learning job (boundary: null / undefined)
    // When / Then: nothing is active
    expect(isLearningActive(null)).toBe(false);
    expect(isLearningActive(undefined)).toBe(false);
  });
});
