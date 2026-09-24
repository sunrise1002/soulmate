import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DecisionIoObservation,
  DecisionIoSource,
  ServiceIdentity,
} from "../types.ts";
import { DecisionIoObservationsPanel } from "./DecisionIoObservationsPanel.tsx";
import { DecisionIoSourcesPanel } from "./DecisionIoSourcesPanel.tsx";

interface ApiCall {
  method: string;
  path: string;
  body: unknown;
}

const invoke = vi.fn<(command: string, args?: unknown) => Promise<unknown>>();

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (command: string, args?: unknown) => invoke(command, args),
}));

const identity: ServiceIdentity = {
  id: "service_1",
  name: "Coding agent",
  description: null,
  scopes: ["decision:record"],
  created_at: "2026-09-23T00:00:00Z",
  revoked_at: null,
  active: true,
  credentials: [],
};

const source: DecisionIoSource = {
  id: "source_1",
  name: "Synthetic agent",
  provider: "synthetic_agent",
  consent_at: "2026-09-23T00:00:00Z",
  data_classes: ["metadata", "decision"],
  author_scope: "mixed",
  raw_retention_policy: "structured_only",
  policy_profile_version: "p13.1",
  service_identity_id: "service_1",
  raw_event_count: 4,
  decision_count: 1,
  resolution_observation_count: 1,
  outcome_observation_count: 2,
  unmatched_observation_count: 1,
};

function observation(
  overrides: Partial<DecisionIoObservation>,
): DecisionIoObservation {
  return {
    id: "observation_1",
    kind: "owner_reported",
    source_id: "source_1",
    actor_type: "agent",
    status: "pending",
    decision_id: "decision_1",
    external_decision_id: "decision-1",
    disposition: null,
    technical_status: null,
    satisfaction: 0.9,
    regret: false,
    created_at: "2026-09-23T00:00:00Z",
    confirmed_at: null,
    ...overrides,
  };
}

function serve(
  reads: unknown,
  write: { status: number; body: unknown } = { status: 200, body: {} },
): ApiCall[] {
  const calls: ApiCall[] = [];
  invoke.mockImplementation((command: string, args?: unknown) => {
    if (command !== "api_request") {
      return Promise.reject(new Error(`Unexpected command: ${command}`));
    }
    const request = (args as { request: ApiCall }).request;
    calls.push(request);
    return Promise.resolve(
      request.method === "GET" ? { status: 200, body: reads } : write,
    );
  });
  return calls;
}

function writes(calls: ApiCall[]): ApiCall[] {
  return calls.filter((call) => call.method !== "GET");
}

