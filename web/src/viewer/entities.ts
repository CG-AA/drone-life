/** Mission entities, rendered generically by `kind` — a new kind is one entry
 * in RENDERERS; unknown kinds still show as a neutral marker.
 *
 * Static kinds skip their geometry rebuild while nothing changed (dirty-key,
 * the drawPads idiom); `animated` kinds (pulses, glows) redraw every frame.
 */

import { Container, Graphics, Text } from "pixi.js";
import type { EntityState } from "../shared/protocol";
import { COLORS, FONT_UI, REDUCED_MOTION } from "../shared/theme";
import { ALT_LIFT, project, projectGround } from "./iso";
import type { Scene } from "./scene";
import { MATERIAL_COLORS, UNKNOWN_MATERIAL } from "./terrain";

/** Decorative pulse a + b·sin(t/period); a steady midpoint under reduced motion. */
function pulse(timeMs: number, period: number, base: number, amp: number): number {
  return REDUCED_MOTION ? base : base + amp * Math.sin(timeMs / period);
}

export class EntityVis {
  root = new Container();
  g = new Graphics();
  /** depth-sorted with tiles; rests on the surface under the entity */
  shadow = new Graphics();
  /** flat ground marking (range rings) that must never occlude anything */
  decal = new Graphics();
  label: Text | null = null;
  drawKey = "";

  constructor(public kind: string, private scene: Scene) {
    this.root.addChild(this.g);
    scene.spriteLayer.addChild(this.root);
    scene.spriteLayer.addChild(this.shadow);
    scene.decalLayer.addChild(this.decal);
  }

  addLabel(text: string, color: number, size = 12, dy = 10): Text {
    this.label = new Text({
      text,
      style: { fontFamily: FONT_UI, fontSize: size,
               fill: color, fontWeight: "700", letterSpacing: 1 },
      resolution: this.scene.textResolution,
    });
    this.label.anchor.set(0.5, 0);
    this.label.position.set(0, dy);
    this.root.addChild(this.label);
    return this.label;
  }

  destroy(): void {
    this.root.destroy({ children: true });
    this.shadow.destroy();
    this.decal.destroy();
  }
}

