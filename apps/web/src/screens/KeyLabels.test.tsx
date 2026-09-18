import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SoulmateClient, type KeyLabel } from "@soulmate/sdk";

import { KeyLabels } from "./KeyLabels.tsx";

interface Call {
  method: string;
  url: string;
  body: unknown;
}

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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clientFor(
  labels: KeyLabel[] | Error,
  write: Response = json(label()),
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
      if (method === "GET") {
        return labels instanceof Error
          ? Promise.reject(labels)
          : Promise.resolve(json({ labels }));
      }
      return Promise.resolve(write);
    },
  });
  return { client, calls };
}

const KEYS = ["ui.theme.dark", "work.remote"];

describe("key labels", () => {
  afterEach(cleanup);

  it("names a key in the owner's own language", async () => {
    // Given: keys with no names yet
    const { client, calls } = clientFor([]);
    const onChanged = vi.fn();

    // When: the owner writes a name and two other wordings
    render(<KeyLabels client={client} keys={KEYS} onChanged={onChanged} />);
    await screen.findByText("Your names for keys");
    fireEvent.change(screen.getByPlaceholderText("giao diện tối"), {
      target: { value: " giao diện tối " },
    });
    fireEvent.change(screen.getByPlaceholderText("nền tối, dark mode"), {
      target: { value: "nền tối, , dark mode" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: the wording is trimmed and empty entries are dropped
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    const write = calls.find((call) => call.method === "POST");
    expect(write?.body).toEqual({
      target_type: "preference",
      key: "ui.theme.dark",
      label: "giao diện tối",
      aliases: ["nền tối", "dark mode"],
    });
  });

  it("loads the stored name when another key is selected", async () => {
    // Given: a name stored for the second key
    const { client } = clientFor([
      label({ key: "work.remote", label: "làm từ xa" }),
    ]);

    // When: the owner selects that key
    render(<KeyLabels client={client} keys={KEYS} onChanged={vi.fn()} />);
    await screen.findByText("Your names for keys");
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "work.remote" },
    });

    // Then: its stored wording appears in the form
    await waitFor(() =>
      expect(screen.getByDisplayValue("làm từ xa")).not.toBeNull(),
    );
  });

  it("keeps at most five wordings", async () => {
    // Given: keys with no names yet
    const { client, calls } = clientFor([]);

    // When: the owner writes six wordings
    render(<KeyLabels client={client} keys={KEYS} onChanged={vi.fn()} />);
    await screen.findByText("Your names for keys");
    fireEvent.change(screen.getByPlaceholderText("nền tối, dark mode"), {
      target: { value: "a, b, c, d, e, f" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: the request stays inside the limit the daemon enforces
    await waitFor(() =>
      expect(calls.some((call) => call.method === "POST")).toBe(true),
    );
    const write = calls.find((call) => call.method === "POST");
    expect((write?.body as { aliases: string[] }).aliases).toEqual([
      "a",
      "b",
      "c",
      "d",
      "e",
    ]);
  });

  it("sends an absent name as null", async () => {
    // Given: keys with no names yet
    const { client, calls } = clientFor([]);

    // When: the owner saves only a wording
    render(<KeyLabels client={client} keys={KEYS} onChanged={vi.fn()} />);
    await screen.findByText("Your names for keys");
    fireEvent.change(screen.getByPlaceholderText("nền tối, dark mode"), {
      target: { value: "nền tối" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: the missing name is explicit
    await waitFor(() =>
      expect(calls.some((call) => call.method === "POST")).toBe(true),
    );
    const write = calls.find((call) => call.method === "POST");
    expect((write?.body as { label: string | null }).label).toBeNull();
  });

  it("removes a stored name", async () => {
    // Given: a named key
    const { client, calls } = clientFor(
      [label()],
      new Response(null, { status: 204 }),
    );
    const onChanged = vi.fn();

    // When: the owner removes the name
    render(<KeyLabels client={client} keys={KEYS} onChanged={onChanged} />);
    await screen.findByText("Your names for keys");
    fireEvent.click(screen.getByRole("button", { name: "Remove name" }));

    // Then: the key travels in the body, never in the path
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    const write = calls.find((call) => call.method === "POST");
    expect(write?.url).toBe("http://127.0.0.1:7432/v1/key-labels/remove");
    expect(write?.body).toEqual({
      target_type: "preference",
      key: "ui.theme.dark",
    });
  });

  it("reports a refused save", async () => {
    // Given: a daemon that refuses an empty label
    const { client } = clientFor(
      [],
      json({ detail: "A key label needs a name or at least one alias." }, 409),
    );

    // When: the owner saves nothing
    render(<KeyLabels client={client} keys={KEYS} onChanged={vi.fn()} />);
    await screen.findByText("Your names for keys");
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    // Then: the reason is shown
    expect(
      await screen.findByText(
        "A key label needs a name or at least one alias.",
      ),
    ).not.toBeNull();
  });

  it("reports a refused removal", async () => {
    // Given: a daemon that has no label to remove
    const { client } = clientFor(
      [],
      json({ detail: "The key has no label." }, 404),
    );

    // When: the owner removes a name that was never written
    render(<KeyLabels client={client} keys={KEYS} onChanged={vi.fn()} />);
    await screen.findByText("Your names for keys");
    fireEvent.click(screen.getByRole("button", { name: "Remove name" }));

    // Then: the reason is shown
    expect(await screen.findByText("The key has no label.")).not.toBeNull();
  });

  it("renders nothing when the model holds no keys", () => {
    // Given: an empty model
    const { client, calls } = clientFor([]);

    // When: the panel is rendered with no keys
    const { container } = render(
      <KeyLabels client={client} keys={[]} onChanged={vi.fn()} />,
    );

    // Then: there is nothing to name, and no key is offered
    expect(container.textContent).toBe("");
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("reports an unreadable label list", async () => {
    // Given: an unreachable service
    const { client } = clientFor(new Error("offline"));

    // When: the panel loads
    render(<KeyLabels client={client} keys={KEYS} onChanged={vi.fn()} />);

    // Then: the owner is told, and can still write a name
    expect(
      await screen.findByText("Key names are unavailable."),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "Save name" })).not.toBeNull();
  });
});
