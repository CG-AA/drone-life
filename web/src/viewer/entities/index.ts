/** Mission entities, rendered generically by `kind` — a new kind is one
 * renderer in its mission's module plus one entry in RENDERERS; unknown kinds
 * still show as a neutral marker.
 *
 * Static kinds skip their geometry rebuild while nothing changed (dirty-key,
 * the drawPads idiom); `animated` kinds (pulses, glows) redraw every frame.
 */

import type { EntityState } from "../../shared/protocol";
import { project } from "../iso";
import type { Scene } from "../scene";
import { EntityVis, type KindRenderer, type Pose } from "./base";
import { tileCarried, tileSource, furnace, ghostTile } from "./building";
import { crate, dropoff } from "./delivery";
import { beacon, beam, bell, bellRing, gate, keep, poof, questMark, tower, troop, zapArc }
  from "./siege";

export { EntityVis, type KindRenderer, type Pose } from "./base";

const fallback: KindRenderer = {
  draw(vis, _ent, _pose, _drawAlt, s) {
    // unknown kind: neutral marker so future missions still show something
    vis.g.circle(0, 0, Math.max(4, s)).fill({ color: 0x8899bb, alpha: 0.8 });
  },
};

/** kind -> renderer, mirroring the server's MISSIONS registry style. */
const RENDERERS: Record<string, KindRenderer> = {
  crate,
  dropoff,
  tile_source: tileSource,
  ghost_tile: ghostTile,
  furnace,
  tile_carried: tileCarried,
  troop,
  keep,
  tower,
  beam,
  zap_arc: zapArc,
  poof,
  gate,
  quest_mark: questMark,
  beacon,
  bell,
  bell_ring: bellRing,
};

export class EntityRenderer {
  private map = new Map<string, EntityVis>();

  constructor(private scene: Scene) {}

  sync(entities: EntityState[],
       interp: Map<string, { n: number; e: number; alt: number }>,
       timeMs: number): void {
    const s = this.scene.scale;
    const seen = new Set<string>();
    for (const ent of entities) {
      seen.add(ent.id);
      const renderer = RENDERERS[ent.kind] ?? fallback;
      let vis = this.map.get(ent.id);
      if (!vis) {
        vis = new EntityVis(ent.kind, this.scene);
        vis.bornMs = timeMs;
        this.map.set(ent.id, vis);
        renderer.init?.(vis, ent);
      }
      // labels rasterize once; re-point them when the display density changes
      if (vis.label && vis.label.resolution !== this.scene.textResolution) {
        vis.label.resolution = this.scene.textResolution;
      }
      const ip = interp.get(ent.id) ?? ent;
      const surface = this.scene.groundAt(ip.n, ip.e);
      const pose: Pose = { n: ip.n, e: ip.e, alt: ip.alt, groundAlt: surface.alt };
      const drawAlt = renderer.poseAlt ? renderer.poseAlt(ent, pose.alt) : pose.alt;
      const p = project(pose.n, pose.e, drawAlt, s);
      vis.root.position.set(p.x, p.y);
      vis.root.zIndex = p.depth - 0.1; // just behind a drone at the same spot
      vis.shadow.zIndex = surface.zIndex;

      const key = `${pose.n.toFixed(2)}|${pose.e.toFixed(2)}|${drawAlt.toFixed(2)}|` +
        `${surface.alt}|${s.toFixed(4)}|${JSON.stringify(ent.data)}`;
      if (!renderer.animated && key === vis.drawKey) continue; // static & unchanged
      vis.drawKey = key;
      vis.g.clear();
      vis.shadow.clear();
      vis.decal.clear();
      renderer.draw(vis, ent, pose, drawAlt, s, timeMs);
    }
    for (const [id, vis] of this.map) {
      if (!seen.has(id)) {
        vis.destroy();
        this.map.delete(id);
      }
    }
  }
}
