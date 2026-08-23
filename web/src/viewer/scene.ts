/** Pixi stage: layers, arena grid with coordinate labels, spawn pads. */

import { Application, Container, Graphics, Text } from "pixi.js";
import type { PadState } from "../shared/protocol";
import { COLORS, FONT_UI } from "../shared/theme";
import { ALT_LIFT, fitScale, project } from "./iso";
import { clampResolution } from "./camera";
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
  terrainLayer = new Container(); // hex-tile prisms, event-driven redraw
  spriteLayer = new Container(); // drones + entities, depth-sorted

  scale = 3;
  half = 100;
  altMax = 60;
  /** Resolution Text objects must rasterize at; changes with the display. */
  textResolution = 1;
  private padsKey = "";
  private lastPads: PadState[] = [];

  async init(): Promise<void> {
    await this.app.init({
      background: COLORS.bg,
      resizeTo: window,
      antialias: true,
      // sharp on HiDPI/scaled-4K projectors; area-capped to bound GPU cost
      resolution: clampResolution(window.devicePixelRatio, window.innerWidth,
                                  window.innerHeight),
      autoDensity: true,
    });
    this.textResolution = this.app.renderer.resolution;
    this.app.canvas.setAttribute("role", "img");
    this.app.canvas.setAttribute("aria-label", "live drone arena");
    document.body.appendChild(this.app.canvas);
    this.spriteLayer.sortableChildren = true;
    this.world.addChild(this.gridLayer, this.gridLabels, this.padLayer, this.trailLayer,
                        this.shadowLayer, this.terrainLayer, this.spriteLayer);
    this.app.stage.addChild(this.world);
    window.addEventListener("resize", () => {
      this.applyResolution();
      this.layout();
    });
    this.watchDpr();
    this.layout();
  }

  /** Browser zoom, OS display scaling, and dragging the window to a monitor of
   * a different DPI all change devicePixelRatio without firing anything Pixi
   * listens to — the framebuffer would stay at its page-load size and the
   * compositor would upscale it (blurry). Re-arm a one-shot dppx query after
   * every change, since the query itself is ratio-specific. */
  private watchDpr(): void {
    const onChange = (): void => {
      this.applyResolution();
      this.layout();
      arm();
    };
    const arm = (): void => {
      matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`)
        .addEventListener("change", onChange, { once: true });
    };
    arm();
  }

  /** Re-point the renderer at the current device pixel density. Idempotent:
   * the resize and dppx paths both call it and the second one is a no-op. */
  applyResolution(): void {
    const res = clampResolution(window.devicePixelRatio, window.innerWidth,
                                window.innerHeight);
    if (Math.abs(res - this.app.renderer.resolution) < 1e-6) return;
    this.app.renderer.resize(window.innerWidth, window.innerHeight, res);
    this.textResolution = res;
  }

  setArena(half: number, altMax: number): void {
    this.half = half;
    this.altMax = altMax;
    this.layout();
  }

  layout(): void {
    // window dims, not renderer dims: Pixi's ResizePlugin applies the actual
    // renderer resize on a later rAF, so renderer.width here can be stale
    // (one F11 toggle would leave the arena fitted to the old viewport).
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.scale = fitScale(this.half, this.altMax, w, h);
    // ground diamond is vertically centered; sky headroom sits above it
    this.setWorldPosition(w / 2, h / 2 + (this.altMax * ALT_LIFT * this.scale) / 2);
    this.drawGrid();
    this.padsKey = ""; // force pad redraw at the new scale
    this.drawPads(this.lastPads);
  }

  /** Snap to the device-pixel grid: 1 px hairlines (grid, tile outlines,
   * altitude stems) smear into grey when they straddle two device pixels. */
  private setWorldPosition(x: number, y: number): void {
    const r = this.app.renderer.resolution;
    this.world.position.set(Math.round(x * r) / r, Math.round(y * r) / r);
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
    g.poly(corners.flatMap((p) => [p.x, p.y])).fill({ color: COLORS.floor });

    for (let v = -H; v <= H; v += GRID_STEP) {
      const a = project(v, -H, 0, s);
      const b = project(v, H, 0, s);
      g.moveTo(a.x, a.y).lineTo(b.x, b.y);
      const c = project(-H, v, 0, s);
      const d = project(H, v, 0, s);
      g.moveTo(c.x, c.y).lineTo(d.x, d.y);
    }
    g.stroke({ width: 1, color: COLORS.grid, alpha: 0.8 });
    g.poly(corners.flatMap((p) => [p.x, p.y])).stroke({ width: 2, color: COLORS.gridBorder });

    // coordinate labels so viewer space maps to script coordinates
    for (let v = -H; v <= H; v += GRID_STEP * 2) {
      this.addLabel(`${v}`, project(v, -H - 8, 0, s), COLORS.label);  // N values, west edge
      this.addLabel(`${v}`, project(-H - 8, v, 0, s), COLORS.label);  // E values, south edge
    }
    const nArrow = project(H + 16, -H - 8, 0, s);
    const eArrow = project(-H - 8, H + 16, 0, s);
    this.addLabel("N ↑", nArrow, COLORS.labelBright, 15);
    this.addLabel("E ↑", eArrow, COLORS.labelBright, 15);
  }

  private addLabel(text: string, at: { x: number; y: number }, color: number,
                   size = 12): void {
    const label = new Text({
      text,
      style: { fontFamily: FONT_UI, fontSize: size, fill: color },
      resolution: this.textResolution,
    });
    label.anchor.set(0.5);
    label.position.set(at.x, at.y);
    this.gridLabels.addChild(label);
  }

  /** Redraw spawn pads when the roster changes (cheap key comparison). */
  drawPads(pads: PadState[]): void {
    this.lastPads = pads;
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
        style: { fontFamily: FONT_UI, fontSize: 11, fill: color, fontWeight: "600" },
        resolution: this.textResolution,
      });
      label.anchor.set(0.5, 0);
      label.position.set(0, 6);
      g.addChild(label);
      this.padLayer.addChild(g);
    }
  }
}
