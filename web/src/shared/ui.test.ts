/** runLabel: a student must be able to read why their script stopped. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

import { END_LABEL, runLabel } from "./ui";
import { END_REASONS } from "./protocol";
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

it("knows every reason the server can send", () => {
  const path = fileURLToPath(
    new URL("../../../server/app/runner/manager.py", import.meta.url));
  const src = readFileSync(path, "utf8");
  const block = src.split("# BEGIN-END-REASONS")[1]?.split("# END-END-REASONS")[0];
  expect(block, "marker block missing from manager.py").toBeTruthy();
  const reasons = [...block!.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);

  expect(reasons.length).toBeGreaterThan(5);
  // the wire list first: RunEndReason is derived from it, so a server reason
  // missing here is a type that lies about what can arrive
  expect([...END_REASONS].sort()).toEqual([...reasons].sort());
  // "error" deliberately has no label — it keeps its exit code instead
  const labelled = new Set([...Object.keys(END_LABEL), "error"]);
  for (const reason of reasons) {
    expect(labelled, `no rendering for reason ${reason}`).toContain(reason);
  }
  for (const reason of Object.keys(END_LABEL)) {
    expect(reasons, `${reason} is not a server reason any more`).toContain(reason);
  }
});
