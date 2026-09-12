import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App.tsx";

const invoke = vi.fn<(command: string) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string) => invoke(command),
}));

describe("desktop navigation", () => {
  afterEach(cleanup);

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
      if (command === "get_desktop_settings") {
        return Promise.resolve({
          privacyMode: "strict_local",
          provider: "ollama",
          ollamaBaseUrl: "http://127.0.0.1:11434",
          ollamaModel: "model",
          openaiBaseUrl: "http://127.0.0.1:8000/v1",
          openaiModel: "",
          hasApiKey: false,
          lanEnabled: false,
        });
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
    expect(
      screen.getByRole("heading", { name: "Clarify uncertain trade-offs" }),
    ).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(
      screen.getByRole("heading", { name: "Decision History" }),
    ).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Devices" }));
    expect(screen.getByRole("heading", { name: "Devices" })).not.toBeNull();
    await waitFor(() =>
      expect(
        screen.getByLabelText("Enable access from other devices"),
      ).not.toBeNull(),
    );

    fireEvent.click(screen.getByRole("button", { name: "External Agents" }));
    expect(
      screen.getByRole("heading", { name: "External Agents" }),
    ).not.toBeNull();
  });

  it("keeps access from other devices off until the owner enables it", async () => {
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText("Private & local")).not.toBeNull(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Devices" }));

    const toggle = await screen.findByLabelText(
      "Enable access from other devices",
    );
    expect((toggle as HTMLInputElement).checked).toBe(false);
    expect(
      screen
        .getByRole("button", { name: /Create pairing code/ })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
});
