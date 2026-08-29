/** Per-pilot callouts on the wall: when a feed event credits a student, a
 * ring flashes around their drone and the points float up from it. This is
 * what turns "+2: Alice zapped a grunt" in the corner into "that was ME" for
 * twenty people at once. Transient, self-expiring; the server knows nothing. */

import { Container, Graphics, Text } from "pixi.js";
import type { EventData } from "../shared/protocol";
import { COLORS, FONT_UI, REDUCED_MOTION } from "../shared/theme";
import { project } from "./iso";
import type { Scene } from "./scene";

export interface Callout { text: string; color: number }

/** Which events deserve a burst at the pilot's drone, and what it says.
 * Pure so the mapping is testable. Events without a student never burst. */
export function calloutFor(ev: EventData): Callout | null {
  if (!ev.student_id) return null;
  const raw = Number(ev.data.points);
  const pts = Number.isFinite(raw) ? raw : null;
  const signed = (n: number): string => (n > 0 ? `+${n}` : `${n}`);
  switch (ev.kind) {
    case "score":
    case "delivery":
    case "tile_placed":
      return pts !== null && pts !== 0 ? { text: signed(pts), color: COLORS.gold } : null;
    case "tower_up":
      return { text: `${signed(pts ?? 15)} TOWER`, color: 0x9fd8ff };
    case "boss_down":
      return { text: `${signed(pts ?? 20)} BOSS!`, color: COLORS.gold };
    case "pickup":
      return { text: "got it", color: 0x9fb8d8 };
    default:
      return null;
  }
}

const LIFE_MS = 1100;
const RISE_M = 5; // meters of altitude the text climbs over its life

interface Fx {
  born: number;
  n: number;
  e: number;
  alt: number;
  color: number;
  root: Container;
  g: Graphics;
  t: Text;
}

export class EffectsRenderer {
  private fx: Fx[] = [];

  constructor(private scene: Scene) {}

  burst(pose: { n: number; e: number; alt: number }, c: Callout, now: number): void {
    const root = new Container();
    const g = new Graphics();
    const t = new Text({
      text: c.text,
      style: { fontFamily: FONT_UI, fontSize: 22, fontWeight: "800", fill: c.color,
               stroke: { color: COLORS.ink, width: 4 } },
      resolution: this.scene.textResolution,
    });
    t.anchor.set(0.5, 1);
    root.addChild(g, t);
    root.zIndex = Number.MAX_SAFE_INTEGER; // over every sprite at that spot
    this.scene.spriteLayer.addChild(root);
    this.fx.push({ born: now, n: pose.n, e: pose.e, alt: pose.alt, color: c.color, root, g, t });
  }

  tick(now: number): void {
    const s = this.scene.scale;
    this.fx = this.fx.filter((f) => {
      const k = Math.min(1, (now - f.born) / LIFE_MS);
      if (k >= 1) {
        f.root.destroy({ children: true });
        return false;
      }
      const rise = REDUCED_MOTION ? RISE_M * 0.5 : RISE_M * k;
      const p = project(f.n, f.e, f.alt + rise, s);
      f.root.position.set(p.x, p.y);
      const fade = 1 - k * k;
      f.t.alpha = fade;
      f.t.position.set(0, -Math.max(8, s * 1.5));
      f.g.clear();
      // an expanding ring at the drone, thick then thin, gone by the end
      const r = Math.max(6, s * 1.6) * (REDUCED_MOTION ? 1.6 : 0.8 + k * 1.8);
      f.g.circle(0, s * 1.2 + (REDUCED_MOTION ? 0 : rise * s * 0.9), r)
        .stroke({ width: Math.max(1.5, 4 * (1 - k)), color: f.color, alpha: fade });
      return true;
    });
  }
}
