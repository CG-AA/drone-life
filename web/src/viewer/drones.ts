/** Drone sprites: body with heading tick, name tag, altitude stem + ground
 * shadow (the 2.5D cue), fading trail. One DroneVis per drone id.
 *
 * The shadow rests on whatever is under the drone — bare floor or the top of
 * a tile stack — and is depth-sorted with the tiles, so a drone hovering
 * over a wall casts onto the wall instead of vanishing beneath it. */

import { Container, Graphics, Text } from "pixi.js";
import type { DroneState } from "../shared/protocol";
import { COLORS, FONT_UI } from "../shared/theme";
import { project } from "./iso";
import { parseHex, slotColor } from "./colors";
import type { Scene } from "./scene";

const TRAIL_LEN = 120;
const TRAIL_MIN_STEP = 0.6; // meters moved before we record a trail point

class DroneVis {
  root = new Container();
  body = new Graphics();
  tag: Text;
  shadow = new Graphics();
  trail = new Graphics();
  points: { n: number; e: number; alt: number }[] = [];
  color: number;

  constructor(state: DroneState, scene: Scene) {
    this.color = slotColor(state.sysid);
    this.tag = new Text({
      text: state.name,
      // the dark stroke is what makes a name readable when the drone flies
      // over a steel stack — tile tops are nearly white, so colored fill
      // alone drops to ~1.5:1 there
      style: {
        fontFamily: FONT_UI, fontSize: 15, fill: this.color, fontWeight: "700",
        stroke: { color: COLORS.ink, width: 3 },
      },
      resolution: scene.textResolution,
    });
    this.tag.anchor.set(0.5, 0);
    this.root.addChild(this.body, this.tag);
    scene.spriteLayer.addChild(this.root);
    scene.spriteLayer.addChild(this.shadow);
    scene.trailLayer.addChild(this.trail);
  }

  destroy(): void {
    this.root.destroy({ children: true });
    this.shadow.destroy();
    this.trail.destroy();
  }

