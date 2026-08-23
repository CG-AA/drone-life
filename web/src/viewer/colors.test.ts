/** slotColor: stable, in-range, and distinct for adjacent sysids. */

import { expect, it } from "vitest";
import { slotColor } from "./colors";

it("is deterministic", () => {
  expect(slotColor(3)).toBe(slotColor(3));
});

it("stays a 24-bit color", () => {
  for (let sysid = 1; sysid <= 40; sysid++) {
    const c = slotColor(sysid);
    expect(Number.isInteger(c)).toBe(true);
    expect(c).toBeGreaterThanOrEqual(0);
    expect(c).toBeLessThanOrEqual(0xffffff);
  }
});

it("gives adjacent sysids clearly different hues (golden angle)", () => {
  const all = new Set<number>();
  for (let sysid = 1; sysid <= 20; sysid++) all.add(slotColor(sysid));
  expect(all.size).toBe(20);
});
