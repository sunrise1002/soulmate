import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EmbeddingModel } from "../types.ts";
import { EmbeddingModelPanel } from "./EmbeddingModelPanel.tsx";

interface ApiCall {
  method: string;
  path: string;
  body: unknown;
}

const invoke = vi.fn<(command: string, args?: unknown) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string, args?: unknown) => invoke(command, args),
}));

function model(overrides: Partial<EmbeddingModel> = {}): EmbeddingModel {
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

function serve(
  state: EmbeddingModel,
  after: EmbeddingModel | { status: number; detail: string } = state,
): ApiCall[] {
  const calls: ApiCall[] = [];
  invoke.mockImplementation((command: string, args?: unknown) => {
    if (command !== "api_request") {
      return Promise.reject(new Error(`Unexpected command: ${command}`));
    }
    const request = (args as { request: ApiCall }).request;
    calls.push(request);
    if (request.method === "GET") {
      return Promise.resolve({ status: 200, body: state });
    }
    return Promise.resolve(
      "status" in after
        ? { status: after.status, body: { detail: after.detail } }
        : { status: 200, body: after },
    );
  });
  return calls;
}

describe("embedding model panel", () => {
  afterEach(cleanup);

  beforeEach(() => {
    invoke.mockReset();
  });

  it("shows the size and memory cost before the owner commits", async () => {
    // Given: a model that was never downloaded
    serve(model());

    // When: the panel loads
    render(<EmbeddingModelPanel />);
    await screen.findByText("BGE-M3 (int8) · MIT");

    // Then: the download and memory needs are stated on the button and next to it
    expect(screen.getByText("586 MB")).not.toBeNull();
    expect(screen.getByText("about 2.0 GB")).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Download 586 MB" }),
    ).not.toBeNull();
  });

  it("downloads only when the owner presses the button", async () => {
    // Given: a model that was never downloaded
    const calls = serve(model(), model({ downloading: true }));

    // When: the panel loads and the owner presses download
    render(<EmbeddingModelPanel />);
    await screen.findByRole("button", { name: "Download 586 MB" });
    expect(calls.every((call) => call.method === "GET")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Download 586 MB" }));

    // Then: exactly one download request was sent
    await waitFor(() =>
      expect(
        calls.filter((call) => call.path === "/v1/embedding-model/download"),
      ).toHaveLength(1),
    );
  });

  it("shows progress and offers to stop a running download", async () => {
    // Given: a download that is half finished
    serve(
      model({
        downloading: true,
        downloaded_bytes: 292_769_757,
        expected_bytes: 585_539_515,
      }),
    );

    // When: the panel loads
    render(<EmbeddingModelPanel />);
    await screen.findByText("293 MB of 586 MB · 50%");

    // Then: the owner can stop it, and cannot start a second one
    expect(
      screen.getByRole("button", { name: "Stop download" }),
    ).not.toBeNull();
    expect(screen.queryByRole("button", { name: /^Download/ })).toBeNull();
  });

  it("offers removal once the model is installed", async () => {
    // Given: an installed model
    const calls = serve(
      model({ installed: true, downloaded_bytes: 585_539_515 }),
      model(),
    );

    // When: the owner removes it
    render(<EmbeddingModelPanel />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove model" }),
    );

    // Then: the removal is an explicit request of its own
    await waitFor(() =>
      expect(
        calls.filter((call) => call.path === "/v1/embedding-model/remove"),
      ).toHaveLength(1),
    );
  });

  it("offers to discard an interrupted download", async () => {
    // Given: a partial file left by a stopped download
    serve(model({ downloaded_bytes: 1_000_000 }));

    // When: the panel loads
    render(<EmbeddingModelPanel />);

    // Then: the owner can resume it or throw the partial bytes away
    expect(
      await screen.findByRole("button", { name: "Discard partial download" }),
    ).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Download 586 MB" }),
    ).not.toBeNull();
  });

  it("explains why offline mode blocks the download", async () => {
    // Given: offline mode, which refuses every endpoint
    serve(model({ can_download: false, privacy_mode: "offline" }));

    // When: the panel loads
    render(<EmbeddingModelPanel />);

    // Then: the reason is shown and the button cannot be pressed
    await screen.findByText(
      "Offline mode blocks every download. Import the files manually instead.",
    );
    expect(
      screen
        .getByRole("button", { name: "Download 586 MB" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });

  it("says when an installed model is switched off in the configuration", async () => {
    // Given: an installed model with the provider still set to none
    serve(model({ installed: true, provider: "none" }));

    // When: the panel loads
    render(<EmbeddingModelPanel />);

    // Then: the owner learns why nothing improved after the download
    expect(
      await screen.findByText(/The model is installed but switched off\./),
    ).not.toBeNull();
  });

  it("reports a refused download instead of failing silently", async () => {
    // Given: a service that refuses the download
    serve(model(), {
      status: 409,
      detail: "The configured privacy mode denies downloading a model.",
    });

    // When: the owner presses download
    render(<EmbeddingModelPanel />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download 586 MB" }),
    );

    // Then: the reason from the daemon is shown
    expect(
      await screen.findByText(
        "The configured privacy mode denies downloading a model.",
      ),
    ).not.toBeNull();
  });

  it("shows a failure the daemon recorded during a download", async () => {
    // Given: a download that failed verification
    serve(
      model({
        error: "model_int8.onnx failed SHA-256 verification and was discarded.",
      }),
    );

    // When: the panel loads
    render(<EmbeddingModelPanel />);

    // Then: the owner sees why the model is still missing
    expect(
      await screen.findByText(
        "model_int8.onnx failed SHA-256 verification and was discarded.",
      ),
    ).not.toBeNull();
  });

  it("stays quiet when the local service cannot be reached", async () => {
    // Given: a service that refuses the read
    invoke.mockImplementation(() =>
      Promise.resolve({ status: 503, body: { detail: "Service starting." } }),
    );

    // When: the panel loads
    render(<EmbeddingModelPanel />);

    // Then: the error replaces the panel instead of showing an empty download card
    expect(await screen.findByText("Service starting.")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /^Download/ })).toBeNull();
  });
});