  update(d: DroneState, n: number, e: number, alt: number, yaw: number, scene: Scene): void {
    const s = scene.scale;
    const textRes = scene.textResolution;
    // the tag is rasterized once at creation; re-point it when the display
    // density changes or it stays soft
    if (this.tag.resolution !== textRes) this.tag.resolution = textRes;
    const p = project(n, e, alt, s);
    const surface = scene.groundAt(n, e);
    const ground = project(n, e, surface.alt, s);
    this.root.position.set(p.x, p.y);
    this.root.zIndex = p.depth;
    this.shadow.zIndex = surface.zIndex;

    const r = Math.max(5, s * 1.7);
    const dim = !d.connected && !d.crashed;
    this.root.alpha = dim ? 0.55 : 1;

    const pilot = d.pilot ?? {};
    // bought looks: fill and outline are the pilot's own; the name tag keeps
    // the slot colour, whose AA contrast on the floor is guaranteed
    const fill = parseHex(pilot.colour) ?? this.color;
    const outline = parseHex(pilot.outline);
    const tiers = tierCount(pilot);
    const body = this.body;
    body.clear();
    if (d.crashed) {
      body.circle(0, 0, r).fill({ color: 0x552222 }).stroke({ width: 2, color: COLORS.danger });
      body.moveTo(-r * 0.6, -r * 0.6).lineTo(r * 0.6, r * 0.6)
        .moveTo(r * 0.6, -r * 0.6).lineTo(-r * 0.6, r * 0.6)
        .stroke({ width: 2, color: COLORS.danger });
    } else {
      // rotor cross behind the hull, rotated by yaw
      const hn = Math.cos(yaw);
      const he = Math.sin(yaw);
      const tip = project(n + hn * 2.2, e + he * 2.2, alt, s);
      body.circle(0, 0, r)
        .fill({ color: d.armed ? fill : COLORS.disarmed })
        .stroke(outline === null
          ? { width: 1.5, color: COLORS.ink, alpha: 0.9 }
          : { width: 2.5, color: outline, alpha: 1 });
      body.moveTo(0, 0).lineTo(tip.x - p.x, tip.y - p.y)
        .stroke({ width: 2.5, color: COLORS.ink, alpha: 0.85 });
      // upgrade badge: one chevron per bought tier, above the hull — a shape,
      // not a colour, so it reads on a washed-out projector
      for (let i = 0; i < tiers; i++) {
        const y = -r - 3 - i * 4;
        body.moveTo(-3, y).lineTo(0, y - 3).lineTo(3, y)
          .stroke({ width: 1.5, color: COLORS.gold, alpha: 0.95 });
      }
      if (d.carrying) {
        body.rect(-r * 0.45, r * 0.7, r * 0.9, r * 0.7)
          .fill({ color: COLORS.warn }).stroke({ width: 1, color: 0x7a4a12 });
      }
    }
    this.tag.position.set(0, r + (d.carrying ? r * 0.8 : 0) + 3);

    // shadow + altitude stem
    const sh = this.shadow;
    sh.clear();
    const above = alt - surface.alt;
    if (above > 0.15) {
      const shrink = Math.max(0.45, 1 - above / 90);
      sh.ellipse(ground.x, ground.y, r * shrink, r * shrink * 0.5)
        .fill({ color: 0x000000, alpha: 0.35 });
      sh.moveTo(ground.x, ground.y).lineTo(p.x, p.y)
        .stroke({ width: 1, color: this.color, alpha: 0.22 });
    }

    // trail
    const last = this.points[this.points.length - 1];
    if (!last || Math.hypot(n - last.n, e - last.e, alt - last.alt) > TRAIL_MIN_STEP) {
      this.points.push({ n, e, alt });
      if (this.points.length > TRAIL_LEN) this.points.shift();
    }
    const tr = this.trail;
    tr.clear();
    if (this.points.length > 1 && !d.on_ground) {
      for (let i = 1; i < this.points.length; i++) {
        const a = project(this.points[i - 1].n, this.points[i - 1].e, this.points[i - 1].alt, s);
        const b = project(this.points[i].n, this.points[i].e, this.points[i].alt, s);
        tr.moveTo(a.x, a.y).lineTo(b.x, b.y)
          .stroke({ width: 1.5, color: this.color, alpha: 0.28 * (i / this.points.length) });
      }
    }
  }

  clearTrail(): void {
    this.points.length = 0;
    this.trail.clear();
  }
}

/** Bought tiers, capped so a maxed pilot wears five chevrons, not seven. */
export function tierCount(pilot: Record<string, unknown>): number {
  const n = (v: unknown): number => (typeof v === "number" && v > 0 ? Math.floor(v) : 0);
  return Math.min(5, n(pilot.zap) + n(pilot.speed) + n(pilot.tower));
}

export class DroneRenderer {
  private map = new Map<string, DroneVis>();

  constructor(private scene: Scene) {}

  /** interp: already-interpolated pose per drone id. */
  sync(drones: DroneState[],
       interp: Map<string, { n: number; e: number; alt: number; yaw: number }>): void {
    const seen = new Set<string>();
    for (const d of drones) {
      seen.add(d.id);
      let vis = this.map.get(d.id);
      if (!vis) {
        vis = new DroneVis(d, this.scene);
        this.map.set(d.id, vis);
      }
      const pose = interp.get(d.id) ?? { n: d.n, e: d.e, alt: d.alt, yaw: d.yaw };
      vis.update(d, pose.n, pose.e, pose.alt, pose.yaw, this.scene);
    }
    for (const [id, vis] of this.map) {
      if (!seen.has(id)) {
        vis.destroy();
        this.map.delete(id);
      }
    }
  }

  clearTrails(): void {
    for (const vis of this.map.values()) vis.clearTrail();
  }
}
