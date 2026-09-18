import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KeyAlias, KeyAliasList } from "../types.ts";
import { DuplicateKeysPanel } from "./DuplicateKeysPanel.tsx";

interface ApiCall {
  method: string;
  path: string;
  body: unknown;
}

const invoke = vi.fn<(command: string, args?: unknown) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string, args?: unknown) => invoke(command, args),
}));

function alias(overrides: Partial<KeyAlias>): KeyAlias {
  return {
    target_type: "preference",
    alias_key: "ui.theme.dark_mode",
    canonical_key: "ui.theme.dark",
    polarity: 1,
    method: "normalized",
    status: "active",
    similarity: null,
    algorithm_version: "key-normalizer-v1",
    created_at: "2026-09-17T00:00:00Z",
    updated_at: "2026-09-17T00:00:00Z",
    ...overrides,
  };
}

function serve(
  list: KeyAliasList | { status: number; detail: string },
  change: { status: number; body: unknown } = {
    status: 200,
    body: { snapshot_version: 2 },
  },
): ApiCall[] {
  const calls: ApiCall[] = [];
  invoke.mockImplementation((command: string, args?: unknown) => {
    if (command !== "api_request") {
      return Promise.reject(new Error(`Unexpected command: ${command}`));
    }
    const request = (args as { request: ApiCall }).request;
    calls.push(request);
    if (request.method === "GET") {
      return Promise.resolve(
        "status" in list
          ? { status: list.status, body: { detail: list.detail } }
          : { status: 200, body: list },
      );
    }
    return Promise.resolve(change);
  });
  return calls;
}

function writes(calls: ApiCall[]): ApiCall[] {
  return calls.filter((call) => call.method === "POST");
}

