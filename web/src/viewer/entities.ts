/** Mission entities, rendered generically by `kind` — a new kind is one entry
 * in RENDERERS; unknown kinds still show as a neutral marker.
 *
 * Static kinds skip their geometry rebuild while nothing changed (dirty-key,
 * the drawPads idiom); `animated` kinds (pulses, glows) redraw every frame.
 */

import { Container, Graphics, Text } from "pixi.js";
import type { EntityState } from "../shared/protocol";
import { ALT_LIFT, project, projectGround } from "./iso";
import type { Scene } from "./scene";
import { MATERIAL_COLORS, UNKNOWN_MATERIAL } from "./terrain";

export class EntityVis {
  root = new Container();
  g = new Graphics();
  shadow = new Graphics();
  label: Text | null = null;
  drawKey = "";

  constructor(public kind: string, scene: Scene) {
    this.root.addChild(this.g);
    scene.spriteLayer.addChild(this.root);
    scene.shadowLayer.addChild(this.shadow);
  }

  addLabel(text: string, color: number, size = 12, dy = 10): Text {
    this.label = new Text({
      text,
      style: { fontFamily: "Segoe UI, system-ui, sans-serif", fontSize: size,
               fill: color, fontWeight: "700", letterSpacing: 1 },
    });
    this.label.anchor.set(0.5, 0);
    this.label.position.set(0, dy);
    this.root.addChild(this.label);
    return this.label;
  }

  destroy(): void {
    this.root.destroy({ children: true });
    this.shadow.destroy();
  }
}

interface Pose {
  n: number;
  e: number;
  alt: number;
}

interface KindRenderer {
  /** time-based pulses/glows: redraw every frame, no dirty-key skip */
  animated?: boolean;
  /** one-time children (labels) at creation */
  init?(vis: EntityVis, ent: EntityState): void;
  /** altitude the sprite draws at (carried things hang below their carrier) */
  poseAlt?(ent: EntityState, alt: number): number;
  draw(vis: EntityVis, ent: EntityState, pose: Pose, drawAlt: number, s: number,
       timeMs: number): void;
}

/** Local screen-space hexagon (pointy-top), as a flat poly array. */
function hexPoly(radiusM: number, s: number): number[] {
  const pts: number[] = [];
  for (let k = 0; k < 6; k++) {
    const a = (Math.PI / 180) * (60 * k + 30);
    const p = project(radiusM * Math.sin(a), radiusM * Math.cos(a), 0, s);
    pts.push(p.x, p.y);
  }
  return pts;
}

const crate: KindRenderer = {
  poseAlt: (_ent, alt) => (alt > 0.5 ? Math.max(0, alt - 1.4) : alt),
  draw(vis, _ent, pose, drawAlt, s) {
    const g = vis.g;
    const u = Math.max(4, s * 1.15); // half-width of the cube
    g.poly([0, -u, u * 0.87, -u * 0.5, 0, 0, -u * 0.87, -u * 0.5])
      .fill({ color: 0xffc46b });
    g.poly([-u * 0.87, -u * 0.5, 0, 0, 0, u, -u * 0.87, u * 0.5])
      .fill({ color: 0xb87a2e });
    g.poly([u * 0.87, -u * 0.5, 0, 0, 0, u, u * 0.87, u * 0.5])
      .fill({ color: 0xdd9c44 });
    g.poly([0, -u, u * 0.87, -u * 0.5, 0, 0, -u * 0.87, -u * 0.5])
      .stroke({ width: 1, color: 0x6b4415 });
    if (drawAlt > 0.3) {
      const ground = projectGround(pose.n, pose.e, s);
      vis.shadow.ellipse(ground.x, ground.y, u, u * 0.5)
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};

const dropoff: KindRenderer = {
  animated: true,
  init(vis) {
    vis.addLabel("DROPOFF", 0x4ade80, 12, 10);
  },
  draw(vis, _ent, _pose, _drawAlt, s, timeMs) {
    const pulse = 0.75 + 0.25 * Math.sin(timeMs / 400);
    for (const [radius, alpha] of [[4.5, 0.9], [3.0, 0.55], [1.5, 0.35]] as const) {
      const r = radius * pulse;
      vis.g.poly([
        project(r, 0, 0, s).x, project(r, 0, 0, s).y,
        project(0, r, 0, s).x, project(0, r, 0, s).y,
        project(-r, 0, 0, s).x, project(-r, 0, 0, s).y,
        project(0, -r, 0, s).x, project(0, -r, 0, s).y,
      ]).stroke({ width: 2, color: 0x4ade80, alpha });
    }
    vis.root.zIndex = -10_000; // flat marker: always under drones/crates
  },
};

const tileSource: KindRenderer = {
  init(vis, ent) {
    const name = String(ent.data.material ?? "?").toUpperCase();
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    vis.addLabel(name, mat.top, 11, 12);
  },
  draw(vis, ent, _pose, _drawAlt, s) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    // a little pile: three flat hex slabs, one perched on top
    const slabs: Array<[number, number, number]> = [ // (dn, de, liftM)
      [0.9, -1.0, 0], [-0.6, 1.1, 0], [0.1, 0.1, 0.9],
    ];
    for (const [dn, de, lift] of slabs) {
      const at = project(dn, de, lift, s);
      const poly = hexPoly(1.5, s);
      const out: number[] = [];
      for (let i = 0; i < poly.length; i += 2) out.push(poly[i] + at.x, poly[i + 1] + at.y);
      vis.g.poly(out).fill({ color: mat.side })
        .stroke({ width: 1.5, color: mat.top, alpha: 0.9 });
    }
  },
};

const ghostTile: KindRenderer = {
  animated: true,
  init(vis, ent) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    vis.addLabel("", mat.top, 10, 6);
  },
  draw(vis, ent, _pose, _drawAlt, s, timeMs) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    const size = Number(ent.data.size ?? 3);
    const pulse = 0.55 + 0.35 * Math.sin(timeMs / 350);
    vis.g.poly(hexPoly(size * 0.92, s))
      .stroke({ width: 2, color: mat.top, alpha: pulse });
    if (vis.label) {
      const have = Number(ent.data.have ?? 0);
      const need = Number(ent.data.need ?? 1);
      vis.label.text = `${have}/${need}`;
    }
  },
};

