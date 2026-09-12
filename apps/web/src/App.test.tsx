import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App.tsx";

const fetchMock =
  vi.fn<(input: string, init?: RequestInit) => Promise<Response>>();

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function localStorageStub(initial: string | null): Storage {
  let value = initial;
  const stub: Storage = {
    getItem: () => value,
    setItem: (_key: string, next: string) => {
      value = next;
    },
    removeItem: () => {
      value = null;
    },
    clear: () => {
      value = null;
    },
    key: () => null,
    length: 0,
  };
  return stub;
}

describe("web client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });

  it("asks an unpaired device to connect before showing any personal data", async () => {
    // Given: a browser on another device with no credential
    fetchMock.mockResolvedValue(
      json({ detail: "A paired device credential is required." }, 401),
    );

    // When: the client loads
    render(
      <App
        origin="https://192.168.1.20:7433"
        storage={localStorageStub(null)}
      />,
    );

    // Then: only the pairing screen is offered
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Connect this device" }),
      ).not.toBeNull();
    });
    expect(screen.queryByRole("heading", { name: "Chat" })).toBeNull();
  });

  it("shows the product screens to a paired device", async () => {
    // Given: a browser holding a valid credential
    fetchMock.mockImplementation((input: string) => {
      if (input.endsWith("/v1/session")) {
        return Promise.resolve(
          json({
            actor: "device",
            device_id: "device_1",
            device_name: "Phone",
            service_id: "installation_1",
            profile_id: "profile_default",
          }),
        );
      }
      return Promise.resolve(json([]));
    });
    const stored = JSON.stringify({
      serviceId: "installation_1",
      deviceId: "device_1",
      deviceName: "Phone",
      credential: "device_1.secret",
    });

    // When: the client loads
    render(
      <App
        origin="https://192.168.1.20:7433"
        storage={localStorageStub(stored)}
      />,
    );

    // Then: the paired device sees the product navigation
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Chat" })).not.toBeNull();
    });
    expect(screen.getByText("Paired as Phone")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Decide" })).not.toBeNull();
    expect(screen.getByRole("button", { name: "My Model" })).not.toBeNull();
    expect(screen.getByRole("button", { name: "History" })).not.toBeNull();
  });
});
