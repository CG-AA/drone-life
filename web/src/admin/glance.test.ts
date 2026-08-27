/** The glance test: a stuck or broken student has to be the first thing the
 * instructor's eye lands on, and their age must survive the 3 s poll. */

import { expect, it } from "vitest";
import type { RosterStudent, RunState } from "../shared/protocol";
import { ageMs, attention, orderRoster, updateAges } from "./glance";

const run = (state: RunState["state"], exit: number | null = null,
             id = "r1"): RunState => ({ run_id: id, state, exit_code: exit, reason: null });

const student = (o: Partial<RosterStudent> & { student_id: string }): RosterStudent =>
  ({ name: o.student_id, slot: 0, sysid: 1, run: null, connected: true,
     crashed: false, ...o });

it("keeps counting while the state holds", () => {
  const s = [student({ student_id: "s1", run: run("running") })];
  const first = updateAges(new Map(), s, 1000);
  const later = updateAges(first, s, 61_000);
  expect(ageMs(later, s[0], 61_000)).toBe(60_000);
});

it("restarts the clock on a new run or a state change", () => {
  const before = [student({ student_id: "s1", run: run("running", null, "r1") })];
  const ages = updateAges(new Map(), before, 1000);

  const nextState = [student({ student_id: "s1", run: run("exited", 0, "r1") })];
  expect(ageMs(updateAges(ages, nextState, 50_000), nextState[0], 50_000)).toBe(0);

  const nextRun = [student({ student_id: "s1", run: run("running", null, "r2") })];
  expect(ageMs(updateAges(ages, nextRun, 50_000), nextRun[0], 50_000)).toBe(0);
});

it("forgets students who left", () => {
  const ages = updateAges(new Map(), [student({ student_id: "s1" })], 1000);
  expect(updateAges(ages, [student({ student_id: "s2" })], 2000).size).toBe(1);
});

it("flags what an instructor should walk over to", () => {
  expect(attention(student({ student_id: "a", run: run("exited", 1) }), 0)).toBe("failed");
  expect(attention(student({ student_id: "b", crashed: true }), 0)).toBe("crashed");
  expect(attention(student({ student_id: "c", run: run("running") }), 11 * 60_000))
    .toBe("stuck");
  expect(attention(student({ student_id: "d", run: run("running") }), 60_000)).toBe("none");
  expect(attention(student({ student_id: "e", run: run("exited", 0) }), 99 * 60_000))
    .toBe("none");
});

it("puts a crashed drone below a failed script but above a healthy one", () => {
  const rows = [
    student({ student_id: "fine", slot: 0, run: run("running") }),
    student({ student_id: "crashed", slot: 1, crashed: true }),
    student({ student_id: "failed", slot: 2, run: run("exited", 2) }),
  ];
  const order = orderRoster(rows, new Map(), 0).map((s) => s.student_id);
  expect(order).toEqual(["failed", "crashed", "fine"]);
});

it("keeps equal rows in slot order so the table doesn't shuffle", () => {
  const rows = [
    student({ student_id: "c", slot: 3 }),
    student({ student_id: "a", slot: 1 }),
    student({ student_id: "b", slot: 2 }),
  ];
  expect(orderRoster(rows, new Map(), 0).map((s) => s.slot)).toEqual([1, 2, 3]);
});

