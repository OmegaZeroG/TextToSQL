import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FALLBACK_DIALECTS,
  analyzeSchema,
  checkHealth,
  fetchDialects,
  generateSql,
  updateSchema,
} from "./api";
import { makeResponse } from "./test/factories";

type Reply = { status: number; body?: unknown } | Error;

function stubFetch(reply: Reply) {
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => {
    // A DOMException is not `instanceof Error` under jsdom, so tell replies apart by shape.
    if (!("status" in reply)) throw reply;
    return {
      status: reply.status,
      json: async () => {
        if (reply.body === undefined) throw new Error("no body");
        return reply.body;
      },
    } as Response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const abortError = () => new DOMException("Aborted", "AbortError");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("analyzeSchema / updateSchema", () => {
  it("posts the schema text and dialect and returns the parsed body", async () => {
    const data = { dialect: "postgres", source: "ddl", ddl: "CREATE TABLE t (id INT);", tables: [] };
    const fetchMock = stubFetch({ status: 200, body: data });

    const result = await analyzeSchema("CREATE TABLE t (id INT);", "postgres");

    expect(result).toEqual({ ok: true, data });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/v1\/schema\/analyze$/);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ schema_text: "CREATE TABLE t (id INT);", dialect: "postgres" });
  });

  it("sends the current schema and the change request when updating", async () => {
    const fetchMock = stubFetch({ status: 200, body: { changes: [] } });
    await updateSchema("CREATE TABLE t (id INT);", "add a name", "mysql");
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      current_ddl: "CREATE TABLE t (id INT);",
      change_text: "add a name",
      dialect: "mysql",
    });
  });

  it("surfaces the API's message when a request is rejected", async () => {
    stubFetch({ status: 422, body: { detail: "Schema not changed: that doesn't change anything" } });
    expect(await analyzeSchema("x", "postgres")).toEqual({
      ok: false,
      message: "Schema not changed: that doesn't change anything",
    });
  });

  it("gives a plain message for FastAPI validation errors (an array)", async () => {
    stubFetch({ status: 422, body: { detail: [{ loc: ["body", "schema_text"], msg: "too short" }] } });
    const result = await analyzeSchema("", "postgres");
    expect(result).toEqual({ ok: false, message: "That request was rejected as invalid." });
  });

  it("falls back to the status code when the error body is not JSON", async () => {
    stubFetch({ status: 502 });
    expect(await analyzeSchema("x", "postgres")).toEqual({ ok: false, message: "Request failed (502)." });
  });

  it("explains a network failure", async () => {
    stubFetch(new TypeError("Failed to fetch"));
    const result = await analyzeSchema("x", "postgres");
    expect(result.ok).toBe(false);
    expect(!result.ok && result.message).toMatch(/Couldn't reach the API \(Failed to fetch\)\. Is the backend running\?/);
  });

  it("reports a cancelled request as cancelled, not as an error", async () => {
    stubFetch(abortError());
    expect(await analyzeSchema("x", "postgres", new AbortController().signal)).toEqual({
      ok: false,
      message: "Cancelled.",
      cancelled: true,
    });
  });
});

describe("generateSql", () => {
  it("sends null when there is no schema", async () => {
    const fetchMock = stubFetch({ status: 200, body: makeResponse() });
    await generateSql("how many?", null, "postgres");
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({
      question: "how many?",
      schema_ddl: null,
      dialect: "postgres",
    });
  });

  it("passes the abort signal through to fetch", async () => {
    const fetchMock = stubFetch({ status: 200, body: makeResponse() });
    const controller = new AbortController();
    await generateSql("q", null, "postgres", controller.signal);
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);
  });

  it("returns the response on success", async () => {
    const body = makeResponse({ sql: "SELECT 1" });
    stubFetch({ status: 200, body });
    expect(await generateSql("q", null, "postgres")).toEqual({ kind: "success", data: body });
  });

  it("turns an ambiguous 422 into a clarification", async () => {
    stubFetch({
      status: 422,
      body: { detail: { kind: "ambiguous", message: "Several readings.", interpretations: ["gross", "net"] } },
    });
    expect(await generateSql("revenue?", null, "postgres")).toEqual({
      kind: "clarification",
      data: { kind: "ambiguous", message: "Several readings.", interpretations: ["gross", "net"] },
    });
  });

  it("turns an unanswerable 422 into a clarification of that kind", async () => {
    stubFetch({
      status: 422,
      body: { detail: { kind: "unanswerable", message: "Not in your schema.", interpretations: ["no shoe size"] } },
    });
    const outcome = await generateSql("shoe size?", "ddl", "postgres");
    expect(outcome.kind === "clarification" && outcome.data.kind).toBe("unanswerable");
  });

  it("ignores non-string interpretations", async () => {
    stubFetch({ status: 422, body: { detail: { kind: "ambiguous", message: "m", interpretations: ["a", 5, null] } } });
    const outcome = await generateSql("q", null, "postgres");
    expect(outcome.kind === "clarification" && outcome.data.interpretations).toEqual(["a"]);
  });

  it("treats a 422 with a plain-text detail as an error, not a clarification", async () => {
    stubFetch({ status: 422, body: { detail: "Couldn't read that schema: nope" } });
    expect(await generateSql("q", "bad", "postgres")).toEqual({
      kind: "error",
      message: "Couldn't read that schema: nope",
    });
  });

  it("reports server errors", async () => {
    stubFetch({ status: 502, body: { detail: "LLM generation failed: boom" } });
    expect(await generateSql("q", null, "postgres")).toEqual({
      kind: "error",
      message: "LLM generation failed: boom",
    });
  });

  it("reports an unreachable API", async () => {
    stubFetch(new TypeError("Failed to fetch"));
    const outcome = await generateSql("q", null, "postgres");
    expect(outcome.kind).toBe("error");
  });

  it("reports an aborted request as cancelled", async () => {
    stubFetch(abortError());
    expect(await generateSql("q", null, "postgres", new AbortController().signal)).toEqual({ kind: "cancelled" });
  });
});

describe("checkHealth", () => {
  it("is true only for a 200", async () => {
    stubFetch({ status: 200, body: { status: "ok" } });
    expect(await checkHealth()).toBe(true);
    stubFetch({ status: 503, body: {} });
    expect(await checkHealth()).toBe(false);
  });

  it("is false when the request fails or is aborted", async () => {
    stubFetch(new TypeError("Failed to fetch"));
    expect(await checkHealth()).toBe(false);
    stubFetch(abortError());
    expect(await checkHealth()).toBe(false);
  });
});

describe("fetchDialects", () => {
  it("returns the API's list", async () => {
    const list = [{ id: "postgres", label: "PostgreSQL" }];
    stubFetch({ status: 200, body: list });
    expect(await fetchDialects()).toEqual(list);
  });

  it.each([
    ["a failed request", new TypeError("offline") as Reply],
    ["a server error", { status: 500, body: {} } as Reply],
    ["an empty list", { status: 200, body: [] } as Reply],
    ["a malformed body", { status: 200, body: { nope: true } } as Reply],
  ])("falls back to the built-in list on %s", async (_label, reply) => {
    stubFetch(reply);
    expect(await fetchDialects()).toEqual(FALLBACK_DIALECTS);
  });
});