interface Pose {
  n: number;
  e: number;
  alt: number;
  /** altitude of the surface below (tile stack top, or 0 on bare floor) */
  groundAlt: number;
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
    if (drawAlt - pose.groundAlt > 0.3) {
      const ground = project(pose.n, pose.e, pose.groundAlt, s);
      vis.shadow.ellipse(ground.x, ground.y, u, u * 0.5)
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};

const dropoff: KindRenderer = {
  animated: true,
  init(vis) {
    vis.addLabel("DROPOFF", COLORS.ok, 12, 10);
  },
  draw(vis, _ent, _pose, _drawAlt, s, timeMs) {
    const breathe = pulse(timeMs, 400, 0.75, 0.25);
    for (const [radius, alpha] of [[4.5, 0.9], [3.0, 0.55], [1.5, 0.35]] as const) {
      const r = radius * breathe;
      vis.g.poly([
        project(r, 0, 0, s).x, project(r, 0, 0, s).y,
        project(0, r, 0, s).x, project(0, r, 0, s).y,
        project(-r, 0, 0, s).x, project(-r, 0, 0, s).y,
        project(0, -r, 0, s).x, project(0, -r, 0, s).y,
      ]).stroke({ width: 2, color: COLORS.ok, alpha });
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
    vis.g.poly(hexPoly(size * 0.92, s))
      .stroke({ width: 2, color: mat.top, alpha: pulse(timeMs, 350, 0.55, 0.35) });
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
    const glow = pulse(timeMs, 300, 0.35, 0.2);
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
    if (drawAlt - pose.groundAlt > 0.3) {
      const ground = project(pose.n, pose.e, pose.groundAlt, s);
      vis.shadow.ellipse(ground.x, ground.y, Math.max(4, s * 1.2), Math.max(2, s * 0.6))
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};

const troop: KindRenderer = {
  animated: true,
  draw(vis, ent, pose, drawAlt, s, timeMs) {
    const chewing = Boolean(ent.data.chewing);
    const dir = (Number(ent.data.dir ?? 0) * Math.PI) / 180; // server sends degrees
    const jitter = chewing && !REDUCED_MOTION ? Math.sin(timeMs / 30) * s * 0.25 : 0;
    const bob = chewing || REDUCED_MOTION ? 0 : Math.abs(Math.sin(timeMs / 120)) * s * 0.35;
    const r = Math.max(3.5, s * 1.1);
    vis.g.circle(jitter, -bob, r).fill({ color: 0xe14b4b })
      .stroke({ width: 1.5, color: 0x7c1f1f });
    const tip = project(Math.cos(dir) * 1.8, Math.sin(dir) * 1.8, 0, s);
    vis.g.moveTo(jitter, -bob).lineTo(jitter + tip.x, -bob + tip.y)
      .stroke({ width: 2, color: 0xffd0d0 });
    if (drawAlt - pose.groundAlt > 0.3) { // airborne (e.g. knocked off a wall)
      const ground = project(pose.n, pose.e, pose.groundAlt, s);
      vis.shadow.ellipse(ground.x, ground.y, r, r * 0.5)
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};

const keep: KindRenderer = {
  animated: true,
  init(vis) {
    vis.addLabel("KEEP", 0xf3d27a, 12, 14);
  },
  draw(vis, ent, _pose, _drawAlt, s, timeMs) {
    const hp = Number(ent.data.hp ?? 0);
    const max = Number(ent.data.max ?? 1);
    const low = hp <= 3;
    // ~2.8 Hz danger flash; a steady bright outline under reduced motion
    const flash = low ? pulse(timeMs, 180, 0.5, 0.5) : 0;
    const base = hexPoly(2.6, s);
    const lift = 3.0 * ALT_LIFT * s;
    const top: number[] = [];
    for (let i = 0; i < base.length; i += 2) top.push(base[i], base[i + 1] - lift);
    vis.g.poly(base).fill({ color: 0x6f6a8f });
    vis.g.poly(top).fill({ color: 0xa39ac9 })
      .stroke({ width: 2, color: low ? 0xff5050 : 0x2c2a3d, alpha: low ? 0.4 + flash * 0.6 : 0.8 });
    const w = Math.max(3, s * 0.8); // hp pips, 5 per row above the roof
    for (let i = 0; i < max; i++) {
      const x = ((i % 5) - 2) * (w + 2);
      const y = -lift - w * 2.2 - Math.floor(i / 5) * (w * 1.7);
      vis.g.rect(x - w / 2, y, w, w * 1.4)
        .fill({ color: i < hp ? COLORS.ok : 0x333344, alpha: 0.95 });
    }
  },
};

const tower: KindRenderer = {
  animated: true,
  draw(vis, ent, pose, _drawAlt, s, timeMs) {
    const glow = pulse(timeMs, 250, 0.55, 0.25);
    const r = Math.max(4, s * 1.3);
    // glow dome capping the steel stack (the stack itself is terrain)
    vis.g.circle(0, -r * 0.3, r * 1.8).fill({ color: 0x7cc7ff, alpha: glow * 0.2 });
    vis.g.ellipse(0, 0, r * 1.2, r * 0.6).fill({ color: 0x274a63 });
    vis.g.circle(0, -r * 0.5, r * 0.8).fill({ color: 0x9fd8ff, alpha: 0.6 + glow * 0.4 });
    const range = Number(ent.data.range ?? 0); // faint ring on the ground
    if (range > 0) {
      const ring: number[] = [];
      for (let k = 0; k < 24; k++) {
        const a = (Math.PI / 12) * k;
        const p = projectGround(pose.n + range * Math.cos(a),
                                pose.e + range * Math.sin(a), s);
        ring.push(p.x, p.y);
      }
      vis.decal.poly(ring).stroke({ width: 1.5, color: 0x7cc7ff, alpha: 0.22 });
    }
  },
};

const beam: KindRenderer = {
  animated: true,
  draw(vis, ent, pose, _drawAlt, s, timeMs) {
    // origin = tower top (our pose); target world coords ride in data
    const src = project(pose.n, pose.e, pose.alt, s);
    const dst = project(Number(ent.data.tn ?? pose.n), Number(ent.data.te ?? pose.e),
                        Number(ent.data.talt ?? 0), s);
    const dx = dst.x - src.x;
    const dy = dst.y - src.y;
    // ~4 Hz flicker is a photosensitivity risk projected large: steady when reduced
    const flick = pulse(timeMs, 40, 0.6, 0.4);
    vis.g.moveTo(0, 0).lineTo(dx, dy).stroke({ width: 3, color: 0x9fd8ff, alpha: flick });
    vis.g.moveTo(0, 0).lineTo(dx, dy).stroke({ width: 1, color: 0xffffff, alpha: 0.9 });
    vis.g.circle(dx, dy, Math.max(3, s) * flick).fill({ color: 0xcfeaff, alpha: 0.8 });
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
  troop,
  keep,
  tower,
  beam,
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
