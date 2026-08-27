/** describeError: every failure a student can hit says what to do next, and
 * nothing leaks raw server internals into the classroom. */

import { expect, it } from "vitest";
import { ApiFailure } from "../shared/http";
import { codeTooBig, describeError } from "./errors";

const fail = (code: string, msg: string, status: number, extra = {}) =>
  new ApiFailure({ code, msg, ...extra }, status);

it("points the editor at a syntax error", () => {
  const v = describeError(fail("syntax", "syntax error: expected ':'", 400,
    { line: 7, col: 12 }), "submit");
  expect(v.text).toContain("line 7");
  expect(v.goto).toEqual({ line: 7, col: 12 });
});

it("does not jump when the server could not place the error", () => {
  const v = describeError(fail("syntax", "unexpected EOF", 400, { line: 0, col: 0 }),
    "submit");
  expect(v.goto).toBeUndefined();
  expect(v.text).toContain("end of your script");
});

it("hides the runner exception behind an instructor-shaped message", () => {
  const v = describeError(fail("runner",
    "could not start your drone box: [Errno 2] No such file or directory: 'podman'",
    503), "submit");
  expect(v.text).not.toContain("Errno");
  expect(v.text).toContain("instructor");
});

it("keeps the instructor's fix, which is the only part anyone can act on", () => {
  const v = describeError(fail("runner",
    "could not start your drone box: runner image drone-life-runner:latest is not "
    + "built — instructor: run `make image`", 503), "submit");
  expect(v.text).toContain("make image");
  expect(v.text).not.toContain("drone-life-runner:latest"); // still no server noise
});

it("does not leak a python exception even when a fix is appended", () => {
  const v = describeError(fail("runner",
    "could not start your drone box: podman could not be run ([Errno 2] No such file "
    + "or directory) — instructor: run `make preflight`", 503), "submit");
  expect(v.text).not.toContain("Errno");
  expect(v.text).toContain("make preflight");
});

it("offers a way back in when the session expired", () => {
  const v = describeError(fail("auth", "join first (bad or missing token)", 401),
    "submit");
  expect(v.actions.map((a) => a.kind)).toContain("rejoin");
});

it("blames the class, not the student, for the join rate limit", () => {
  const v = describeError(fail("rate", "too many join attempts; wait a minute", 429),
    "join");
  expect(v.text).toContain("whole class");
  expect(v.actions.map((a) => a.kind)).toContain("retry");
});

it("tells a student pressing Run too fast that it is their own doing", () => {
  // the same code, the other limiter: submitting is capped per student
  const v = describeError(fail("rate", "submitting too fast — wait a few seconds", 429),
    "submit");
  expect(v.text).not.toContain("whole class");
  expect(v.text).toContain("Run too fast");
  expect(v.actions.map((a) => a.kind)).toContain("retry");
});

it("gives room-code and room-full errors a next action", () => {
  expect(describeError(fail("room_code", "wrong room code — ask your instructor", 403),
    "join").text).toContain("ask your instructor");
  expect(describeError(fail("room_full", "room is full (20 drones)", 409), "join").text)
    .toContain("free a slot");
});

it("passes the name rules through — they are already plain", () => {
  const msg = "names starting with 'Bot-' are reserved";
  expect(describeError(fail("name", msg, 400), "join").text).toBe(msg);
});

it("explains a size rejection in KB", () => {
  expect(describeError(fail("too_big", "script larger than 64 KB", 413), "submit").text)
    .toContain("64 KB");
});

it("handles a body with no error envelope (FastAPI validation, proxies)", () => {
  const v = describeError(fail("http", "request failed (422)", 422), "submit");
  expect(v.text).toContain("422");
  expect(v.actions.map((a) => a.kind)).toContain("retry");
});

it("names the network when fetch itself rejects", () => {
  const v = describeError(new TypeError("Failed to fetch"), "submit");
  expect(v.text).toContain("wifi");
  expect(v.actions.map((a) => a.kind)).toContain("retry");
});

it("measures script size in bytes, not characters", () => {
  expect(codeTooBig("print('hi')")).toBeNull();
  expect(codeTooBig("é".repeat(6), 10)).toBe(12); // 2 bytes each
  expect(codeTooBig("x".repeat(10), 10)).toBeNull(); // the limit itself is fine
});
