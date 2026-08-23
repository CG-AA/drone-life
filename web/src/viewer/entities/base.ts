/** Shared primitives for the per-mission kind renderers. */

import { Container, Graphics, Text } from "pixi.js";
import type { EntityState } from "../../shared/protocol";
import { FONT_UI, REDUCED_MOTION } from "../../shared/theme";
import { project } from "../iso";
import type { Scene } from "../scene";

/** Decorative pulse a + b·sin(t/period); a steady midpoint under reduced motion. */
export function pulse(timeMs: number, period: number, base: number, amp: number): number {
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

export interface Pose {
  n: number;
  e: number;
  alt: number;
  /** altitude of the surface below (tile stack top, or 0 on bare floor) */
  groundAlt: number;
}

export interface KindRenderer {
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
export function hexPoly(radiusM: number, s: number): number[] {
  const pts: number[] = [];
  for (let k = 0; k < 6; k++) {
    const a = (Math.PI / 180) * (60 * k + 30);
    const p = project(radiusM * Math.sin(a), radiusM * Math.cos(a), 0, s);
    pts.push(p.x, p.y);
  }
  return pts;
}
