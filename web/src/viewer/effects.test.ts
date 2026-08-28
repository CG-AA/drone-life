/** calloutFor: which feed events burst at the pilot's drone, and what they say. */

import { expect, it } from "vitest";
import { calloutFor } from "./effects";

const ev = (kind: string, student_id: string | null, data: Record<string, unknown> = {}) =>
  ({ kind, msg: kind, student_id, data, t: 1 });

it("floats the points from a credited score", () => {
  expect(calloutFor(ev("score", "s1", { points: 2 }))?.text).toBe("+2");
  expect(calloutFor(ev("delivery", "s1", { points: 10 }))?.text).toBe("+10");
  expect(calloutFor(ev("tile_placed", "s1", { points: 2 }))?.text).toBe("+2");
});

it("names the big moments", () => {
  expect(calloutFor(ev("tower_up", "s1", { points: 15 }))?.text).toBe("+15 TOWER");
  expect(calloutFor(ev("boss_down", "s1", { points: 20 }))?.text).toBe("+20 BOSS!");
  expect(calloutFor(ev("pickup", "s1"))?.text).toBe("got it");
});

it("never bursts for anonymous or pointless events", () => {
  expect(calloutFor(ev("score", null, { points: 10 }))).toBeNull();
  expect(calloutFor(ev("score", "s1", { points: 0 }))).toBeNull();
  expect(calloutFor(ev("score", "s1"))).toBeNull();
  expect(calloutFor(ev("keep_hit", "s1", { points: -1 }))).toBeNull();
  expect(calloutFor(ev("joined", "s1"))).toBeNull();
});
