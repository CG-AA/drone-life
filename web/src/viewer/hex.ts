/** Axial hex math, mirroring server/app/game/hex.py. Pure, unit-tested.
 *
 * Pointy-top hexes in the NED ground plane:
 *   e = size * sqrt(3) * (q + r / 2)
 *   n = size * 3/2 * r
 * `size` (center-to-corner) always comes from the tiles message — never a
 * local constant, so the two languages cannot drift.
 */

const SQRT3 = Math.sqrt(3);

export interface WorldPoint {
  n: number;
  e: number;
}

export function axialToWorld(q: number, r: number, size: number): WorldPoint {
  return { n: size * 1.5 * r, e: size * SQRT3 * (q + r / 2) };
}

/** The cell's 6 corners in world meters, counter-clockwise from due east. */
export function hexCorners(q: number, r: number, size: number): WorldPoint[] {
  const c = axialToWorld(q, r, size);
  const corners: WorldPoint[] = [];
  for (let k = 0; k < 6; k++) {
    const a = (Math.PI / 180) * (60 * k + 30);
    corners.push({ n: c.n + size * Math.sin(a), e: c.e + size * Math.cos(a) });
  }
  return corners;
}

export type Axial = [q: number, r: number];

/** Cube rounding: snap fractional axial coords to the nearest cell. */
export function axialRound(qf: number, rf: number): Axial {
  const x = qf;
  const z = rf;
  const y = -x - z;
  let rx = Math.round(x);
  const ry = Math.round(y);
  let rz = Math.round(z);
  const dx = Math.abs(rx - x);
  const dy = Math.abs(ry - y);
  const dz = Math.abs(rz - z);
  if (dx > dy && dx > dz) rx = -ry - rz;
  else if (dy <= dz) rz = -rx - ry;
  return [rx, rz];
}

/** (n, e) in meters -> the cell containing it. Mirrors hex.world_to_axial. */
export function worldToAxial(n: number, e: number, size: number): Axial {
  const rf = (2 / 3) * n / size;
  const qf = (SQRT3 / 3) * e / size - rf / 2;
  return axialRound(qf, rf);
}

/** Depth bias that keeps a prism behind anything standing on it: a sprite on
 * the ground outside the cell is at least 1.27·size farther along (n + e), so
 * pushing the prism back by 0.6·size never flips a real front/behind case. */
export const PRISM_DEPTH_BIAS = 0.6;
