/** slotColor: stable, in-range, distinct for adjacent sysids, and legible
 * on the arena floor from the back of the room. */

import { expect, it } from "vitest";
import { contrastRatio, parseHex, relativeLuminance, slotColor } from "./colors";

const FLOOR = 0x151b28; // COLORS.floor in shared/theme.ts

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

it("measures contrast on the WCAG scale", () => {
  expect(contrastRatio(0xffffff, 0x000000)).toBeCloseTo(21, 1);
  expect(contrastRatio(FLOOR, FLOOR)).toBeCloseTo(1, 5);
  expect(relativeLuminance(0xffffff)).toBeCloseTo(1, 5);
  expect(relativeLuminance(0x000000)).toBeCloseTo(0, 5);
});

it("clears AA against the arena floor for every slot", () => {
  for (let sysid = 1; sysid <= 40; sysid++) {
    const ratio = contrastRatio(slotColor(sysid), FLOOR);
    expect(ratio, `sysid ${sysid} on the floor`).toBeGreaterThanOrEqual(4.5);
  }
});

it("parses a bought #rrggbb and refuses everything else", () => {
  expect(parseHex("#ff8800")).toBe(0xff8800);
  expect(parseHex(" #FF8800 ")).toBe(0xff8800);
  expect(parseHex("#fff")).toBeNull();
  expect(parseHex("ff8800")).toBeNull();
  expect(parseHex("#gg8800")).toBeNull();
  expect(parseHex(null)).toBeNull();
  expect(parseHex(0xff8800)).toBeNull();
});
