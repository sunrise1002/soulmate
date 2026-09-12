import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App.tsx";

const invoke = vi.fn<(command: string) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string) => invoke(command),
}));

describe("desktop navigation", () => {
  beforeEach(() => {
    invoke.mockImplementation((command: string) => {
      if (command === "daemon_status") {
        return Promise.resolve({
          state: "running",
          pid: 42,
          message: "The private local service is running on this device.",
        });
      }
      if (command === "api_request") {
        return Promise.resolve({ status: 200, body: [] });
      }
      return Promise.reject(new Error(`Unexpected command: ${command}`));
    });
  });

  it("opens each main product screen and reports local service health", async () => {
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("Private & local")).not.toBeNull(),
    );
    expect(screen.getByRole("heading", { name: "Chat" })).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Decide" }));
    expect(
      screen.getByRole("heading", { name: "What are you deciding?" }),
    ).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "My Model" }));
    expect(screen.getByRole("heading", { name: "My Model" })).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(
      screen.getByRole("heading", { name: "Decision History" }),
    ).not.toBeNull();
  });
});
