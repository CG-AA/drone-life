/** Drone sprites: body with heading tick, name tag, altitude stem + ground
 * shadow (the 2.5D cue), fading trail. One DroneVis per drone id. */

import { Container, Graphics, Text } from "pixi.js";
import type { DroneState } from "../shared/protocol";
import { project, projectGround } from "./iso";
import { slotColor } from "./colors";
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
      style: { fontFamily: "Segoe UI, system-ui, sans-serif", fontSize: 13,
               fill: this.color, fontWeight: "700" },
    });
    this.tag.anchor.set(0.5, 0);
    this.root.addChild(this.body, this.tag);
    scene.spriteLayer.addChild(this.root);
    scene.shadowLayer.addChild(this.shadow);
    scene.trailLayer.addChild(this.trail);
  }

  destroy(): void {
    this.root.destroy({ children: true });
    this.shadow.destroy();
    this.trail.destroy();
  }

  update(d: DroneState, n: number, e: number, alt: number, yaw: number, s: number): void {
    const p = project(n, e, alt, s);
    const ground = projectGround(n, e, s);
    this.root.position.set(p.x, p.y);
    this.root.zIndex = p.depth;

    const r = Math.max(5, s * 1.7);
    const dim = !d.connected && !d.crashed;
    this.root.alpha = dim ? 0.55 : 1;

    const body = this.body;
    body.clear();
    if (d.crashed) {
      body.circle(0, 0, r).fill({ color: 0x552222 }).stroke({ width: 2, color: 0xff5c5c });
      body.moveTo(-r * 0.6, -r * 0.6).lineTo(r * 0.6, r * 0.6)
        .moveTo(r * 0.6, -r * 0.6).lineTo(-r * 0.6, r * 0.6)
        .stroke({ width: 2, color: 0xff5c5c });
    } else {
      // rotor cross behind the hull, rotated by yaw
      const hn = Math.cos(yaw);
      const he = Math.sin(yaw);
      const tip = project(n + hn * 2.2, e + he * 2.2, alt, s);
      body.circle(0, 0, r)
        .fill({ color: d.armed ? this.color : 0x39445c })
        .stroke({ width: 1.5, color: 0x0b0e14, alpha: 0.9 });
      body.moveTo(0, 0).lineTo(tip.x - p.x, tip.y - p.y)
        .stroke({ width: 2.5, color: 0x0b0e14, alpha: 0.85 });
      if (d.carrying) {
        body.rect(-r * 0.45, r * 0.7, r * 0.9, r * 0.7)
          .fill({ color: 0xffb347 }).stroke({ width: 1, color: 0x7a4a12 });
      }
    }
    this.tag.position.set(0, r + (d.carrying ? r * 0.8 : 0) + 3);

    // shadow + altitude stem
    const sh = this.shadow;
    sh.clear();
    if (alt > 0.15) {
      const shrink = Math.max(0.45, 1 - alt / 90);
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
      vis.update(d, pose.n, pose.e, pose.alt, pose.yaw, this.scene.scale);
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