describe("duplicate keys panel", () => {
  afterEach(cleanup);

  beforeEach(() => {
    invoke.mockReset();
  });

  it("groups aliases by review state and reviews a suggestion", async () => {
    // Given: one suggestion, one merge, and one rejected merge
    const calls = serve({
      enabled: true,
      aliases: [
        alias({
          alias_key: "ui.theme.light",
          method: "semantic",
          status: "suggested",
          similarity: 0.91,
        }),
        alias({}),
        alias({ alias_key: "ui.theme.dark_level", status: "rejected" }),
      ],
    });
    const onChanged = vi.fn();

    // When: the owner merges the suggestion as an opposite
    render(<DuplicateKeysPanel revision={0} onChanged={onChanged} />);
    await screen.findByText("Possible duplicate keys");
    fireEvent.click(screen.getByRole("button", { name: "Merge as opposite" }));

    // Then: every section is shown and the review request is sent
    expect(screen.getByText("Merged keys")).not.toBeNull();
    expect(screen.getByText("Kept separate")).not.toBeNull();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(writes(calls)).toEqual([
      {
        method: "POST",
        path: "/v1/key-aliases/review",
        body: {
          target_type: "preference",
          alias_key: "ui.theme.light",
          action: "invert",
        },
      },
    ]);
    expect(calls.filter((call) => call.method === "GET")).toHaveLength(2);
  });

  it.each([
    ["Merge", "suggested", "approve"],
    ["Keep separate", "suggested", "reject"],
    ["Flip direction", "active", "invert"],
    ["Merge", "rejected", "approve"],
  ] as const)(
    "sends %s for a %s alias as %s",
    async (label, status, action) => {
      // Given: an alias in the given state
      const calls = serve({ enabled: true, aliases: [alias({ status })] });

      // When: the owner presses the action
      render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);
      fireEvent.click(await screen.findByRole("button", { name: label }));

      // Then: the matching review action is sent
      await waitFor(() =>
        expect(writes(calls)[0]?.body).toEqual({
          target_type: "preference",
          alias_key: "ui.theme.dark_mode",
          action,
        }),
      );
    },
  );

  it.each([
    ["normalized", "/v1/key-aliases/review"],
    ["owner", "/v1/key-aliases/remove"],
  ] as const)("undoes a %s merge through %s", async (method, path) => {
    // Given: an active merge created automatically or by the owner
    const calls = serve({ enabled: true, aliases: [alias({ method })] });

    // When: the owner undoes it
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));

    // Then: automatic merges are rejected and owner merges are removed
    await waitFor(() => expect(writes(calls)[0]?.path).toBe(path));
    expect(writes(calls)[0]?.body).toEqual(
      method === "owner"
        ? { target_type: "preference", alias_key: "ui.theme.dark_mode" }
        : {
            target_type: "preference",
            alias_key: "ui.theme.dark_mode",
            action: "reject",
          },
    );
  });

  it("does not offer direction changes for non-preference keys", async () => {
    // Given: a suggested and an active fact alias
    serve({
      enabled: true,
      aliases: [
        alias({ target_type: "fact", status: "suggested" }),
        alias({ target_type: "fact", alias_key: "Home.City" }),
      ],
    });

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);
    await screen.findByText("Possible duplicate keys");

    // Then: only polarity-free actions are shown
    expect(screen.queryByRole("button", { name: "Merge as opposite" })).toBe(
      null,
    );
    expect(screen.queryByRole("button", { name: "Flip direction" })).toBe(null);
    expect(screen.getByRole("button", { name: "Merge" })).not.toBeNull();
  });

  it("describes opposite merges", async () => {
    // Given: an inverted merge
    serve({
      enabled: true,
      aliases: [alias({ alias_key: "ui.theme.light", polarity: -1 })],
    });

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);

    // Then: the relation reads as an opposite
    expect(await screen.findByText(/opposite of/)).not.toBeNull();
  });

  it("explains a semantic suggestion with its similarity", async () => {
    // Given: a suggestion that only similar wording produced
    serve({
      enabled: true,
      aliases: [
        alias({
          alias_key: "appearance.night",
          method: "semantic",
          status: "suggested",
          similarity: 0.917,
        }),
      ],
    });

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);

    // Then: the owner sees why the pair was suggested before merging it
    expect(
      await screen.findByText(/similar wording, 92% alike/i),
    ).not.toBeNull();
  });

  it("names no similarity for an automatic merge", async () => {
    // Given: a merge produced by equal normalized keys
    serve({ enabled: true, aliases: [alias({})] });

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);

    // Then: no similarity is claimed
    expect(await screen.findByText(/same as/)).not.toBeNull();
    expect(screen.queryByText(/similar wording/i)).toBe(null);
  });

  it("shows merges read-only when key merging is disabled", async () => {
    // Given: aliases disabled in configuration
    serve({ enabled: false, aliases: [alias({})] });

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);

    // Then: the owner is told and no action is offered
    expect(await screen.findByText(/Key merging is turned off/)).not.toBeNull();
    expect(screen.queryByRole("button")).toBe(null);
  });

  it("reports when no duplicate keys exist", async () => {
    // Given: no aliases
    serve({ enabled: true, aliases: [] });

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);

    // Then: an empty state is shown
    expect(
      await screen.findByText("No duplicate keys have been found."),
    ).not.toBeNull();
  });

  it("shows the service error when the list cannot load", async () => {
    // Given: a service that refuses the list
    serve({ status: 503, detail: "Local storage is unavailable." });

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);

    // Then: the detail is shown
    expect(
      await screen.findByText("Local storage is unavailable."),
    ).not.toBeNull();
  });

  it("keeps the model unchanged when a review fails", async () => {
    // Given: a review rejected with a conflict
    serve(
      { enabled: true, aliases: [alias({ status: "rejected" })] },
      {
        status: 409,
        body: { detail: "Target key aliases form a cycle starting at 'x'." },
      },
    );
    const onChanged = vi.fn();

    // When: the owner tries to merge
    render(<DuplicateKeysPanel revision={0} onChanged={onChanged} />);
    fireEvent.click(await screen.findByRole("button", { name: "Merge" }));

    // Then: the conflict is shown and nothing is refreshed
    expect(
      await screen.findByText(
        "Target key aliases form a cycle starting at 'x'.",
      ),
    ).not.toBeNull();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("falls back to generic messages when the bridge fails", async () => {
    // Given: a desktop bridge that throws non-error values
    invoke.mockRejectedValue("bridge unavailable");

    // When: the panel renders
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);

    // Then: a readable message is shown
    expect(
      await screen.findByText("Merged keys are unavailable."),
    ).not.toBeNull();
  });

  it("falls back to a generic message when a change cannot be sent", async () => {
    // Given: a list that loads and a bridge that fails on writes
    invoke
      .mockResolvedValueOnce({
        status: 200,
        body: { enabled: true, aliases: [alias({})] },
      })
      .mockRejectedValueOnce("bridge closed");

    // When: the owner undoes a merge
    render(<DuplicateKeysPanel revision={0} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));

    // Then: a readable message replaces the raw bridge failure
    expect(
      await screen.findByText("The key merge could not be changed."),
    ).not.toBeNull();
  });
});
