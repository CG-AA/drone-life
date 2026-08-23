import { describe, expect, it } from "vitest";
import { fitScale, lerpAngle, project, projectGround, unproject } from "./iso";

describe("project", () => {
  it("puts the origin at screen center", () => {
    const p = project(0, 0, 0, 3);
    expect(p.x).toBeCloseTo(0);
    expect(p.y).toBeCloseTo(0);
  });

  it("moves north up and left", () => {
    const p = project(10, 0, 0, 1);
    expect(p.x).toBeLessThan(0);
    expect(p.y).toBeLessThan(0);
  });

  it("moves east up and right", () => {
    const p = project(0, 10, 0, 1);
    expect(p.x).toBeGreaterThan(0);
    expect(p.y).toBeLessThan(0);
  });

  it("altitude lifts the point without moving its shadow", () => {
    const ground = projectGround(5, 5, 2);
    const air = project(5, 5, 10, 2);
    expect(air.x).toBe(ground.x);
    expect(air.y).toBeLessThan(ground.y);
    expect(air.depth).toBe(ground.depth);
  });

  it("nearer (south-west) points paint on top", () => {
    expect(project(-50, -50, 0, 1).depth).toBeGreaterThan(project(50, 50, 0, 1).depth);
  });
});

describe("unproject", () => {
  it("round-trips project() at ground level", () => {
    for (const [n, e] of [[0, 0], [10, -25], [-100, 100], [37.5, 4.25]]) {
      for (const s of [1, 3, 7.75]) {
        const p = project(n, e, 0, s);
        const back = unproject(p.x, p.y, s);
        expect(back.n).toBeCloseTo(n);
        expect(back.e).toBeCloseTo(e);
      }
    }
  });

  it("is linear in the screen delta (panBy relies on it)", () => {
    const a = unproject(40, 24, 2.5);
    const b = unproject(80, 48, 2.5);
    expect(b.n).toBeCloseTo(a.n * 2);
    expect(b.e).toBeCloseTo(a.e * 2);
  });
});

describe("fitScale", () => {
  it("fits the arena into the viewport", () => {
    const s = fitScale(100, 60, 1920, 1080);
    expect(s).toBeGreaterThan(0);
    const corner = project(-100, 100, 0, s); // widest x
    expect(Math.abs(corner.x) * 2).toBeLessThanOrEqual(1920);
  });
});

describe("lerpAngle", () => {
  it("takes the short way around", () => {
    const mid = lerpAngle(3.0, -3.0, 0.5); // across the pi seam
    expect(Math.abs(Math.cos(mid))).toBeGreaterThan(0.9);
    expect(Math.cos(mid)).toBeLessThan(0);
  });
});
