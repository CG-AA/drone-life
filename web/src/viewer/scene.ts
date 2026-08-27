/** Pixi stage: layers, arena floor (hex lattice) with coordinate labels,
 * spawn pads.
 *
 * Paint order, bottom-up: floor grid → pads → trails → ground decals (flat
 * rings) → the single depth-sorted layer holding tile prisms, shadows, drones
 * and entities. Anything with a footprint in the world goes in that last layer
 * with a depth zIndex, so near things cover far things regardless of kind.
 *
 * The scene owns a Camera; CameraController drives it from input. Zoom changes
 * `scale`, which every layer already keys its redraw on, so the vector art is
 * re-emitted crisp at the new zoom rather than being a scaled-up bitmap. Pan
 * is a pure container translation and redraws nothing.
 */

import { Application, Container, Graphics, Text } from "pixi.js";
import type { PadState } from "../shared/protocol";
import { COLORS, FONT_UI } from "../shared/theme";
import { axialToWorld, hexCorners, worldToAxial } from "./hex";
import { project, type Projected } from "./iso";
import { type Camera, clampCamera, clampResolution, defaultCamera, worldOffset } from "./camera";
import { slotColor } from "./colors";

const GRID_STEP = 20;

/** Where a shadow (or anything resting on the ground) sits at a world point:
 * the altitude of the surface and the zIndex that paints it just above the
 * tile it rests on. */
export interface Ground {
  alt: number;
  zIndex: number;
}

export class Scene {
  app = new Application();
  world = new Container();
  gridLayer = new Graphics();
  gridLabels = new Container();
  padLayer = new Container();
  trailLayer = new Container();
  decalLayer = new Container(); // flat ground rings, never occlude anything
  spriteLayer = new Container(); // tiles + shadows + drones + entities, depth-sorted
  /** Hex lattice size from hello (and the tiles message); null until one arrives. */
  hexSize: number | null = null;
  /** Overridden by the terrain renderer once tiles exist. */
  groundAt: (n: number, e: number) => Ground = (n, e) =>
    ({ alt: 0, zIndex: project(n, e, 0, 1).depth });

  camera: Camera = { scale: 3, cN: 0, cE: 0 };
  half = 100;
  altMax = 60;
  /** Resolution Text objects must rasterize at; changes with the display. */
  textResolution = 1;
  /** True once the viewer has panned or zoomed: a window resize then keeps
   * their view instead of yanking it back to the fitted default. */
  userAdjusted = false;
  private padsKey = "";
  private lastPads: PadState[] = [];
  private appliedScale = 0;
  private syncQueued = false;

  /** px per meter. Layers read this to redraw at the current zoom. */
  get scale(): number {
    return this.camera.scale;
  }

