/** Hex-tile terrain: material-banded prisms drawn into one Graphics.
 *
 * Event-driven — a full redraw happens only when a tiles message arrives or
 * the scene rescales, never per frame. Tiles are static between messages, so
 * they bypass the per-frame entity path entirely.
 */

import { Graphics } from "pixi.js";
import type { TilesData } from "../shared/protocol";
import { axialToWorld, hexCorners } from "./hex";
import { ALT_LIFT, project } from "./iso";
import type { Scene } from "./scene";

interface MaterialColors {
  top: number;
  side: number;
  sideDark: number;
}

const MATERIAL_COLORS: Record<string, MaterialColors> = {
  steel: { top: 0xa8b4c4, side: 0x77879c, sideDark: 0x566374 },
  clay: { top: 0xc98d68, side: 0xa9714c, sideDark: 0x8f5a3c },
};
const UNKNOWN: MaterialColors = { top: 0x8a8f98, side: 0x6a6f78, sideDark: 0x4e535c };

export class TerrainRenderer {
  private g = new Graphics();
  private data: TilesData | null = null;
  private drawnScale = 0;

  constructor(private scene: Scene) {
    scene.terrainLayer.addChild(this.g);
  }

  set(data: TilesData): void {
    this.data = data;
    this.render();
  }

  /** Called from the ticker: repaints only after a resize changed the scale. */
  tick(): void {
    if (this.data && this.scene.scale !== this.drawnScale) this.render();
  }

  private render(): void {
    const g = this.g;
    g.clear();
    const data = this.data;
    if (!data) return;
    const s = this.scene.scale;
    this.drawnScale = s;
    const { size, tile_height } = data.geometry;

    // back-to-front so near prisms paint over far ones
    const cells = [...data.cells].sort((a, b) => {
      const ca = axialToWorld(a.q, a.r, size);
      const cb = axialToWorld(b.q, b.r, size);
      return project(cb.n, cb.e, 0, s).depth - project(ca.n, ca.e, 0, s).depth;
    });

    for (const cell of cells) {
      const corners = hexCorners(cell.q, cell.r, size).map((c) => project(c.n, c.e, 0, s));
      const worldCorners = hexCorners(cell.q, cell.r, size);
      const center = axialToWorld(cell.q, cell.r, size);
      const bandLift = tile_height * ALT_LIFT * s;

      // side faces, one color band per stacked tile (bottom-up)
      for (let level = 0; level < cell.stack.length; level++) {
        const mat = MATERIAL_COLORS[cell.stack[level]] ?? UNKNOWN;
        const y0 = level * bandLift;
        const y1 = (level + 1) * bandLift;
        for (let k = 0; k < 6; k++) {
          const a = worldCorners[k];
          const b = worldCorners[(k + 1) % 6];
          // camera-facing edges only: midpoint nearer the viewer than the center
          const midNE = (a.n + b.n) / 2 + (a.e + b.e) / 2;
          if (midNE >= center.n + center.e) continue;
          // west-ish faces in shadow, south-ish faces lit
          const dark = a.e + b.e < center.e * 2;
          const pa = corners[k];
          const pb = corners[(k + 1) % 6];
          g.poly([pa.x, pa.y - y0, pb.x, pb.y - y0, pb.x, pb.y - y1, pa.x, pa.y - y1])
            .fill({ color: dark ? mat.sideDark : mat.side })
            .stroke({ width: 1, color: 0x10141c, alpha: 0.25 });
        }
      }

      // top face in the top tile's color
      const topMat = MATERIAL_COLORS[cell.stack[cell.stack.length - 1]] ?? UNKNOWN;
      const topLift = cell.stack.length * bandLift;
      g.poly(corners.flatMap((p) => [p.x, p.y - topLift]))
        .fill({ color: topMat.top })
        .stroke({ width: 1, color: 0x10141c, alpha: 0.45 });
    }
  }
}
