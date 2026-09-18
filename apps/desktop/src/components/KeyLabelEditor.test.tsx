import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KeyLabel } from "../types.ts";
import { KeyLabelEditor } from "./KeyLabelEditor.tsx";

interface ApiCall {
  method: string;
  path: string;
  body: unknown;
}

const invoke = vi.fn<(command: string, args?: unknown) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string, args?: unknown) => invoke(command, args),
}));

function label(overrides: Partial<KeyLabel> = {}): KeyLabel {
  return {
    target_type: "preference",
    key: "ui.theme.dark",
    label: "giao diện tối",
    aliases: ["nền tối"],
    source: "owner",
    created_at: "2026-09-18T00:00:00Z",
    updated_at: "2026-09-18T00:00:00Z",
    ...overrides,
  };
}

function serve(
  labels: KeyLabel[],
  write: { status: number; body: unknown } = { status: 200, body: label() },
): ApiCall[] {
  const calls: ApiCall[] = [];
  invoke.mockImplementation((command: string, args?: unknown) => {
    if (command !== "api_request") {
      return Promise.reject(new Error(`Unexpected command: ${command}`));
    }
    const request = (args as { request: ApiCall }).request;
    calls.push(request);
    if (request.method === "GET") {
      return Promise.resolve({ status: 200, body: { labels } });
    }
    return Promise.resolve(write);
  });
  return calls;
}

function writes(calls: ApiCall[]): ApiCall[] {
  return calls.filter((call) => call.method === "POST");
}

describe("key label editor", () => {
  afterEach(cleanup);

  beforeEach(() => {
    invoke.mockReset();
  });

  it("loads the stored name and aliases of the selected key", async () => {
    // Given: a key the owner already named
    serve([label(), label({ key: "work.remote", label: "làm từ xa" })]);

    // When: the editor opens for that key
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={vi.fn()} />);

    // Then: only its own name is shown, not another key's
    await waitFor(() =>
      expect(screen.getByDisplayValue("giao diện tối")).not.toBeNull(),
    );
    expect(screen.getByDisplayValue("nền tối")).not.toBeNull();
    expect(screen.queryByDisplayValue("làm từ xa")).toBeNull();
  });

  it("saves a name and its comma separated wordings", async () => {
    // Given: a key with no name yet
    const calls = serve([]);
    const onChanged = vi.fn();

    // When: the owner writes a name and two other wordings
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={onChanged} />);
    await screen.findByText("Your name for this key");
    fireEvent.change(screen.getByPlaceholderText("giao diện tối"), {
      target: { value: "  giao diện tối  " },
    });
    fireEvent.change(screen.getByPlaceholderText("nền tối, dark mode"), {
      target: { value: "nền tối , , dark mode" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: the wording is trimmed and empty entries never reach the daemon
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(writes(calls)).toEqual([
      {
        method: "POST",
        path: "/v1/key-labels",
        body: {
          target_type: "preference",
          key: "ui.theme.dark",
          label: "giao diện tối",
          aliases: ["nền tối", "dark mode"],
        },
      },
    ]);
  });

  it("sends no more than five wordings", async () => {
    // Given: a key with no name yet
    const calls = serve([]);

    // When: the owner writes six wordings
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={vi.fn()} />);
    await screen.findByText("Your name for this key");
    fireEvent.change(screen.getByPlaceholderText("nền tối, dark mode"), {
      target: { value: "a, b, c, d, e, f" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: the request stays inside the limit the daemon enforces
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect((writes(calls)[0]?.body as { aliases: string[] }).aliases).toEqual([
      "a",
      "b",
      "c",
      "d",
      "e",
    ]);
  });

  it("sends an empty name as null so only aliases remain", async () => {
    // Given: a named key
    const calls = serve([label()]);

    // When: the owner clears the name but keeps a wording
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByDisplayValue("giao diện tối")).not.toBeNull(),
    );
    fireEvent.change(screen.getByPlaceholderText("giao diện tối"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: an absent name is explicit rather than an empty string
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(
      (writes(calls)[0]?.body as { label: string | null }).label,
    ).toBeNull();
  });

  it("removes a stored name so extraction may propose one again", async () => {
    // Given: a named key
    const calls = serve([label()], { status: 204, body: null });
    const onChanged = vi.fn();

    // When: the owner removes the name
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={onChanged} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove name" }));

    // Then: the removal names the key only in the request body
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(writes(calls)).toEqual([
      {
        method: "POST",
        path: "/v1/key-labels/remove",
        body: { target_type: "preference", key: "ui.theme.dark" },
      },
    ]);
  });

  it("offers no removal for a key that has no stored name", async () => {
    // Given: a key with no name
    serve([]);

    // When: the editor opens
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={vi.fn()} />);
    await screen.findByText("Your name for this key");

    // Then: there is nothing to remove
    expect(screen.queryByRole("button", { name: "Remove name" })).toBeNull();
  });

  it("marks a name Soulmate proposed", async () => {
    // Given: a name extraction wrote
    serve([label({ source: "extracted" })]);

    // When: the editor opens
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={vi.fn()} />);

    // Then: the owner can tell it apart from their own wording
    expect(
      await screen.findByText(/Soulmate suggested this name/),
    ).not.toBeNull();
  });

  it("reports a refused save without losing what was typed", async () => {
    // Given: a daemon that refuses an empty label
    const calls = serve([], { status: 409, body: null });
    invoke.mockImplementation((command: string, args?: unknown) => {
      const request = (args as { request: ApiCall }).request;
      calls.push(request);
      if (request.method === "GET") {
        return Promise.resolve({ status: 200, body: { labels: [] } });
      }
      return Promise.resolve({
        status: 409,
        body: { detail: "A key label needs a name or at least one alias." },
      });
    });

    // When: the owner saves nothing at all
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={vi.fn()} />);
    await screen.findByText("Your name for this key");
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: the reason is shown next to the still-editable fields
    expect(
      await screen.findByText(
        "A key label needs a name or at least one alias.",
      ),
    ).not.toBeNull();
    expect(screen.getByPlaceholderText("giao diện tối")).not.toBeNull();
  });

  it("reports an unreadable label list", async () => {
    // Given: a service that refuses the read
    invoke.mockImplementation(() =>
      Promise.resolve({ status: 503, body: { detail: "Service starting." } }),
    );

    // When: the editor opens
    render(<KeyLabelEditor targetKey="ui.theme.dark" onChanged={vi.fn()} />);

    // Then: the owner is told, and can still write a name
    expect(await screen.findByText("Service starting.")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Save name" })).not.toBeNull();
  });
});
