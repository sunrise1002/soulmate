import { describe, expect, it, vi } from "vitest";

import { ApiError, SoulmateClient, type FetchLike } from "./client.ts";

interface Call {
  url: string;
  init: RequestInit | undefined;
}

function stub(
  status: number,
  body: unknown,
): { fetch: FetchLike; calls: Call[] } {
  const calls: Call[] = [];
  const fetchImpl: FetchLike = (url, init) => {
    calls.push({ url, init });
    const text = body === undefined ? "" : JSON.stringify(body);
    return Promise.resolve(
      new Response(text, {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  };
  return { fetch: fetchImpl, calls };
}

function headersOf(call: Call): Record<string, string> {
  return (call.init?.headers ?? {}) as Record<string, string>;
}

describe("SoulmateClient", () => {
  it("sends the device credential and parses a successful response", async () => {
    // Given: a client holding a paired credential
    const { fetch, calls } = stub(200, { status: "healthy" });
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433/",
      credential: "device_1.secret",
      fetch,
    });

    // When: it calls the service
    const health = await client.health();

    // Then: the request is authorized and the body is typed
    expect(health.status).toBe("healthy");
    expect(calls[0]?.url).toBe("https://192.168.1.20:7433/v1/health");
    expect(headersOf(calls[0] as Call).Authorization).toBe(
      "Bearer device_1.secret",
    );
  });

  it("omits the authorization header without a credential", async () => {
    // Given: an unpaired client
    const { fetch, calls } = stub(200, { status: "healthy" });
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433",
      fetch,
    });

    // When: it probes health
    await client.health();

    // Then: nothing is sent that could look like a credential
    expect(headersOf(calls[0] as Call).Authorization).toBeUndefined();
  });

  it.each([[""], [undefined]])(
    "treats the empty credential %s as unpaired",
    async (credential) => {
      // Given: a client configured with an empty credential
      const { fetch, calls } = stub(200, { status: "healthy" });
      const client = new SoulmateClient({
        baseUrl: "https://192.168.1.20:7433",
        credential,
        fetch,
      });

      // When: it probes health
      await client.health();

      // Then: no authorization header is sent
      expect(headersOf(calls[0] as Call).Authorization).toBeUndefined();
    },
  );

  it("serializes request bodies as JSON", async () => {
    // Given: a paired client
    const { fetch, calls } = stub(200, { conversation_id: "conversation_1" });
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433",
      credential: "device_1.secret",
      fetch,
    });

    // When: it sends a chat message
    await client.chat("hello", "conversation_1");

    // Then: the daemon receives the documented payload
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.body).toBe(
      JSON.stringify({ content: "hello", conversation_id: "conversation_1" }),
    );
    expect(headersOf(calls[0] as Call)["Content-Type"]).toBe(
      "application/json",
    );
  });

  it("escapes identifiers used in paths", async () => {
    // Given: an identifier containing path characters
    const { fetch, calls } = stub(200, []);
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433",
      fetch,
    });

    // When: evidence for that preference is requested
    await client.preferenceEvidence("quiet/loud");

    // Then: the path cannot be escaped by user data
    expect(calls[0]?.url).toBe(
      "https://192.168.1.20:7433/v1/preferences/quiet%2Floud/evidence",
    );
  });

  it("exposes active learning, advice, and outcome operations", async () => {
    // Given: a paired client and successful local service
    const { fetch, calls } = stub(200, {});
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433",
      credential: "device_1.secret",
      fetch,
    });

    // When: Phase 8 workflows are requested
    await client.generateActiveQuestions(2, "work.remote");
    await client.answerActiveQuestion("question/1", "b");
    await client.adviseDecision("decision/1");
    await client.recordOutcome("decision/1", 0.25, true, "Synthetic outcome");
    await client.deleteOutcome("decision/1");

    // Then: identifiers and structured feedback use the versioned REST contract
    expect(calls.map((call) => call.url)).toEqual([
      "https://192.168.1.20:7433/v1/active-questions/generate",
      "https://192.168.1.20:7433/v1/active-questions/question%2F1/answer",
      "https://192.168.1.20:7433/v1/decisions/decision%2F1/advise",
      "https://192.168.1.20:7433/v1/decisions/decision%2F1/outcome",
      "https://192.168.1.20:7433/v1/decisions/decision%2F1/outcome",
    ]);
    expect(calls[0]?.init?.body).toBe(
      JSON.stringify({ limit: 2, target_key: "work.remote" }),
    );
    expect(calls[3]?.init?.body).toBe(
      JSON.stringify({
        satisfaction: 0.25,
        regret: true,
        notes: "Synthetic outcome",
      }),
    );
  });

  it("exposes scoped external identity and intelligence operations", async () => {
    const { fetch, calls } = stub(200, {});
    const client = new SoulmateClient({
      baseUrl: "http://127.0.0.1:7432",
      credential: "sk_soulmate.credential_1.secret",
      fetch,
    });
    const decision = {
      domain: "shopping",
      question: "Which laptop?",
      options: [
        { label: "A", description: "Quiet", features: { quiet: 1 } },
        { label: "B", description: "Fast", features: { quiet: -1 } },
      ],
    };

    await client.predictChoice(decision);
    await client.rankOptions(decision);
    await client.preferenceSummary();
    await client.findSimilarDecisions(decision);
    await client.recordExternalDecision(decision);
    await client.recordExternalOutcome("decision/1", 0.8, false);
    await client.updateServiceIdentityScopes("service/1", ["decision:predict"]);
    await client.revokeApiCredential("service/1", "credential/1");

    expect(calls.map((call) => call.url)).toEqual([
      "http://127.0.0.1:7432/v1/external/predict-choice",
      "http://127.0.0.1:7432/v1/external/rank-options",
      "http://127.0.0.1:7432/v1/external/preference-summary",
      "http://127.0.0.1:7432/v1/external/find-similar-decisions",
      "http://127.0.0.1:7432/v1/external/record-decision",
      "http://127.0.0.1:7432/v1/external/record-outcome",
      "http://127.0.0.1:7432/v1/service-identities/service%2F1/scopes",
      "http://127.0.0.1:7432/v1/service-identities/service%2F1/credentials/credential%2F1",
    ]);
    expect(headersOf(calls[0] as Call).Authorization).toBe(
      "Bearer sk_soulmate.credential_1.secret",
    );
  });

  it("exposes owner-only portability and import operations", async () => {
    const { fetch, calls } = stub(200, {});
    const client = new SoulmateClient({
      baseUrl: "http://127.0.0.1:7432",
      fetch,
    });

    await client.dataSources();
    await client.importChatHistory("history.json", "[]", "json");
    await client.deleteDataSource("source/1");
    await client.createBackup();
    await client.createEncryptedExport("synthetic export phrase");
    await client.stageRestore("YXJjaGl2ZQ==", "synthetic export phrase");

    expect(calls.map((call) => call.url)).toEqual([
      "http://127.0.0.1:7432/v1/data/sources",
      "http://127.0.0.1:7432/v1/data/imports",
      "http://127.0.0.1:7432/v1/data/sources/source%2F1",
      "http://127.0.0.1:7432/v1/data/backups",
      "http://127.0.0.1:7432/v1/data/exports",
      "http://127.0.0.1:7432/v1/data/restores",
    ]);
    expect(calls[1]?.init?.body).toBe(
      JSON.stringify({
        name: "history.json",
        content: "[]",
        format: "json",
      }),
    );
  });

  it.each([
    [401, "A paired device credential is required.", true],
    [403, "This action is only available on the owner's device.", true],
    [404, "Device was not found.", false],
    [503, "The local service is starting.", false],
  ])(
    "maps status %s to a typed error",
    async (status, detail, requiresPairing) => {
      // Given: a service that refuses the request
      const { fetch } = stub(status, { detail });
      const client = new SoulmateClient({
        baseUrl: "https://192.168.1.20:7433",
        fetch,
      });

      // When: the client calls it
      const error = await client
        .modelSummary()
        .catch((caught: unknown) => caught);

      // Then: callers can react to revoked or missing pairing
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(status);
      expect((error as ApiError).message).toBe(detail);
      expect((error as ApiError).requiresPairing).toBe(requiresPairing);
    },
  );

  it("falls back to a readable message when the service sends no detail", async () => {
    // Given: an error response without a detail field
    const { fetch } = stub(500, {});
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433",
      fetch,
    });

    // When/Then: the message still identifies the failure
    await expect(client.modelSummary()).rejects.toThrow("status 500");
  });

  it("reports a transport failure to the caller", async () => {
    // Given: a network that drops the request
    const fetchImpl = vi
      .fn<FetchLike>()
      .mockRejectedValue(new TypeError("Network request failed"));
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433",
      fetch: fetchImpl,
    });

    // When/Then: the original transport error surfaces
    await expect(client.health()).rejects.toThrow("Network request failed");
  });

  it("returns a client bound to a new credential after re-pairing", async () => {
    // Given: a client whose credential was revoked
    const { fetch, calls } = stub(200, { status: "healthy" });
    const client = new SoulmateClient({
      baseUrl: "https://192.168.1.20:7433",
      credential: "device_1.old",
      fetch,
    });

    // When: the device pairs again
    await client.withCredential("device_2.new").health();

    // Then: the new credential is used without rebuilding the transport
    expect(headersOf(calls[0] as Call).Authorization).toBe(
      "Bearer device_2.new",
    );
  });
});
