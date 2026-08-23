import { describe, expect, it } from "vitest";
import {
  clampCamera, clampResolution, defaultCamera, maxScale, panBy, screenToWorld,
  solveCenter, worldOffset, zoomAt, PAN_MARGIN_M,
} from "./camera";
import { ALT_LIFT, fitScale } from "./iso";

describe("clampResolution", () => {
  it("honors devicePixelRatio when the framebuffer budget allows", () => {
    expect(clampResolution(1, 1920, 1080)).toBe(1);
    expect(clampResolution(2, 1920, 1080)).toBe(2);
  });

  it("allows a high ratio on a small (browser-zoomed) viewport", () => {
    // ctrl+zoom to 300%: CSS viewport shrinks as dpr rises, so full sharpness
    // still fits the budget.
    expect(clampResolution(3, 640, 360)).toBe(3);
  });

  it("caps the framebuffer area on a big HiDPI window", () => {
    const res = clampResolution(2, 3840, 2160);
    expect(res).toBeLessThan(2);
    expect(3840 * res * (2160 * res)).toBeLessThanOrEqual(9_000_001);
  });

  it("never drops below 1, and survives a missing dpr", () => {
    expect(clampResolution(0, 1920, 1080)).toBe(1);
    expect(clampResolution(2, 8000, 8000)).toBe(1);
  });
});

describe("defaultCamera / worldOffset", () => {
  it("reproduces the pre-camera projector layout exactly", () => {
    // Regression guard: a fresh viewer load must look pixel-identical to the
    // fixed fit-to-window layout it replaced.
    const [w, h] = [1920, 1080];
    const cam = defaultCamera(100, 60, w, h);
    const off = worldOffset(cam, w, h);
    const legacyScale = fitScale(100, 60, w, h);
    expect(cam.scale).toBeCloseTo(legacyScale);
    expect(off.x).toBeCloseTo(w / 2);
    expect(off.y).toBeCloseTo(h / 2 + (60 * ALT_LIFT * legacyScale) / 2);
  });
});

describe("zoomAt", () => {
  it("keeps the world point under the cursor pinned", () => {
    const [w, h] = [1600, 900];
    const cam = defaultCamera(100, 60, w, h);
    const [sx, sy] = [1200, 300];
    const before = screenToWorld(cam, w, h, sx, sy);
    const zoomed = zoomAt(cam, w, h, sx, sy, 2.5, 0.1, 100);
    const after = screenToWorld(zoomed, w, h, sx, sy);
    expect(zoomed.scale).toBeCloseTo(cam.scale * 2.5);
    expect(after.n).toBeCloseTo(before.n);
    expect(after.e).toBeCloseTo(before.e);
  });

  it("respects the scale limits", () => {
    const [w, h] = [1600, 900];
    const cam = defaultCamera(100, 60, w, h);
    expect(zoomAt(cam, w, h, 800, 450, 100, cam.scale, cam.scale * 4).scale)
      .toBeCloseTo(cam.scale * 4);
    expect(zoomAt(cam, w, h, 800, 450, 0.01, cam.scale, cam.scale * 4).scale)
      .toBeCloseTo(cam.scale);
  });
});

describe("panBy", () => {
  it("shifts the world offset by exactly the pixel delta", () => {
    const [w, h] = [1600, 900];
    const cam = defaultCamera(100, 60, w, h);
    const before = worldOffset(cam, w, h);
    const after = worldOffset(panBy(cam, 120, -45), w, h);
    expect(after.x - before.x).toBeCloseTo(120);
    expect(after.y - before.y).toBeCloseTo(-45);
  });
});

describe("solveCenter", () => {
  it("puts the requested world point at the requested screen point", () => {
    const [w, h] = [1280, 720];
    const c = solveCenter(40, -15, 300, 600, 6, w, h);
    const cam = { scale: 6, cN: c.cN, cE: c.cE };
    const got = screenToWorld(cam, w, h, 300, 600);
    expect(got.n).toBeCloseTo(40);
    expect(got.e).toBeCloseTo(-15);
  });
});

describe("clampCamera", () => {
  it("floors zoom at the fitted scale and caps zoom-in", () => {
    const [w, h] = [1600, 900];
    const fit = fitScale(100, 60, w, h);
    expect(clampCamera({ scale: fit / 4, cN: 0, cE: 0 }, 100, 60, w, h).scale)
      .toBeCloseTo(fit);
    expect(clampCamera({ scale: 9999, cN: 0, cE: 0 }, 100, 60, w, h).scale)
      .toBeCloseTo(maxScale(100, 60, w, h));
  });

  it("keeps the center within the arena plus its margin", () => {
    const c = clampCamera({ scale: 8, cN: 500, cE: -500 }, 100, 60, 1600, 900);
    expect(c.cN).toBeCloseTo(100 + PAN_MARGIN_M);
    expect(c.cE).toBeCloseTo(-(100 + PAN_MARGIN_M));
  });
});