describe("Decision I/O sources panel", () => {
  afterEach(cleanup);

  beforeEach(() => {
    invoke.mockReset();
    vi.restoreAllMocks();
  });

  it("shows granted capabilities and volume for each source", async () => {
    // Given: one approved source
    serve([source]);

    // When: the panel loads
    render(
      <DecisionIoSourcesPanel identities={[identity]} onChanged={vi.fn()} />,
    );

    // Then: the owner sees what it may send, what is kept, and how much exists
    expect(await screen.findByText("Synthetic agent")).not.toBeNull();
    expect(screen.getByText(/Activity metadata, Decisions/)).not.toBeNull();
    expect(screen.getByText(/Keeps: Structured records/)).not.toBeNull();
    expect(screen.getByText(/4 events/)).not.toBeNull();
    expect(screen.getByText(/1 unmatched/)).not.toBeNull();
  });

  it("approves a source with the selected identity and data classes", async () => {
    // Given: no sources and one active identity
    const calls = serve([]);
    const onChanged = vi.fn();
    render(
      <DecisionIoSourcesPanel identities={[identity]} onChanged={onChanged} />,
    );
    await screen.findByText("No agent is allowed to send events yet.");

    // When: the owner fills in the form and approves it
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Coding agent" },
    });
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "codex" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve source" }));

    // Then: exactly the owner's choices are sent
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(writes(calls)).toEqual([
      {
        method: "POST",
        path: "/v1/decision-io/sources",
        body: {
          name: "Coding agent",
          provider: "codex",
          service_identity_id: "service_1",
          data_classes: ["metadata", "decision", "outcome"],
          raw_retention_policy: "metadata_only",
        },
      },
    ]);
  });

  it("explains the deletion consequence and keeps the source when cancelled", async () => {
    // Given: one source and an owner who declines the confirmation
    const calls = serve([source]);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <DecisionIoSourcesPanel identities={[identity]} onChanged={vi.fn()} />,
    );

    // When: the owner presses remove
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove Synthetic agent" }),
    );

    // Then: the consequence is shown and nothing is deleted
    expect(confirm.mock.calls[0]?.[0]).toContain("4 events, 1 decisions");
    expect(writes(calls)).toEqual([]);
  });

  it("removes a source after confirmation", async () => {
    // Given: one source and an owner who accepts the confirmation
    const calls = serve([source], {
      status: 200,
      body: {
        source_id: "source_1",
        raw_event_count: 4,
        decision_count: 1,
        observation_count: 3,
        evidence_count: 2,
        model_rebuilt: true,
      },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onChanged = vi.fn();
    render(
      <DecisionIoSourcesPanel identities={[identity]} onChanged={onChanged} />,
    );

    // When: the owner removes it
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove Synthetic agent" }),
    );

    // Then: the delete request is sent and the result reported
    expect(
      await screen.findByText(/Removed 4 events and 2 Evidence/),
    ).not.toBeNull();
    expect(writes(calls)[0]).toEqual({
      method: "DELETE",
      path: "/v1/decision-io/sources/source_1",
      body: null,
    });
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("shows the daemon's reason when approval is refused", async () => {
    // Given: the daemon rejects the retention request
    serve([], {
      status: 422,
      body: { detail: "The source could not be approved by the daemon." },
    });
    render(
      <DecisionIoSourcesPanel identities={[identity]} onChanged={vi.fn()} />,
    );
    await screen.findByText("No agent is allowed to send events yet.");

    // When: the owner submits the form
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "A" } });
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "b" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve source" }));

    // Then: the reason is displayed
    expect(
      await screen.findByText(
        "The source could not be approved by the daemon.",
      ),
    ).not.toBeNull();
  });

  it("disables approval when no identity is active", async () => {
    // Given: only a revoked identity
    serve([]);
    render(
      <DecisionIoSourcesPanel
        identities={[{ ...identity, active: false }]}
        onChanged={vi.fn()}
      />,
    );

    // When/Then: the approve button cannot be used
    const button = await screen.findByRole("button", {
      name: "Approve source",
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("Decision I/O observations panel", () => {
  afterEach(cleanup);

  beforeEach(() => {
    invoke.mockReset();
  });

  it("labels reports as observed until the owner confirms them", async () => {
    // Given: one pending satisfaction report and one confirmed technical result
    serve([
      observation({}),
      observation({
        id: "observation_2",
        kind: "technical",
        status: "confirmed",
        technical_status: "succeeded",
        satisfaction: null,
        regret: null,
        confirmed_at: "2026-09-23T01:00:00Z",
      }),
    ]);

    // When: the panel loads
    render(<DecisionIoObservationsPanel revision={0} onChanged={vi.fn()} />);

    // Then: observations are visibly distinct from confirmed records
    expect(await screen.findByText("observed (pending)")).not.toBeNull();
    expect(screen.getByText("confirmed")).not.toBeNull();
    expect(screen.getByText(/90% satisfied/)).not.toBeNull();
  });

  it("confirms a satisfaction report with the owner's own values", async () => {
    // Given: a pending satisfaction report from an agent
    const calls = serve([observation({})]);
    const onChanged = vi.fn();
    render(<DecisionIoObservationsPanel revision={0} onChanged={onChanged} />);

    // When: the owner confirms with their own satisfaction and regret
    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    fireEvent.change(screen.getByLabelText(/Your satisfaction/), {
      target: { value: "0.4" },
    });
    fireEvent.click(screen.getByLabelText("I regret this decision"));
    fireEvent.click(screen.getByRole("button", { name: "Save my outcome" }));

    // Then: the owner's values, not the agent's, are sent
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(writes(calls)).toEqual([
      {
        method: "POST",
        path: "/v1/decision-io/observations/observation_1/confirm",
        body: { satisfaction: 0.4, regret: true, notes: null },
      },
    ]);
  });

  it("rejects an observation and offers no confirmation for technical results", async () => {
    // Given: a pending technical result
    const calls = serve([
      observation({
        kind: "technical",
        technical_status: "failed",
        satisfaction: null,
        regret: null,
      }),
    ]);
    render(<DecisionIoObservationsPanel revision={0} onChanged={vi.fn()} />);

    // When: the owner rejects it
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));

    // Then: only a rejection is possible and it is sent
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    await waitFor(() =>
      expect(writes(calls)[0]?.path).toBe(
        "/v1/decision-io/observations/observation_1/reject",
      ),
    );
  });

  it("does not offer confirmation for an unmatched report", async () => {
    // Given: a satisfaction report whose decision has not arrived
    serve([observation({ status: "unmatched", decision_id: null })]);

    // When: the panel loads
    render(<DecisionIoObservationsPanel revision={0} onChanged={vi.fn()} />);

    // Then: it can be rejected but not confirmed
    expect(
      await screen.findByRole("button", { name: "Reject" }),
    ).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("shows an error when observations cannot be loaded", async () => {
    // Given: the daemon fails the read
    invoke.mockResolvedValue({
      status: 500,
      body: { detail: "Observations failed to load." },
    });

    // When: the panel loads
    render(<DecisionIoObservationsPanel revision={0} onChanged={vi.fn()} />);

    // Then: the failure is visible
    expect(
      await screen.findByText("Observations failed to load."),
    ).not.toBeNull();
  });
});