const furnace: KindRenderer = {
  animated: true,
  draw(vis, _ent, _pose, _drawAlt, s, timeMs) {
    const glow = 0.35 + 0.2 * Math.sin(timeMs / 300);
    vis.g.circle(0, 0, Math.max(6, s * 2.6)).fill({ color: 0xff9a3c, alpha: glow * 0.5 });
    // squat clay prism with an ember-lit top
    const base = hexPoly(2.2, s);
    const lift = 1.6 * ALT_LIFT * s; // a squat ~1.6 m chimney
    const top: number[] = [];
    for (let i = 0; i < base.length; i += 2) top.push(base[i], base[i + 1] - lift);
    vis.g.poly(base).fill({ color: 0x8f5a3c });
    vis.g.poly(top).fill({ color: 0xc98d68 }).stroke({ width: 1, color: 0x10141c, alpha: 0.5 });
    vis.g.circle(0, -lift, Math.max(2.5, s * 1.0)).fill({ color: 0xffb054, alpha: glow + 0.3 });
  },
};

const tileCarried: KindRenderer = {
  poseAlt: (_ent, alt) => (alt > 0.5 ? Math.max(0, alt - 1.4) : alt),
  draw(vis, ent, pose, drawAlt, s) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    vis.g.poly(hexPoly(1.4, s)).fill({ color: mat.top })
      .stroke({ width: 1, color: mat.sideDark });
    if (drawAlt > 0.3) {
      const ground = projectGround(pose.n, pose.e, s);
      vis.shadow.ellipse(ground.x, ground.y, Math.max(4, s * 1.2), Math.max(2, s * 0.6))
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};

const fallback: KindRenderer = {
  draw(vis, _ent, _pose, _drawAlt, s) {
    // unknown kind: neutral marker so future missions still show something
    vis.g.circle(0, 0, Math.max(4, s)).fill({ color: 0x8899bb, alpha: 0.8 });
  },
};

const RENDERERS: Record<string, KindRenderer> = {
  crate,
  dropoff,
  tile_source: tileSource,
  ghost_tile: ghostTile,
  furnace,
  tile_carried: tileCarried,
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
        this.map.set(ent.id, vis);
        renderer.init?.(vis, ent);
      }
      const pose = interp.get(ent.id) ?? ent;
      const drawAlt = renderer.poseAlt ? renderer.poseAlt(ent, pose.alt) : pose.alt;
      const p = project(pose.n, pose.e, drawAlt, s);
      vis.root.position.set(p.x, p.y);
      vis.root.zIndex = p.depth - 0.1; // just behind a drone at the same spot

      const key = `${pose.n.toFixed(2)}|${pose.e.toFixed(2)}|${drawAlt.toFixed(2)}|` +
        `${s.toFixed(4)}|${JSON.stringify(ent.data)}`;
      if (!renderer.animated && key === vis.drawKey) continue; // static & unchanged
      vis.drawKey = key;
      vis.g.clear();
      vis.shadow.clear();
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
