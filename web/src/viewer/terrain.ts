/** Hex-tile terrain: material-banded prisms, one Graphics per cell.
 *
 * Each prism lives in the scene's depth-sorted sprite layer with its own
 * zIndex, so drones and entities interleave with the tiles correctly: a drone
 * standing behind a wall is hidden by it, one in front paints over it. (A
 * single terrain layer under every sprite made far-side drones float over
 * near walls — the "confusing z-order".)
 *
 * Event-driven — a full rebuild happens only when a tiles message arrives or
 * the scene rescales, never per frame. Tiles are static between messages.
 */

import { Graphics } from "pixi.js";
import type { TilesData } from "../shared/protocol";
import { axialToWorld, hexCorners, PRISM_DEPTH_BIAS, worldToAxial } from "./hex";
import { ALT_LIFT, project } from "./iso";
import type { Ground, Scene } from "./scene";

export interface MaterialColors {
  top: number;
  side: number;
  sideDark: number;
}

export const MATERIAL_COLORS: Record<string, MaterialColors> = {
  steel: { top: 0xa8b4c4, side: 0x77879c, sideDark: 0x566374 },
  clay: { top: 0xc98d68, side: 0xa9714c, sideDark: 0x8f5a3c },
};
export const UNKNOWN_MATERIAL: MaterialColors =
  { top: 0x8a8f98, side: 0x6a6f78, sideDark: 0x4e535c };

export class TerrainRenderer {
  private prisms: Graphics[] = [];
  private data: TilesData | null = null;
  private heights = new Map<string, number>(); // "q,r" -> stack count
  private drawnScale = 0;

  constructor(private scene: Scene) {
    scene.groundAt = (n, e) => this.groundAt(n, e);
  }

  set(data: TilesData): void {
    this.data = data;
    this.heights.clear();
    for (const cell of data.cells) this.heights.set(`${cell.q},${cell.r}`, cell.stack.length);
    this.scene.setHexGeometry(data.geometry.size);
    this.render();
  }

  /** The surface under a world point: the top of the tile stack there (so a
   * shadow lands on the wall, not under it), painted just above that prism. On
   * bare ground the point's own depth is the right order against every prism. */
  groundAt(n: number, e: number): Ground {
    const bare: Ground = { alt: 0, zIndex: project(n, e, 0, 1).depth };
    if (!this.data) return bare;
    const { size, tile_height } = this.data.geometry;
    const [q, r] = worldToAxial(n, e, size);
    const stack = this.heights.get(`${q},${r}`);
    if (!stack) return bare;
    const c = axialToWorld(q, r, size);
    return { alt: stack * tile_height,
             zIndex: project(c.n, c.e, 0, 1).depth - PRISM_DEPTH_BIAS * size + 1e-3 };
  }

  /** Called from the ticker: rebuilds only after a resize changed the scale. */
  tick(): void {
    if (this.data && this.scene.scale !== this.drawnScale) this.render();
  }

  private render(): void {
    for (const g of this.prisms) g.destroy();
    this.prisms = [];
    const data = this.data;
    if (!data) return;
    const s = this.scene.scale;
    this.drawnScale = s;
    const { size, tile_height } = data.geometry;
    const bandLift = tile_height * ALT_LIFT * s;

    for (const cell of data.cells) {
      const worldCorners = hexCorners(cell.q, cell.r, size);
      const center = axialToWorld(cell.q, cell.r, size);
      const origin = project(center.n, center.e, 0, s);
      // local coords around the cell center so the prism can be positioned
      const corners = worldCorners.map((c) => {
        const p = project(c.n, c.e, 0, s);
        return { x: p.x - origin.x, y: p.y - origin.y };
      });
      const g = new Graphics();

      // side faces, one color band per stacked tile (bottom-up)
      for (let level = 0; level < cell.stack.length; level++) {
        const mat = MATERIAL_COLORS[cell.stack[level]] ?? UNKNOWN_MATERIAL;
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
      const topMat = MATERIAL_COLORS[cell.stack[cell.stack.length - 1]] ?? UNKNOWN_MATERIAL;
      const topLift = cell.stack.length * bandLift;
      g.poly(corners.flatMap((p) => [p.x, p.y - topLift]))
        .fill({ color: topMat.top })
        .stroke({ width: 1, color: 0x10141c, alpha: 0.45 });

      g.position.set(origin.x, origin.y);
      // pushed slightly back so whatever stands on the cell paints over it
      g.zIndex = origin.depth - PRISM_DEPTH_BIAS * size;
      this.scene.spriteLayer.addChild(g);
      this.prisms.push(g);
    }
  }
}
