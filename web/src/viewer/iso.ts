/** NED -> 2:1 isometric screen projection. Pure functions, unit-tested.
 *
 * Orientation: the arena diamond's top corner is (+N, +E) — north runs up-left,
 * east runs up-right, so "go north" in a script visibly moves the drone up the
 * screen. Altitude lifts the sprite straight up; the ground shadow stays put.
 */

const COS30 = Math.cos(Math.PI / 6);
const SIN30 = 0.5;
export const ALT_LIFT = 0.9; // screen lift per meter of altitude, in scale units

export interface Projected {
  x: number;
  y: number;
  /** paint order: larger = nearer the camera (drawn on top) */
  depth: number;
}

export function project(n: number, e: number, alt: number, scale: number): Projected {
  return {
    x: (e - n) * COS30 * scale,
    y: -(e + n) * SIN30 * scale - alt * ALT_LIFT * scale,
    depth: -(n + e),
  };
}

/** Where the ground shadow of an airborne point sits. */
export function projectGround(n: number, e: number, scale: number): Projected {
  return project(n, e, 0, scale);
}

/** Inverse of project() at altitude 0: screen offset (in world-container
 * space) back to NED meters. Used to anchor zoom under the cursor and to turn
 * a pixel drag into a pan. */
export function unproject(x: number, y: number, scale: number): { n: number; e: number } {
  const diff = x / (COS30 * scale); // e - n
  const sum = -y / (SIN30 * scale); // e + n
  return { n: (sum - diff) / 2, e: (sum + diff) / 2 };
}

/** Scale so the whole arena (half-size `half`, tallest flight `altMax`) fits WxH. */
export function fitScale(half: number, altMax: number, w: number, h: number): number {
  const margin = 0.9;
  const worldW = 4 * half * COS30;
  const worldH = 4 * half * SIN30 + altMax * ALT_LIFT;
  return Math.min((w * margin) / worldW, (h * margin) / worldH);
}

/** Shortest-path angle interpolation (radians). */
export function lerpAngle(a: number, b: number, t: number): number {
  let d = (b - a) % (2 * Math.PI);
  if (d > Math.PI) d -= 2 * Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return a + d * t;
}
