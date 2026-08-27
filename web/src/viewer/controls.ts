/** Pan/zoom input for the arena view: wheel, trackpad, drag, pinch, keyboard.
 *
 * All the view math lives in camera.ts; this is the DOM layer that turns
 * events into camera moves. Wheel and key zooms ease toward a target so a
 * notch reads as a glide; drag and pinch are applied straight through, because
 * easing a direct manipulation just feels like lag.
 */

import { type Camera, clampCamera, defaultCamera, followCenter, maxScale, panBy,
         screenToWorld, solveCenter, worldToScreen, zoomAt } from "./camera";
import { nextFollowId } from "./follow";
import { expBlend, type Pose } from "./interp";
import { fitScale } from "./iso";
import type { Scene } from "./scene";

/** Wheel-click zoom sensitivity, per pixel of deltaY. A 120px notch is ~1.2x. */
const WHEEL_K = 0.0015;
/** Trackpad pinch (ctrl+wheel) is a smaller physical gesture — amplify it. */
const PINCH_K = 0.012;
/** Zoom ease time constant. Lower = snappier. */
const ZOOM_TAU_MS = 80;
const KEY_ZOOM_STEP = 1.25;
const KEY_PAN_PX = 80;
/** Pointer travel that turns a tap into a drag. */
const DRAG_SLOP_PX = 5;
/** Tap this close to a drone to follow it. Grows with the drone's drawn size. */
const TAP_PICK_PX = 28;

export class CameraController {
  private target: Camera;
  /** The camera value this controller last wrote; anything else in
   * scene.camera means the scene refit itself and we should follow. */
  private applied: Camera;
  /** World point pinned under the cursor while a zoom eases. */
  private anchor: { sx: number; sy: number; n: number; e: number } | null = null;
  private pointers = new Map<number, { x: number; y: number }>();
  private pinchDist = 0;
  private dragging = false;
  private moved = 0;
  private settled = true;
  /** A reset is easing home; clear userAdjusted once it lands. */
  private resetting = false;
  /** Drone the camera is tracking, if any. */
  private followId: string | null = null;
  private poses: (() => Map<string, Pose>) | null = null;

  constructor(private scene: Scene) {
    this.target = { ...scene.camera };
    this.applied = scene.camera;
    const canvas = scene.app.canvas;
    canvas.addEventListener("wheel", this.onWheel, { passive: false });
    canvas.addEventListener("pointerdown", this.onPointerDown);
    canvas.addEventListener("pointermove", this.onPointerMove);
    canvas.addEventListener("pointerup", this.onPointerUp);
    canvas.addEventListener("pointercancel", this.onPointerUp);
    window.addEventListener("keydown", this.onKeyDown);
    // Safari fires its own pinch gestures alongside wheel events
    canvas.addEventListener("gesturestart", preventDefault);
    canvas.addEventListener("gesturechange", preventDefault);
  }

  /** Where to read the smoothed render poses from (main.ts owns them). */
  setPoseSource(fn: () => Map<string, Pose>): void {
    this.poses = fn;
  }

  /** Id of the drone being followed, or null. */
  get following(): string | null {
    return this.followId;
  }

  private get vw(): number { return window.innerWidth; }
  private get vh(): number { return window.innerHeight; }

  private clamp(cam: Camera): Camera {
    return clampCamera(cam, this.scene.half, this.scene.altMax, this.vw, this.vh);
  }

  /** Write a camera to the scene now (direct manipulation, or an eased step). */
  private commit(cam: Camera): void {
    const next = this.clamp(cam);
    this.scene.camera = next;
    this.applied = next;
    this.scene.applyCamera();
  }

