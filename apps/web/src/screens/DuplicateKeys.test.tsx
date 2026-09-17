import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  SoulmateClient,
  type KeyAlias,
  type KeyAliasList,
} from "@soulmate/sdk";

import { DuplicateKeys } from "./DuplicateKeys.tsx";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clientFor(
  list: KeyAliasList | Error,
  change: Response | Error = json({ snapshot_version: 2 }),
): { client: SoulmateClient; calls: Call[] } {
  const calls: Call[] = [];
  const client = new SoulmateClient({
    baseUrl: "http://127.0.0.1:7432",
    fetch: (url, init) => {
      const method = init?.method ?? "GET";
      calls.push({
        method,
        url,
        body:
          typeof init?.body === "string"
            ? (JSON.parse(init.body) as unknown)
            : undefined,
      });
      const result = method === "GET" ? list : change;
      if (result instanceof Error) return Promise.reject(result);
      return Promise.resolve(
        result instanceof Response ? result : json(result),
      );
    },
  });
  return { client, calls };
}

describe("duplicate keys review", () => {
  afterEach(cleanup);

  it.each([
    ["Merge", "suggested", "normalized", "/v1/key-aliases/review", "approve"],
    [
      "Merge as opposite",
      "suggested",
      "semantic",
      "/v1/key-aliases/review",
      "invert",
    ],
    [
      "Keep separate",
      "suggested",
      "semantic",
      "/v1/key-aliases/review",
      "reject",
    ],
    [
      "Flip direction",
      "active",
      "normalized",
      "/v1/key-aliases/review",
      "invert",
    ],
    ["Undo", "active", "normalized", "/v1/key-aliases/review", "reject"],
    ["Undo", "active", "owner", "/v1/key-aliases/remove", undefined],
    ["Merge", "rejected", "normalized", "/v1/key-aliases/review", "approve"],
  ] as const)(
    "sends %s for a %s %s alias",
    async (label, status, method, path, action) => {
      // Given: an alias in the given state
      const { client, calls } = clientFor({
        enabled: true,
        aliases: [alias({ status, method })],
      });
      const onChanged = vi.fn();

      // When: the owner presses the action
      render(<DuplicateKeys client={client} onChanged={onChanged} />);
      fireEvent.click(await screen.findByRole("button", { name: label }));

      // Then: the change is sent and the model is refreshed
      await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
      const write = calls.find((call) => call.method === "POST");
      expect(write?.url).toBe(`http://127.0.0.1:7432${path}`);
      expect(write?.body).toEqual({
        target_type: "preference",
        alias_key: "ui.theme.dark_mode",
        ...(action === undefined ? {} : { action }),
      });
    },
  );

  it("shows opposite merges and hides direction changes for facts", async () => {
    // Given: an inverted preference merge and a fact suggestion
    const { client } = clientFor({
      enabled: true,
      aliases: [
        alias({ alias_key: "ui.theme.light", polarity: -1 }),
        alias({
          target_type: "fact",
          alias_key: "Home.City",
          status: "suggested",
        }),
      ],
    });

    // When: the review renders
    render(<DuplicateKeys client={client} onChanged={vi.fn()} />);

    // Then: labels reflect polarity and facts cannot be inverted
    expect(await screen.findByText(/opposite of/)).not.toBeNull();
    expect(screen.getByText("Possible duplicate keys")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Merge as opposite" })).toBe(
      null,
    );
    expect(
      screen.getAllByRole("button", { name: "Flip direction" }),
    ).toHaveLength(1);
  });

  it("is read-only when key merging is disabled", async () => {
    // Given: aliases disabled by configuration
    const { client } = clientFor({ enabled: false, aliases: [alias({})] });

    // When: the review renders
    render(<DuplicateKeys client={client} onChanged={vi.fn()} />);

    // Then: no action is offered
    expect(await screen.findByText(/Key merging is turned off/)).not.toBeNull();
    expect(screen.queryByRole("button")).toBe(null);
  });

  it("reports an empty review list", async () => {
    // Given: no aliases
    const { client } = clientFor({ enabled: true, aliases: [] });

    // When: the review renders
    render(<DuplicateKeys client={client} onChanged={vi.fn()} />);

    // Then: the empty state is shown
    expect(
      await screen.findByText("No duplicate keys have been found."),
    ).not.toBeNull();
  });

  it("reports a list that cannot load", async () => {
    // Given: a network failure
    const { client } = clientFor(new TypeError("Failed to fetch"));

    // When: the review renders
    render(<DuplicateKeys client={client} onChanged={vi.fn()} />);

    // Then: a readable alert is shown
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Merged keys are unavailable.",
    );
  });

  it("shows the service reason when a change is refused", async () => {
    // Given: a review that conflicts with the alias rules
    const { client } = clientFor(
      { enabled: true, aliases: [alias({ status: "rejected" })] },
      json({ detail: "Target key aliases form a cycle starting at 'x'." }, 409),
    );
    const onChanged = vi.fn();

    // When: the owner tries to merge
    render(<DuplicateKeys client={client} onChanged={onChanged} />);
    fireEvent.click(await screen.findByRole("button", { name: "Merge" }));

    // Then: the reason is shown and nothing is refreshed
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Target key aliases form a cycle starting at 'x'.",
    );
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for unexplained failures", async () => {
    // Given: a write that fails without a message
    const { client } = clientFor(
      { enabled: true, aliases: [alias({})] },
      new Error(""),
    );

    // When: the owner undoes a merge
    render(<DuplicateKeys client={client} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));

    // Then: a generic alert is shown
    expect((await screen.findByRole("alert")).textContent).toBe(
      "The key merge could not be changed.",
    );
  });
});
