import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App.tsx";

const invoke = vi.fn<(command: string, args?: unknown) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string, args?: unknown) => invoke(command, args),
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
      if (command === "get_remote_backup_settings") {
        return Promise.resolve({
          enabled: false,
          automaticDaily: false,
          intervalHours: 24,
          endpointUrl: "",
          region: "auto",
          bucket: "",
          prefix: "soulmate",
          hasPassphrase: false,
          hasAccessKeyId: false,
          hasSecretAccessKey: false,
        });
      }
      if (command === "daemon_logs") return Promise.resolve([]);
      if (command === "save_remote_backup_settings") {
        return Promise.resolve({
          enabled: true,
          automaticDaily: true,
          intervalHours: 24,
          endpointUrl: "https://account.r2.cloudflarestorage.com",
          region: "auto",
          bucket: "soulmate-backups",
          prefix: "soulmate",
          hasPassphrase: true,
          hasAccessKeyId: true,
          hasSecretAccessKey: true,
        });
      }
      if (command === "daemon_restart") {
        return Promise.resolve({
          state: "starting",
          pid: 43,
          message: "The private local service is starting.",
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
    expect(
      screen.getByRole("heading", { name: "Set an action policy" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("heading", { name: "Delegation requests" }),
    ).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Connections" }));
    expect(screen.getByRole("heading", { name: "Connections" })).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Data & Privacy" }));
    expect(
      screen.getByRole("heading", { name: "Data & Privacy" }),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "Back up now" })).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("heading", { name: "Settings" })).not.toBeNull();
    await waitFor(() =>
      expect(
        screen.getByLabelText("Enable encrypted remote backup"),
      ).not.toBeNull(),
    );
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

  it("configures encrypted remote backup without environment variables", async () => {
    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Private & local")).not.toBeNull(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const enabled = await screen.findByLabelText(
      "Enable encrypted remote backup",
    );
    fireEvent.click(enabled);
    fireEvent.change(screen.getByLabelText("S3 endpoint URL"), {
      target: { value: "https://account.r2.cloudflarestorage.com" },
    });
    fireEvent.change(screen.getByLabelText("Private bucket name"), {
      target: { value: "soulmate-backups" },
    });
    fireEvent.change(screen.getByLabelText(/^Access key ID/), {
      target: { value: "access-key" },
    });
    fireEvent.change(screen.getByLabelText(/^Secret access key/), {
      target: { value: "secret-key" },
    });
    fireEvent.change(screen.getByLabelText(/^Encryption passphrase/), {
      target: { value: "long-safe-passphrase" },
    });
    fireEvent.click(
      screen.getByLabelText("Back up automatically while Soulmate is running"),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Save backup settings and restart",
      }),
    );

    await waitFor(() =>
      expect(
        invoke.mock.calls.some(
          ([command, args]) =>
            command === "save_remote_backup_settings" &&
            (args as { settings?: { enabled?: boolean } }).settings?.enabled ===
              true,
        ),
      ).toBe(true),
    );
  });
});
