/** Frame interpolation: render the world at *now*, not one frame ago.
 *
 * World frames arrive at 10 Hz. Interpolating between the two newest frames
 * is smooth but structurally renders 100 ms in the past. Instead we
 * dead-reckon from the newest frame using the velocities already on the wire,
 * then ease the render pose toward that target — the ease absorbs the small
 * prediction error when the next frame lands, so corrections never pop.
 *
 * Pure functions, unit-tested.
 */

import { lerpAngle } from "./iso";

/** Smoothing time constant. Larger = smoother but laggier. */
export const POS_TAU_MS = 90;
/** Never predict further ahead than this, however late the next frame is. */
export const EXTRAP_MAX_MS = 300;
/** Errors beyond this are teleports (reset, respawn), not motion — snap. */
export const SNAP_DIST_M = 5;
/** Sanity cap on velocity estimated by differencing entity positions. */
export const ENT_V_MAX = 15;

export interface Pose {
  n: number;
  e: number;
  alt: number;
  yaw: number;
}

/** Fraction of the remaining gap to close in one frame of `dtMs`.
 * Frame-rate independent: the same wall-clock ease at 30 or 144 fps. */
export function expBlend(dtMs: number, tauMs: number): number {
  return 1 - Math.exp(-Math.max(0, dtMs) / tauMs);
}

/** Dead-reckon one coordinate from the newest sample.
 *
 * The lead is the sample's age *plus* the smoother's time constant: an
 * exponential smoother chasing a moving target settles a constant τ behind it,
 * so leading by τ cancels that lag and a constant-velocity drone renders at
 * its true present position. */
export function predict(pos: number, vel: number, ageMs: number): number {
  const leadMs = Math.min(Math.max(ageMs, 0) + POS_TAU_MS, EXTRAP_MAX_MS);
  return pos + (vel * leadMs) / 1000;
}

/** Ease `state` one frame toward `target`. Snaps on the first sample and on
 * teleport-sized jumps, so a reset never glides a drone across the arena. */
export function smoothPose(state: Pose | undefined, target: Pose, dtMs: number): Pose {
  if (!state
      || Math.hypot(target.n - state.n, target.e - state.e, target.alt - state.alt)
         > SNAP_DIST_M) {
    return { n: target.n, e: target.e, alt: Math.max(0, target.alt), yaw: target.yaw };
  }
  const k = expBlend(dtMs, POS_TAU_MS);
  return {
    n: state.n + (target.n - state.n) * k,
    e: state.e + (target.e - state.e) * k,
    alt: Math.max(0, state.alt + (target.alt - state.alt) * k),
    yaw: lerpAngle(state.yaw, target.yaw, k),
  };
}

/** Velocity from two position samples, for entities (which carry no velocity
 * on the wire). Clamped: a respawn must not read as a 200 m/s crate. */
export function diffVelocity(prev: number, cur: number, intervalMs: number): number {
  if (intervalMs <= 0) return 0;
  const v = ((cur - prev) / intervalMs) * 1000;
  return Math.min(Math.max(v, -ENT_V_MAX), ENT_V_MAX);
}
