/** View math: renderer resolution budget, and the pan/zoom camera.
 *
 * Pure functions over plain data — no Pixi, no DOM — so the whole camera is
 * unit-testable. `Scene` owns a `Camera` and applies it; `CameraController`
 * drives it from input events.
 */

import { ALT_LIFT, fitScale, project, unproject } from "./iso";

/** Physical-pixel budget for the framebuffer (~4K). Browser zoom shrinks the
 * CSS viewport as devicePixelRatio rises, so the physical area stays roughly
 * constant: capping on area (rather than a fixed dpr cap) keeps zoomed-in
 * pages fully sharp while still bounding GPU cost on a 4K projector. */
export const MAX_FB_PIXELS = 9_000_000;

export function clampResolution(dpr: number, w: number, h: number): number {
  const area = Math.max(1, w * h);
  return Math.min(dpr || 1, Math.max(1, Math.sqrt(MAX_FB_PIXELS / area)));
}

/** How far outside the arena the view may be panned, in meters. */
export const PAN_MARGIN_M = 25;
/** Floor for the zoom-in limit, px per meter. */
export const MIN_MAX_SCALE = 24;
/** Zoom-in limit as a multiple of the fitted scale. */
export const MAX_ZOOM_FACTOR = 16;

/** Camera: `scale` is px per meter, `cN`/`cE` is the world point (at altitude
 * 0) that sits at the center of the viewport. */
export interface Camera {
  scale: number;
  cN: number;
  cE: number;
}

/** The default view's center point.
 *
 * The pre-camera layout placed the world origin at
 * `(w/2, h/2 + altMax*ALT_LIFT*scale/2)` — i.e. it nudged the ground diamond
 * down to leave sky headroom above. Solving that offset through the
 * projection gives a plain world-space center of n = e = altMax*ALT_LIFT/2,
 * so the headroom needs no special case: it is just where the camera looks.
 */
export function headroomCenter(altMax: number): number {
  return (altMax * ALT_LIFT) / 2;
}

export function defaultCamera(half: number, altMax: number, w: number, h: number): Camera {
  const c = headroomCenter(altMax);
  return { scale: fitScale(half, altMax, w, h), cN: c, cE: c };
}

/** Zoom-in limit, px per meter. */
export function maxScale(half: number, altMax: number, w: number, h: number): number {
  return Math.max(MIN_MAX_SCALE, MAX_ZOOM_FACTOR * fitScale(half, altMax, w, h));
}

/** Where the world container goes so the camera center lands mid-viewport. */
export function worldOffset(cam: Camera, w: number, h: number): { x: number; y: number } {
  const p = project(cam.cN, cam.cE, 0, cam.scale);
  return { x: w / 2 - p.x, y: h / 2 - p.y };
}

/** Screen pixel (viewport coords) -> world meters at altitude 0. */
export function screenToWorld(cam: Camera, w: number, h: number, sx: number, sy: number):
  { n: number; e: number } {
  const off = worldOffset(cam, w, h);
  return unproject(sx - off.x, sy - off.y, cam.scale);
}

/** The center that keeps world point (n,e) under screen point (sx,sy) at `scale`. */
export function solveCenter(n: number, e: number, sx: number, sy: number,
                            scale: number, w: number, h: number): { cN: number; cE: number } {
  // We want: project(center) = project(n,e) - (sx - w/2, sy - h/2).
  const p = project(n, e, 0, scale);
  const target = unproject(p.x - (sx - w / 2), p.y - (sy - h / 2), scale);
  return { cN: target.n, cE: target.e };
}

/** Zoom by `factor`, keeping the world point under (sx,sy) pinned there. */
export function zoomAt(cam: Camera, w: number, h: number, sx: number, sy: number,
                       factor: number, minS: number, maxS: number): Camera {
  const scale = Math.min(Math.max(cam.scale * factor, minS), maxS);
  if (scale === cam.scale) return cam;
  const anchor = screenToWorld(cam, w, h, sx, sy);
  const c = solveCenter(anchor.n, anchor.e, sx, sy, scale, w, h);
  return { scale, cN: c.cN, cE: c.cE };
}

/** Pan by a screen-pixel delta: dragging right moves the world right. */
export function panBy(cam: Camera, dxPx: number, dyPx: number): Camera {
  const d = unproject(dxPx, dyPx, cam.scale);
  return { scale: cam.scale, cN: cam.cN - d.n, cE: cam.cE - d.e };
}

export function clampCamera(cam: Camera, half: number, altMax: number,
                            w: number, h: number): Camera {
  const minS = fitScale(half, altMax, w, h);
  const maxS = maxScale(half, altMax, w, h);
  const lim = half + PAN_MARGIN_M;
  return {
    scale: Math.min(Math.max(cam.scale, minS), maxS),
    cN: Math.min(Math.max(cam.cN, -lim), lim),
    cE: Math.min(Math.max(cam.cE, -lim), lim),
  };
}
