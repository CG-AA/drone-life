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