  async init(): Promise<void> {
    await this.app.init({
      background: COLORS.bg,
      // deliberately not resizeTo: window — Pixi's ResizePlugin defers the
      // renderer resize to a later frame, which leaves one frame drawn with
      // the new camera in the old framebuffer. syncViewport() owns the size.
      width: window.innerWidth,
      height: window.innerHeight,
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
                        this.decalLayer, this.spriteLayer);
    this.app.stage.addChild(this.world);
    window.addEventListener("resize", () => this.queueViewportSync());
    // F11 and the double-click handler both land here; on some browsers the
    // fullscreen transition reports its final size only after this event
    document.addEventListener("fullscreenchange", () => this.queueViewportSync());
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
      this.queueViewportSync();
      arm();
    };
    const arm = (): void => {
      matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`)
        .addEventListener("change", onChange, { once: true });
    };
    arm();
  }

  /** Coalesce a burst of viewport events into one sync. Dragging a window
   * edge fires resize at pointer rate, and each sync rebuilds the whole hex
   * lattice, every pad, and (next tick) every tile prism. */
  private queueViewportSync(): void {
    if (this.syncQueued) return;
    this.syncQueued = true;
    window.requestAnimationFrame(() => {
      this.syncQueued = false;
      this.syncViewport();
    });
  }

  /** Match the renderer to the window, then refit. Owns both the size and the
   * device pixel density, so the framebuffer and the camera can never
   * disagree about how big the viewport is. */
  private syncViewport(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    const res = clampResolution(window.devicePixelRatio, w, h);
    if (Math.abs(res - this.textResolution) > 1e-6) {
      this.textResolution = res;
      // Text rasterizes at the resolution it was built with. Drones and
      // entities re-point theirs every frame; the grid and pad labels are
      // only rebuilt when the zoom changes, so force that rebuild or they
      // stay soft for as long as the projector keeps this zoom.
      this.appliedScale = 0;
    }
    this.app.renderer.resize(w, h, res);
    this.layout();
  }

  setArena(half: number, altMax: number): void {
    this.half = half;
    this.altMax = altMax;
    this.userAdjusted = false; // a new arena deserves a fresh fit
    this.layout();
  }

  /** The tile lattice the floor is drawn with (from the tiles message, so it
   * can never drift from the server's hex size). */
  setHexGeometry(size: number): void {
    if (this.hexSize === size) return;
    this.hexSize = size;
    this.drawGrid();
    this.padsKey = "";
    this.drawPads(this.lastPads);
  }

  layout(): void {
    // window dims, not renderer dims: syncViewport resizes the renderer just
    // before calling this, but setArena and boot reach it directly.
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.camera = this.userAdjusted
      ? clampCamera(this.camera, this.half, this.altMax, w, h)
      : defaultCamera(this.half, this.altMax, w, h);
    this.applyCamera();
  }

  /** Move the world to where the camera looks, redrawing scale-dependent
   * layers only when the zoom actually changed. */
  applyCamera(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    const off = worldOffset(this.camera, w, h);
    // Snap to the device-pixel grid: 1 px hairlines (grid, tile outlines,
    // altitude stems) smear into grey when they straddle two device pixels.
    const r = this.app.renderer.resolution;
    this.world.position.set(Math.round(off.x * r) / r, Math.round(off.y * r) / r);
    if (this.camera.scale !== this.appliedScale) {
      this.appliedScale = this.camera.scale;
      this.drawGrid();
      this.padsKey = ""; // force pad redraw at the new scale
      this.drawPads(this.lastPads);
    }
  }

  private drawGrid(): void {
    const g = this.gridLayer;
    const s = this.scale;
    const H = this.half;
    g.clear();
    // removeChildren() alone leaks: Pixi does not destroy detached children
    for (const c of this.gridLabels.removeChildren()) c.destroy();

    const corners = [
      project(H, H, 0, s), project(-H, H, 0, s),
      project(-H, -H, 0, s), project(H, -H, 0, s),
    ];
    const diamond = corners.flatMap((p) => [p.x, p.y]);
    g.poly(diamond).fill({ color: COLORS.floor });

    if (this.hexSize !== null) this.drawHexLattice(this.hexSize, s);
    else this.drawSquareGrid(s);
    g.poly(diamond).stroke({ width: 2, color: COLORS.gridBorder });

    // coordinate labels so viewer space maps to script coordinates
    for (let v = -H; v <= H; v += GRID_STEP * 2) {
      this.addLabel(`${v}`, project(v, -H - 8, 0, s), COLORS.label);  // N values, west edge
      this.addLabel(`${v}`, project(-H - 8, v, 0, s), COLORS.label);  // E values, south edge
    }
    const nArrow = project(H + 16, -H - 8, 0, s);
    const eArrow = project(-H - 8, H + 16, 0, s);
    this.addLabel("N ↑", nArrow, COLORS.labelBright, 18);
    this.addLabel("E ↑", eArrow, COLORS.labelBright, 18);
  }

  /** Pre-tiles fallback: the old 20 m square grid. */
  private drawSquareGrid(s: number): void {
    const g = this.gridLayer;
    const H = this.half;
    for (let v = -H; v <= H; v += GRID_STEP) {
      const a = project(v, -H, 0, s);
      const b = project(v, H, 0, s);
      g.moveTo(a.x, a.y).lineTo(b.x, b.y);
      const c = project(-H, v, 0, s);
      const d = project(H, v, 0, s);
      g.moveTo(c.x, c.y).lineTo(d.x, d.y);
    }
    g.stroke({ width: 1, color: COLORS.grid, alpha: 0.8 });
  }

  /** The real cell lattice, so placed tiles visibly sit in the grid they snap
   * to. Each cell strokes three of its six edges (the other three belong to
   * its neighbors); cells straddling the border are clipped by the arena
   * diamond (Pixi mask), so the lattice runs right up to the edge without
   * poking out. */
  private drawHexLattice(size: number, s: number): void {
    const g = this.gridLayer;
    const H = this.half;
    const reach = H + size; // include cells whose center is just outside
    const rMax = Math.ceil(reach / (1.5 * size));
    for (let r = -rMax; r <= rMax; r++) {
      const qMax = Math.ceil(reach / (Math.sqrt(3) * size)) + Math.ceil(Math.abs(r) / 2) + 1;
      for (let q = -qMax; q <= qMax; q++) {
        const c = axialToWorld(q, r, size);
        if (Math.abs(c.n) > reach || Math.abs(c.e) > reach) continue;
        const pts: Projected[] = hexCorners(q, r, size).map((w) => project(w.n, w.e, 0, s));
        g.moveTo(pts[0].x, pts[0].y);
        for (let k = 1; k <= 3; k++) g.lineTo(pts[k].x, pts[k].y);
      }
    }
    g.stroke({ width: 1, color: COLORS.grid, alpha: 0.8 });
    const mask = new Graphics();
    const corners = [
      project(H, H, 0, s), project(-H, H, 0, s),
      project(-H, -H, 0, s), project(H, -H, 0, s),
    ];
    mask.poly(corners.flatMap((p) => [p.x, p.y])).fill({ color: 0xffffff });
    const old = this.gridLayer.mask as Graphics | null;
    this.gridLayer.mask = mask;
    this.gridLayer.addChild(mask);
    old?.destroy();
  }

  private addLabel(text: string, at: { x: number; y: number }, color: number,
                   size = 14): void {
    const label = new Text({
      text,
      style: {
        fontFamily: FONT_UI, fontSize: size, fill: color,
        stroke: { color: COLORS.ink, width: 2.5 },
      },
      resolution: this.textResolution,
    });
    label.anchor.set(0.5);
    label.position.set(at.x, at.y);
    this.gridLabels.addChild(label);
  }

  /** Redraw spawn pads when the roster changes (cheap key comparison). */
  drawPads(pads: PadState[]): void {
    this.lastPads = pads;
    const key = pads.map((p) => `${p.slot}:${p.name}`).join("|")
      + `@${this.scale.toFixed(3)}/${this.hexSize}`;
    if (key === this.padsKey) return;
    this.padsKey = key;
    for (const c of this.padLayer.removeChildren()) c.destroy({ children: true });
    const s = this.scale;
    // a pad IS a lattice cell (server: hex.pad_cell), so draw that cell's own
    // hex rather than a free-floating marker — it fills its grid hex exactly
    const size = this.hexSize;
    if (size === null) return; // hello carries hex_size; pads follow it
    for (const pad of pads) {
      const g = new Graphics();
      const [q, r] = worldToAxial(pad.n, pad.e, size);
      const corners: Projected[] = hexCorners(q, r, size).map((w) => project(w.n, w.e, 0, s));
      const c = axialToWorld(q, r, size);
      const center = project(c.n, c.e, 0, s);
      const color = slotColor(pad.slot + 1);
      g.poly(corners.flatMap((p) => [p.x - center.x, p.y - center.y]))
        .fill({ color, alpha: 0.16 })
        .stroke({ width: 1.5, color, alpha: 0.75 });
      g.position.set(center.x, center.y);
      const label = new Text({
        text: pad.name,
        style: {
          fontFamily: FONT_UI, fontSize: 13, fill: color, fontWeight: "600",
          stroke: { color: COLORS.ink, width: 2.5 },
        },
        resolution: this.textResolution,
      });
      label.anchor.set(0.5, 0);
      label.position.set(0, 6);
      g.addChild(label);
      this.padLayer.addChild(g);
    }
  }
}
