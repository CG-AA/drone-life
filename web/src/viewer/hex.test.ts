import { describe, expect, it } from "vitest";
import { axialToWorld, hexCorners, worldToAxial } from "./hex";

// Golden values generated from server/app/game/hex.py — pins the two
// implementations to each other so they cannot drift.
describe("axialToWorld", () => {
  it("matches the Python implementation", () => {
    const a = axialToWorld(2, 3, 3.0);
    expect(a.n).toBeCloseTo(13.5, 9);
    expect(a.e).toBeCloseTo(18.186533479473212, 9);
    const b = axialToWorld(-4, 1, 3.0);
    expect(b.n).toBeCloseTo(4.5, 9);
    expect(b.e).toBeCloseTo(-18.186533479473212, 9);
    const o = axialToWorld(0, 0, 3.0);
    expect(o.n).toBe(0);
    expect(o.e).toBe(0);
  });

  it("all six neighbors sit one pitch away", () => {
    const pitch = 5.196152422706632; // sqrt(3) * size, from Python
    const c = axialToWorld(2, 5, 3.0);
    const neighbors = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];
    for (const [dq, dr] of neighbors) {
      const nb = axialToWorld(2 + dq, 5 + dr, 3.0);
      expect(Math.hypot(nb.n - c.n, nb.e - c.e)).toBeCloseTo(pitch, 9);
    }
  });
});

describe("hexCorners", () => {
  it("returns six corners equidistant from the center", () => {
    const c = axialToWorld(3, -2, 3.0);
    const corners = hexCorners(3, -2, 3.0);
    expect(corners).toHaveLength(6);
    for (const p of corners) {
      expect(Math.hypot(p.n - c.n, p.e - c.e)).toBeCloseTo(3.0, 9);
    }
  });

  it("adjacent cells share an edge midpoint", () => {
    // cells (0,0) and (0,1) are neighbors; corners k=0,1 of (0,0) form the
    // shared edge, whose midpoint is halfway between the two centers
    const a = axialToWorld(0, 0, 3.0);
    const b = axialToWorld(0, 1, 3.0);
    const corners = hexCorners(0, 0, 3.0);
    const mid = { n: (corners[0].n + corners[1].n) / 2, e: (corners[0].e + corners[1].e) / 2 };
    expect(mid.n).toBeCloseTo((a.n + b.n) / 2, 9);
    expect(mid.e).toBeCloseTo((a.e + b.e) / 2, 9);
  });
});

describe("worldToAxial", () => {
  it("matches the Python implementation", () => {
    // golden values from hex.world_to_axial(n, e, 3.0)
    const cases: Array<[number, number, number, number]> = [
      [0, 0, 0, 0], [2.5, 2.5, 0, 1], [13.5, 18.19, 2, 3],
      [-7.9, 3.2, 2, -2], [4.4, -20.1, -4, 1], [1.5, 2.598, 0, 0],
    ];
    for (const [n, e, q, r] of cases) expect(worldToAxial(n, e, 3.0)).toEqual([q, r]);
  });

  it("inverts axialToWorld at every cell center", () => {
    for (let q = -5; q <= 5; q++) {
      for (let r = -5; r <= 5; r++) {
        const c = axialToWorld(q, r, 3.0);
        expect(worldToAxial(c.n, c.e, 3.0)).toEqual([q, r]);
      }
    }
  });
});