  private zoom(factor: number, sx: number, sy: number, immediate = false): void {
    const min = fitScale(this.scene.half, this.scene.altMax, this.vw, this.vh);
    const max = maxScale(this.scene.half, this.scene.altMax, this.vw, this.vh);
    if (this.followId) {
      // follow owns the centre; anchoring to the cursor would drag the camera
      // off the drone only for the next frame to snap it back
      const scale = Math.min(Math.max(this.target.scale * factor, min), max);
      if (scale === this.target.scale) return;
      this.target = { ...this.target, scale };
      this.scene.userAdjusted = true;
      this.settled = false;
      return;
    }
    const next = zoomAt(this.target, this.vw, this.vh, sx, sy, factor, min, max);
    if (next === this.target) return;
    this.scene.userAdjusted = true;
    this.resetting = false;
    if (immediate) {
      this.target = this.clamp(next);
      this.anchor = null;
      this.settled = true;
      this.commit(this.target);
      return;
    }
    // remember the world point under the cursor so the ease keeps it pinned
    this.anchor = { sx, sy, ...screenToWorld(this.target, this.vw, this.vh, sx, sy) };
    this.target = next;
    this.settled = false;
  }

  private pan(dx: number, dy: number, immediate = false): void {
    if (!dx && !dy) return;
    this.target = this.clamp(panBy(this.target, dx, dy));
    this.anchor = null;
    this.scene.userAdjusted = true;
    this.resetting = false;
    this.followId = null; // taking the view by hand stops following
    if (immediate) {
      this.settled = true;
      this.commit(this.target);
    } else {
      this.settled = false;
    }
  }

  private onWheel = (ev: WheelEvent): void => {
    ev.preventDefault();
    // deltaMode 1 is lines, not pixels (Firefox with a real mouse wheel)
    const unit = ev.deltaMode === 1 ? 16 : 1;
    if (ev.deltaY) {
      this.zoom(Math.exp(-ev.deltaY * unit * (ev.ctrlKey ? PINCH_K : WHEEL_K)),
                ev.clientX, ev.clientY);
    }
    // two-finger horizontal scroll pans; a mouse wheel never sends deltaX
    if (!ev.ctrlKey && ev.deltaX) this.pan(-ev.deltaX * unit, 0, true);
  };

  private onPointerDown = (ev: PointerEvent): void => {
    this.pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (this.pointers.size === 1) {
      this.dragging = true;
      this.moved = 0;
      this.scene.app.canvas.setPointerCapture(ev.pointerId);
    } else if (this.pointers.size === 2) {
      this.dragging = false;
      this.pinchDist = this.spread();
    }
  };

