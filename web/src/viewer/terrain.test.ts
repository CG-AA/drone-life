/** groundAt: the surface a shadow lands on — stack top over tiles, floor
 * elsewhere, ordered against the tile prisms. */

import { expect, it } from "vitest";
import type { TilesData } from "../shared/protocol";
import { axialToWorld } from "./hex";
import type { Scene } from "./scene";
import { TerrainRenderer } from "./terrain";

const SIZE = 3.0;
const TILE_H = 2.0;

function makeRenderer(cells: TilesData["cells"]): TerrainRenderer {
  const fakeScene = {
    scale: 6,
    spriteLayer: { addChild() {} },
    setHexGeometry() {},
    groundAt: () => ({ alt: 0, zIndex: 0 }),
  } as unknown as Scene;
  const r = new TerrainRenderer(fakeScene);
  r.set({ geometry: { size: SIZE, tile_height: TILE_H }, cells });
  return r;
}

it("bare ground is altitude zero", () => {
  const r = makeRenderer([]);
  expect(r.groundAt(10, -20).alt).toBe(0);
});

it("over a stack, the surface is the stack top", () => {
  const r = makeRenderer([{ q: 2, r: 1, stack: ["steel", "steel"] }]);
  const c = axialToWorld(2, 1, SIZE);
  expect(r.groundAt(c.n, c.e).alt).toBe(2 * TILE_H);
  expect(r.groundAt(c.n + 50, c.e).alt).toBe(0);
});

it("a stacked surface paints above its own prism", () => {
  const r = makeRenderer([{ q: 0, r: 0, stack: ["clay"] }]);
  const c = axialToWorld(0, 0, SIZE);
  const onStack = r.groundAt(c.n, c.e);
  const bare = r.groundAt(c.n + 40, c.e + 40);
  expect(onStack.zIndex).not.toBe(bare.zIndex);
});
