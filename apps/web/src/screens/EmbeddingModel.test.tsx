import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SoulmateClient, type EmbeddingModel as Model } from "@soulmate/sdk";

import { EmbeddingModel } from "./EmbeddingModel.tsx";

interface Call {
  method: string;
  url: string;
}

function model(overrides: Partial<Model> = {}): Model {
  return {
    provider: "local",
    model_id: "bge-m3-int8",
    display_name: "BGE-M3 (int8)",
    license: "MIT",
    source: "https://huggingface.co/Xenova/bge-m3",
    dimensions: 1024,
    download_bytes: 585_539_515,
    peak_memory_bytes: 2_000_000_000,
    installed: false,
    downloading: false,
    downloaded_bytes: 0,
    expected_bytes: 585_539_515,
    can_download: true,
    privacy_mode: "strict_local",
    error: null,
    files: [],
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
  state: Model | Error,
  change: Response = json(model({ downloading: true })),
): { client: SoulmateClient; calls: Call[] } {
  const calls: Call[] = [];
  const client = new SoulmateClient({
    baseUrl: "http://127.0.0.1:7432",
    fetch: (url, init) => {
      const method = init?.method ?? "GET";
      calls.push({ method, url });
      if (method === "GET") {
        return state instanceof Error
          ? Promise.reject(state)
          : Promise.resolve(json(state));
      }
      return Promise.resolve(change);
    },
  });
  return { client, calls };
}

describe("embedding model panel", () => {
  afterEach(cleanup);

  it("states the download size and memory cost before any action", async () => {
    // Given: a model that was never downloaded
    const { client, calls } = clientFor(model());

    // When: the panel loads
    render(<EmbeddingModel client={client} />);
    await screen.findByText(/586 MB to download/);

    // Then: the memory need is shown and nothing was fetched but the status
    expect(screen.getByText(/about 2.0 GB of memory/)).not.toBeNull();
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("downloads only on an explicit owner action", async () => {
    // Given: a model that was never downloaded
    const { client, calls } = clientFor(model());

    // When: the owner presses the download button
    render(<EmbeddingModel client={client} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download 586 MB" }),
    );

    // Then: one download request was sent
    await waitFor(() =>
      expect(
        calls.filter((call) =>
          call.url.endsWith("/v1/embedding-model/download"),
        ),
      ).toHaveLength(1),
    );
  });

  it("shows progress and offers to stop a running download", async () => {
    // Given: a download in flight
    const { client } = clientFor(
      model({ downloading: true, downloaded_bytes: 292_769_757 }),
    );

    // When: the panel loads
    render(<EmbeddingModel client={client} />);

    // Then: the owner sees how far it got and can stop it
    expect(
      await screen.findByText(/Downloading 293 MB of 586 MB/),
    ).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Stop download" }),
    ).not.toBeNull();
    expect(screen.queryByRole("button", { name: /^Download/ })).toBeNull();
  });

  it("removes an installed model on request", async () => {
    // Given: an installed model
    const { client, calls } = clientFor(
      model({ installed: true, downloaded_bytes: 585_539_515 }),
      json(model()),
    );

    // When: the owner removes it
    render(<EmbeddingModel client={client} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove model" }),
    );

    // Then: the files are deleted by an explicit request
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.endsWith("/v1/embedding-model/remove")),
      ).toHaveLength(1),
    );
  });

  it("cannot start a download the privacy mode refuses", async () => {
    // Given: offline mode
    const { client } = clientFor(
      model({ can_download: false, privacy_mode: "offline" }),
    );

    // When: the panel loads
    render(<EmbeddingModel client={client} />);
    await screen.findByText(
      "The configured privacy mode does not allow downloading a model here.",
    );

    // Then: the button exists but is unusable
    expect(
      screen
        .getByRole("button", { name: "Download 586 MB" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("says when an installed model is switched off in the configuration", async () => {
    // Given: an installed model with the provider still set to none
    const { client } = clientFor(model({ installed: true, provider: "none" }));

    // When: the panel loads
    render(<EmbeddingModel client={client} />);

    // Then: the owner learns why nothing changed after downloading
    expect(
      await screen.findByText(/The model is installed but switched off\./),
    ).not.toBeNull();
  });

  it("shows a verification failure the daemon recorded", async () => {
    // Given: a download that failed its SHA-256 check
    const { client } = clientFor(
      model({
        error: "model_int8.onnx failed SHA-256 verification and was discarded.",
      }),
    );

    // When: the panel loads
    render(<EmbeddingModel client={client} />);

    // Then: the owner sees the reason the model is still missing
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "model_int8.onnx failed SHA-256 verification and was discarded.",
    );
  });

  it("reports a refused download instead of failing silently", async () => {
    // Given: a daemon that refuses the download
    const { client } = clientFor(
      model(),
      json({ detail: "A model download is already running." }, 409),
    );

    // When: the owner presses download
    render(<EmbeddingModel client={client} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download 586 MB" }),
    );

    // Then: the reason reaches the owner
    expect(
      await screen.findByText("A model download is already running."),
    ).not.toBeNull();
  });

  it("renders nothing but a message when the model cannot be read", async () => {
    // Given: an unreachable service
    const { client } = clientFor(new Error("offline"));

    // When: the panel loads
    render(<EmbeddingModel client={client} />);

    // Then: no download card is shown at all
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "The local model is unavailable.",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});
