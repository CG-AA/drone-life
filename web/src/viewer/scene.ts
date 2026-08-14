/** Pixi stage: layers, arena grid with coordinate labels, spawn pads. */

import { Application, Container, Graphics, Text } from "pixi.js";
import type { PadState } from "../shared/protocol";
import { ALT_LIFT, fitScale, project } from "./iso";
import { slotColor } from "./colors";

const GRID_STEP = 20;

export class Scene {
  app = new Application();
  world = new Container();
  gridLayer = new Graphics();
  gridLabels = new Container();
  padLayer = new Container();
  trailLayer = new Container();
  shadowLayer = new Container();
  spriteLayer = new Container(); // drones + entities, depth-sorted

  scale = 3;
  half = 100;
  altMax = 60;
  private padsKey = "";

  async init(): Promise<void> {
    await this.app.init({ background: 0x0e1116, resizeTo: window, antialias: true });
    document.body.appendChild(this.app.canvas);
    this.spriteLayer.sortableChildren = true;
    this.world.addChild(this.gridLayer, this.gridLabels, this.padLayer, this.trailLayer,
                        this.shadowLayer, this.spriteLayer);
    this.app.stage.addChild(this.world);
    window.addEventListener("resize", () => this.layout());
    this.layout();
  }

  setArena(half: number, altMax: number): void {
    this.half = half;
    this.altMax = altMax;
    this.layout();
  }

  layout(): void {
    const w = this.app.renderer.width;
    const h = this.app.renderer.height;
    this.scale = fitScale(this.half, this.altMax, w, h);
    // ground diamond is vertically centered; sky headroom sits above it
    this.world.position.set(w / 2, h / 2 + (this.altMax * ALT_LIFT * this.scale) / 2);
    this.drawGrid();
    this.padsKey = ""; // force pad redraw at the new scale
  }

  private drawGrid(): void {
    const g = this.gridLayer;
    const s = this.scale;
    const H = this.half;
    g.clear();
    this.gridLabels.removeChildren();

    const corners = [
      project(H, H, 0, s), project(-H, H, 0, s),
      project(-H, -H, 0, s), project(H, -H, 0, s),
    ];
    g.poly(corners.flatMap((p) => [p.x, p.y])).fill({ color: 0x151b28 });

    for (let v = -H; v <= H; v += GRID_STEP) {
      const a = project(v, -H, 0, s);
      const b = project(v, H, 0, s);
      g.moveTo(a.x, a.y).lineTo(b.x, b.y);
      const c = project(-H, v, 0, s);
      const d = project(H, v, 0, s);
      g.moveTo(c.x, c.y).lineTo(d.x, d.y);
    }
    g.stroke({ width: 1, color: 0x263149, alpha: 0.8 });
    g.poly(corners.flatMap((p) => [p.x, p.y])).stroke({ width: 2, color: 0x3b4a6b });

    // coordinate labels so viewer space maps to script coordinates
    for (let v = -H; v <= H; v += GRID_STEP * 2) {
      this.addLabel(`${v}`, project(v, -H - 8, 0, s), 0x5b6a88);      // N values, west edge
      this.addLabel(`${v}`, project(-H - 8, v, 0, s), 0x5b6a88);      // E values, south edge
    }
    const nArrow = project(H + 16, -H - 8, 0, s);
    const eArrow = project(-H - 8, H + 16, 0, s);
    this.addLabel("N ↑", nArrow, 0x7f93bd, 15);
    this.addLabel("E ↑", eArrow, 0x7f93bd, 15);
  }

  private addLabel(text: string, at: { x: number; y: number }, color: number,
                   size = 12): void {
    const label = new Text({
      text,
      style: { fontFamily: "Segoe UI, system-ui, sans-serif", fontSize: size, fill: color },
    });
    label.anchor.set(0.5);
    label.position.set(at.x, at.y);
    this.gridLabels.addChild(label);
  }

  /** Redraw spawn pads when the roster changes (cheap key comparison). */
  drawPads(pads: PadState[]): void {
    const key = pads.map((p) => `${p.slot}:${p.name}`).join("|") + this.scale.toFixed(3);
    if (key === this.padsKey) return;
    this.padsKey = key;
    this.padLayer.removeChildren();
    const s = this.scale;
    const r = 3.2; // pad radius, meters
    for (const pad of pads) {
      const g = new Graphics();
      const corners = [
        project(pad.n + r, pad.e, 0, s), project(pad.n, pad.e + r, 0, s),
        project(pad.n - r, pad.e, 0, s), project(pad.n, pad.e - r, 0, s),
      ];
      const center = project(pad.n, pad.e, 0, s);
      const color = slotColor(pad.slot + 1);
      g.poly(corners.flatMap((p) => [p.x - center.x, p.y - center.y]))
        .fill({ color, alpha: 0.16 })
        .stroke({ width: 1.5, color, alpha: 0.75 });
      g.position.set(center.x, center.y);
      const label = new Text({
        text: pad.name,
        style: { fontFamily: "Segoe UI, system-ui, sans-serif", fontSize: 11,
                 fill: color, fontWeight: "600" },
      });
      label.anchor.set(0.5, 0);
      label.position.set(0, 6);
      g.addChild(label);
      this.padLayer.addChild(g);
    }
  }
}
