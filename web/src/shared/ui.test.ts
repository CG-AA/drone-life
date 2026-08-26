/** runLabel: a student must be able to read why their script stopped. */

import { expect, it } from "vitest";

import { runLabel } from "./ui";
import type { RunState } from "./protocol";

function run(over: Partial<RunState> = {}): RunState {
  return { run_id: "r1", state: "exited", exit_code: 0, reason: "done", ...over };
}

it("says idle with no run at all", () => {
  expect(runLabel(null)).toBe("idle");
});

it("shows the live state while the script runs", () => {
  expect(runLabel(run({ state: "running", reason: null }))).toBe("running");
  expect(runLabel(run({ state: "starting", reason: null }))).toBe("starting");
});

it("names each end reason in words", () => {
  expect(runLabel(run({ reason: "done" }))).toBe("finished");
  expect(runLabel(run({ reason: "timeout", exit_code: -9 }))).toBe("timed out");
  expect(runLabel(run({ reason: "stopped" }))).toBe("stopped");
  expect(runLabel(run({ reason: "replaced" }))).toBe("replaced");
  expect(runLabel(run({ reason: "start_failed", exit_code: -1 }))).toBe("failed to start");
  expect(runLabel(run({ reason: "runner_failed", exit_code: 125 }))).toBe("sandbox error");
});

it("keeps the exit code for a plain script error — that's the debugging handle", () => {
  expect(runLabel(run({ reason: "error", exit_code: 1 }))).toBe("exited (1)");
});

it("falls back to the old rendering when a server sends no reason", () => {
  expect(runLabel(run({ reason: null, exit_code: 3 }))).toBe("exited (3)");
  expect(runLabel(run({ reason: null, exit_code: null }))).toBe("exited");
});