  private onPointerMove = (ev: PointerEvent): void => {
    const prev = this.pointers.get(ev.pointerId);
    if (!prev) return;
    const dx = ev.clientX - prev.x;
    const dy = ev.clientY - prev.y;
    this.pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });

    if (this.pointers.size === 2) {
      const dist = this.spread();
      if (this.pinchDist > 0 && dist > 0) {
        const mid = this.midpoint();
        this.zoom(dist / this.pinchDist, mid.x, mid.y, true);
      }
      this.pinchDist = dist;
      this.pan(dx / 2, dy / 2, true); // both pointers report the same slide
      return;
    }
    if (!this.dragging) return;
    this.moved += Math.abs(dx) + Math.abs(dy);
    if (this.moved > DRAG_SLOP_PX) this.pan(dx, dy, true);
  };

  private onPointerUp = (ev: PointerEvent): void => {
    const wasTap = this.dragging && this.pointers.size === 1
      && this.moved <= DRAG_SLOP_PX;
    this.pointers.delete(ev.pointerId);
    if (this.pointers.size < 2) this.pinchDist = 0;
    if (this.pointers.size === 0) this.dragging = false;
    // a tap picks a drone to follow; a tap on empty sky stops following
    if (wasTap) this.followId = this.droneAt(ev.clientX, ev.clientY);
  };

  /** Tour the roster from the keyboard — clicking a moving drone at arena
   * zoom is a fiddly shot to ask of someone standing at a projector. */
  private followNext(): void {
    const poses = this.poses?.();
    if (!poses) return;
    this.followId = nextFollowId([...poses.keys()], this.followId);
    this.settled = false;
  }

  /** Nearest drone drawn within picking distance of a screen point. */
  private droneAt(sx: number, sy: number): string | null {
    const poses = this.poses?.();
    if (!poses) return null;
    // matches the drawn body radius in drones.ts, so the target grows with zoom
    const radius = Math.max(5, this.scene.camera.scale * 1.7);
    const pick = Math.max(TAP_PICK_PX, radius * 1.5);
    let best: string | null = null;
    let bestD = pick;
    for (const [id, pose] of poses) {
      const p = worldToScreen(this.scene.camera, this.vw, this.vh,
                              pose.n, pose.e, pose.alt);
      const d = Math.hypot(p.x - sx, p.y - sy);
      if (d < bestD) {
        bestD = d;
        best = id;
      }
    }
    return best;
  }

  private spread(): number {
    const [a, b] = [...this.pointers.values()];
    return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
  }

  private midpoint(): { x: number; y: number } {
    const [a, b] = [...this.pointers.values()];
    return a && b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : { x: 0, y: 0 };
  }

  private onKeyDown = (ev: KeyboardEvent): void => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return; // leave browser zoom alone
    const el = ev.target as HTMLElement | null;
    const tag = el?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || el?.isContentEditable) return;
    switch (ev.key) {
      case "+": case "=": this.zoom(KEY_ZOOM_STEP, this.vw / 2, this.vh / 2); break;
      case "-": case "_": this.zoom(1 / KEY_ZOOM_STEP, this.vw / 2, this.vh / 2); break;
      case "ArrowLeft": case "a": case "A": this.pan(KEY_PAN_PX, 0); break;
      case "ArrowRight": case "d": case "D": this.pan(-KEY_PAN_PX, 0); break;
      case "ArrowUp": case "w": case "W": this.pan(0, KEY_PAN_PX); break;
      case "ArrowDown": case "s": case "S": this.pan(0, -KEY_PAN_PX); break;
      case "n": case "N": this.followNext(); break;
      case "0": case "Home":
        this.target = defaultCamera(this.scene.half, this.scene.altMax, this.vw, this.vh);
        this.anchor = null;
        this.settled = false;
        this.resetting = true; // userAdjusted clears once we get there
        this.followId = null;
        break;
      default: return;
    }
    ev.preventDefault();
  };

  /** Ease the live camera toward its target. Called once per rendered frame. */
  update(dtMs: number): void {
    if (this.scene.camera !== this.applied) {
      // the scene refit itself (window resize, fullscreen, new arena)
      this.target = { ...this.scene.camera };
      this.applied = this.scene.camera;
      this.anchor = null;
      this.settled = true;
      this.resetting = false;
      return; // followId survives: a resize should not stop following
    }

    if (this.followId) {
      const pose = this.poses?.().get(this.followId);
      if (!pose) {
        this.followId = null; // drone left the roster, or the epoch reset
      } else {
        // re-aim every frame; the ease below turns that into smooth tracking
        const c = followCenter(pose.n, pose.e, pose.alt);
        this.target = { ...this.target, cN: c.cN, cE: c.cE };
        this.anchor = null;
        this.settled = false;
      }
    }
    if (this.settled) return;

    const cam = this.scene.camera;
    const k = expBlend(dtMs, ZOOM_TAU_MS);
    // ease in log space so each frame is a constant *ratio*: linear easing
    // across a 16x zoom range crawls at one end and lurches at the other
    const scale = Math.exp(Math.log(cam.scale)
      + (Math.log(this.target.scale) - Math.log(cam.scale)) * k);

    let next: Camera;
    if (this.anchor) {
      // hold the cursor's world point exactly under the cursor as we ease
      const c = solveCenter(this.anchor.n, this.anchor.e, this.anchor.sx,
                            this.anchor.sy, scale, this.vw, this.vh);
      next = { scale, cN: c.cN, cE: c.cE };
    } else {
      next = {
        scale,
        cN: cam.cN + (this.target.cN - cam.cN) * k,
        cE: cam.cE + (this.target.cE - cam.cE) * k,
      };
    }

    if (Math.abs(Math.log(this.target.scale / scale)) < 1e-3
        && Math.hypot(this.target.cN - next.cN, this.target.cE - next.cE) < 0.05) {
      next = { ...this.target };
      this.anchor = null;
      this.settled = true;
      if (this.resetting) {
        this.resetting = false;
        this.scene.userAdjusted = false; // resizes refit again, as by default
      }
    }
    this.commit(next);
  }
}

function preventDefault(ev: Event): void {
  ev.preventDefault();
}
