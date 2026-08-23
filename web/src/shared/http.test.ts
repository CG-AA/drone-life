/** The {"error": {...}} envelope unwrap behind every button on two pages. */

import { afterEach, expect, it, vi } from "vitest";
import { ApiFailure, request } from "./http";

function stubFetch(status: number, body: unknown): void {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(
    body === undefined ? "not json at all" : JSON.stringify(body),
    { status, headers: { "Content-Type": "application/json" } })));
}

afterEach(() => vi.unstubAllGlobals());

it("returns the parsed body on success", async () => {
  stubFetch(200, { ok: true, run_id: "abc" });
  await expect(request("POST", "/api/v1/submit", {}, { code: "x" }))
    .resolves.toEqual({ ok: true, run_id: "abc" });
});

it("throws ApiFailure with the server's error envelope", async () => {
  stubFetch(422, { error: { code: "syntax", msg: "bad line", line: 3 } });
  const failure = await request("POST", "/api/v1/submit", {}).catch((e: unknown) => e);
  expect(failure).toBeInstanceOf(ApiFailure);
  expect((failure as ApiFailure).status).toBe(422);
  expect((failure as ApiFailure).error).toEqual({ code: "syntax", msg: "bad line", line: 3 });
});

it("degrades to a generic error when the body is not JSON", async () => {
  stubFetch(502, undefined);
  const failure = await request("GET", "/api/v1/x", {}).catch((e: unknown) => e);
  expect(failure).toBeInstanceOf(ApiFailure);
  expect((failure as ApiFailure).error.code).toBe("http");
  expect((failure as ApiFailure).error.msg).toContain("502");
});
