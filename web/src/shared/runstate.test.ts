/** runClass: the wire says "exited" for both a finished script and a wrecked
 * one, and the two must never render the same. */

import { expect, it } from "vitest";
import type { RunState } from "./protocol";
import { formatAge, pillLabel, runClass } from "./runstate";

const run = (state: RunState["state"], exit: number | null = null): RunState =>
  ({ run_id: "r1", state, exit_code: exit, reason: null });

it("separates a clean exit from a crash", () => {
  expect(runClass(null)).toBe("idle");
  expect(runClass(run("starting"))).toBe("starting");
  expect(runClass(run("running"))).toBe("running");
  expect(runClass(run("exited", 0))).toBe("done");
  expect(runClass(run("exited", 1))).toBe("failed");
  expect(runClass(run("exited", 137))).toBe("failed");
  // we stopped it (kill, resubmit): deliberate, not the student's failure
  expect(runClass(run("exited", null))).toBe("done");
});

it("labels the pill with how long it has been that way", () => {
  expect(pillLabel(null, 0)).toBe("idle");
  expect(pillLabel(run("running"), 12 * 60_000)).toBe("running 12m");
  expect(pillLabel(run("starting"), 2000)).toBe("starting 2s");
  expect(pillLabel(run("exited", 137), 0)).toBe("exited (137)");
  expect(pillLabel(run("exited", 0), 0)).toBe("exited");
});

it("keeps ages readable at every scale", () => {
  expect(formatAge(0)).toBe("0s");
  expect(formatAge(59_999)).toBe("59s");
  expect(formatAge(60_000)).toBe("1m");
  expect(formatAge(3 * 3600_000 + 25 * 60_000)).toBe("3h25m");
  expect(formatAge(-5)).toBe("0s"); // a clock that stepped backwards
});
