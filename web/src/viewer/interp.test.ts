import { describe, expect, it } from "vitest";
import {
  diffVelocity, expBlend, predict, smoothPose, ENT_V_MAX, EXTRAP_MAX_MS, POS_TAU_MS,
  type Pose,
} from "./interp";

describe("expBlend", () => {
  it("closes more of the gap the longer the frame", () => {
    expect(expBlend(8, 90)).toBeLessThan(expBlend(16, 90));
    expect(expBlend(0, 90)).toBe(0);
    expect(expBlend(10_000, 90)).toBeCloseTo(1);
  });
});

describe("predict", () => {
  it("leads a fresh sample by the smoother's time constant", () => {
    expect(predict(0, 10, 0)).toBeCloseTo((10 * POS_TAU_MS) / 1000);
  });

  it("leads further as the sample ages", () => {
    expect(predict(0, 10, 100)).toBeGreaterThan(predict(0, 10, 0));
  });

  it("stops extrapolating once the feed is badly late", () => {
    const capped = predict(0, 10, 5000);
    expect(capped).toBeCloseTo((10 * EXTRAP_MAX_MS) / 1000);
    expect(predict(0, 10, 60_000)).toBeCloseTo(capped);
  });

  it("leaves a stationary point alone", () => {
    expect(predict(42, 0, 250)).toBe(42);
  });
});

describe("smoothPose", () => {
  const at = (n: number, e = 0, alt = 0, yaw = 0): Pose => ({ n, e, alt, yaw });

  it("snaps on the first sample", () => {
    expect(smoothPose(undefined, at(10, 20, 5), 16)).toEqual(at(10, 20, 5));
  });

  it("snaps on a teleport instead of gliding across the arena", () => {
    expect(smoothPose(at(0), at(90), 16).n).toBe(90);
  });

  it("eases toward a nearby target and converges", () => {
    let pose = at(0);
    const target = at(2);
    pose = smoothPose(pose, target, 16);
    expect(pose.n).toBeGreaterThan(0);
    expect(pose.n).toBeLessThan(2);
    for (let i = 0; i < 60; i++) pose = smoothPose(pose, target, 16);
    expect(pose.n).toBeCloseTo(2);
  });

  it("never renders a drone underground", () => {
    expect(smoothPose(at(0, 0, 1), at(0, 0, -0.4), 16).alt).toBeGreaterThanOrEqual(0);
  });

  it("takes the short way around the yaw seam", () => {
    const pose = smoothPose({ n: 0, e: 0, alt: 0, yaw: 3.0 },
                            { n: 0, e: 0, alt: 0, yaw: -3.0 }, 500);
    expect(Math.cos(pose.yaw)).toBeLessThan(0); // stayed near pi, didn't sweep through 0
  });
});

describe("diffVelocity", () => {
  it("recovers a constant velocity from two samples", () => {
    expect(diffVelocity(0, 1, 100)).toBeCloseTo(10);
  });

  it("clamps implausible jumps and tolerates a zero interval", () => {
    expect(diffVelocity(0, 500, 100)).toBe(ENT_V_MAX);
    expect(diffVelocity(0, -500, 100)).toBe(-ENT_V_MAX);
    expect(diffVelocity(0, 5, 0)).toBe(0);
  });
});

describe("end-to-end tracking", () => {
  it("renders a cruising drone at its true present position", () => {
    // The whole point of the scheme: a drone crossing the arena at 8 m/s must
    // render where it *is*, not where it was when the last frame was built.
    const v = 8;
    let truth = 0;          // true position, advanced in real time
    let sampled = 0;        // position as of the newest world frame
    let sampledAt = 0;      // when that frame arrived
    let pose: Pose | undefined;
    let t = 0;

    for (let frame = 0; frame < 240; frame++) {  // 4 s at 60 fps
      const dt = 1000 / 60;
      t += dt;
      truth = (v * t) / 1000;
      if (t - sampledAt >= 100) {   // a 10 Hz world frame lands
        sampledAt = t;
        sampled = truth;
      }
      const age = t - sampledAt;
      const target: Pose = { n: predict(sampled, v, age), e: 0, alt: 0, yaw: 0 };
      pose = smoothPose(pose, target, dt);
    }

    // within 15 cm of truth; the old lerp scheme sat a full ~0.8 m behind here
    expect(Math.abs(pose!.n - truth)).toBeLessThan(0.15);
  });
});
