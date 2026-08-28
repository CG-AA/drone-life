/** Kind renderers owned by the siege mission: troop, keep, tower, beam, and
 * the short-lived cosmetics (zap_arc, poof) that make a kill visible from the
 * back row. The server owns their lifetime; they animate from `vis.bornMs`. */

import { COLORS, REDUCED_MOTION } from "../../shared/theme";
import { ALT_LIFT, project, projectGround } from "../iso";
import { hexPoly, pulse, type KindRenderer } from "./base";

/** Per-kind look: shape and size, never colour alone (a projector washes
 * colour out first). Sizes carry a floor so a creep reads from the back row. */
interface TroopLook { fill: number; edge: number; tick: number; r: number; sides: number }
const TROOP_LOOK: Record<string, TroopLook> = {
  grunt: { fill: 0xe14b4b, edge: 0x7c1f1f, tick: 0xffd0d0, r: 1.2, sides: 0 },
  runner: { fill: 0xff9a3c, edge: 0x8a4a10, tick: 0xffe0b0, r: 0.9, sides: 3 },
  brute: { fill: 0x9c1f2e, edge: 0x3d0a12, tick: 0xffb0b0, r: 1.9, sides: 6 },
  sapper: { fill: 0xa25cff, edge: 0x4a1f8a, tick: 0xe6d0ff, r: 1.15, sides: 4 },
  champion: { fill: 0xd91f5a, edge: 0x5a0a24, tick: 0xffd0e0, r: 2.6, sides: 8 },
};

function polyAround(cx: number, cy: number, r: number, sides: number, rot = 0): number[] {
  const pts: number[] = [];
  for (let k = 0; k < sides; k++) {
    const a = rot + (Math.PI * 2 * k) / sides;
    pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r * 0.75);
  }
  return pts;
}

export const troop: KindRenderer = {
  animated: true,
  draw(vis, ent, pose, drawAlt, s, timeMs) {
    const chewing = Boolean(ent.data.chewing);
    const look = TROOP_LOOK[String(ent.data.kind ?? "grunt")] ?? TROOP_LOOK.grunt;
    const dir = (Number(ent.data.dir ?? 0) * Math.PI) / 180; // server sends degrees
    const jitter = chewing && !REDUCED_MOTION ? Math.sin(timeMs / 30) * s * 0.25 : 0;
    const bob = chewing || REDUCED_MOTION ? 0 : Math.abs(Math.sin(timeMs / 120)) * s * 0.35;
    const r = Math.max(5, s * look.r);
    if (look.sides === 0) {
      vis.g.circle(jitter, -bob, r).fill({ color: look.fill })
        .stroke({ width: 1.5, color: look.edge });
    } else {
      vis.g.poly(polyAround(jitter, -bob, r, look.sides, -Math.PI / 2))
        .fill({ color: look.fill }).stroke({ width: 1.5, color: look.edge });
    }
    if (look.sides === 8) { // the champion wears a crown
      const c = polyAround(jitter, -bob - r * 0.9, r * 0.55, 3, -Math.PI / 2);
      vis.g.poly(c).fill({ color: COLORS.gold });
    }
    const reach = look.sides === 3 ? 2.6 : 1.8; // runners point further ahead
    const tip = project(Math.cos(dir) * reach, Math.sin(dir) * reach, 0, s);
    vis.g.moveTo(jitter, -bob).lineTo(jitter + tip.x, -bob + tip.y)
      .stroke({ width: 2, color: look.tick });
    const hp = Number(ent.data.hp ?? 1);
    const max = Number(ent.data.max ?? 1);
    if (max > 1) { // hp pips over multi-hp creeps, keep-pip style but smaller
      const w = Math.max(2.5, s * 0.5);
      const x0 = jitter - ((max - 1) * (w + 1.5)) / 2;
      for (let i = 0; i < max; i++) {
        vis.g.rect(x0 + i * (w + 1.5) - w / 2, -bob - r - w * 1.8, w, w)
          .fill({ color: i < hp ? COLORS.ok : 0x333344, alpha: 0.95 });
      }
    }
    if (drawAlt - pose.groundAlt > 0.3) { // airborne (e.g. knocked off a wall)
      const ground = project(pose.n, pose.e, pose.groundAlt, s);
      vis.shadow.ellipse(ground.x, ground.y, r, r * 0.5)
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};

export const keep: KindRenderer = {
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

export const tower: KindRenderer = {
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

export const beam: KindRenderer = {
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

export const gate: KindRenderer = {
  animated: true,
  init(vis, ent) {
    vis.addLabel(`GATE ${String(ent.data.label ?? "")}`.trim(), 0xd9a0a0, 11, 12);
  },
  draw(vis, ent, pose, _drawAlt, s, timeMs) {
    const active = Boolean(ent.data.active);
    // a dark archway on the lattice: two posts and a lintel, hex footprint
    const base = hexPoly(2.4, s);
    vis.g.poly(base).fill({ color: 0x1c1a26, alpha: 0.9 })
      .stroke({ width: 2, color: active ? 0xff5c5c : 0x5a4a5a, alpha: 0.95 });
    const h = 2.2 * ALT_LIFT * s;
    const w = Math.max(4, s * 1.3);
    vis.g.rect(-w - 2, -h, 3, h).fill({ color: 0x4a3a4a });
    vis.g.rect(w - 1, -h, 3, h).fill({ color: 0x4a3a4a });
    vis.g.rect(-w - 2, -h - 3, w * 2 + 4, 3).fill({ color: 0x6a5a6a });
    if (active) { // creeps are coming through: a pulsing red ring on the ground
      const glow = pulse(timeMs, 220, 0.5, 0.35);
      const ring: number[] = [];
      for (let k = 0; k < 18; k++) {
        const a = (Math.PI / 9) * k;
        const p = projectGround(pose.n + 6 * Math.cos(a), pose.e + 6 * Math.sin(a), s);
        ring.push(p.x, p.y);
      }
      vis.decal.poly(ring).stroke({ width: 3, color: 0xff5c5c, alpha: glow });
    }
  },
};

/** Fill colour per kill verb: what killed it is readable at a glance. */
const POOF_COLOR: Record<string, number> = {
  zap: COLORS.gold,
  squish: 0x9fb8d8,     // steel-blue: a tile landed on it
  tower: 0x9fd8ff,      // the beam's colour
  leak: COLORS.danger,  // it reached the Keep
};

export const poof: KindRenderer = {
  animated: true,
  draw(vis, ent, _pose, _drawAlt, s, timeMs) {
    const color = POOF_COLOR[String(ent.data.verb ?? "")] ?? 0xcccccc;
    // 0..1 over the poof's life (POOF_S on the server); frozen mid-way when
    // the viewer prefers reduced motion so it still reads as "something died"
    const k = REDUCED_MOTION ? 0.45 : Math.min(1, (timeMs - vis.bornMs) / 600);
    const r = Math.max(4, s * 1.1) * (0.6 + k * 2.2);
    vis.g.circle(0, 0, r).stroke({ width: Math.max(1.5, 3 * (1 - k)), color, alpha: 1 - k });
    vis.g.circle(0, 0, r * 0.35).fill({ color, alpha: 0.5 * (1 - k) });
    for (let i = 0; i < 6; i++) { // debris flung outward
      const a = (Math.PI / 3) * i + 0.4;
      const d = r * (0.5 + k * 0.7);
      vis.g.circle(Math.cos(a) * d, Math.sin(a) * d * 0.5 - k * s * 1.5, Math.max(1.2, s * 0.25))
        .fill({ color, alpha: 0.9 * (1 - k) });
    }
  },
};

export const zapArc: KindRenderer = {
  animated: true,
  draw(vis, ent, pose, _drawAlt, s, timeMs) {
    // origin = the drone (our pose); the creep's position rides in data
    const src = project(pose.n, pose.e, pose.alt, s);
    const dst = project(Number(ent.data.tn ?? pose.n), Number(ent.data.te ?? pose.e),
                        Number(ent.data.talt ?? 0), s);
    const dx = dst.x - src.x;
    const dy = dst.y - src.y;
    const k = REDUCED_MOTION ? 0.3 : Math.min(1, (timeMs - vis.bornMs) / 300);
    // a jagged bolt: three kinks off the straight line, fading over its life
    const pts = [0, 0];
    for (let i = 1; i < 4; i++) {
      const t = i / 4;
      const off = (i % 2 ? 1 : -1) * Math.max(3, s * 0.8);
      pts.push(dx * t - dy * 0.08 * (i % 2 ? 1 : -1) + off * 0.3, dy * t + off);
    }
    pts.push(dx, dy);
    vis.g.poly(pts, false).stroke({ width: 4, color: COLORS.gold, alpha: 0.35 * (1 - k) });
    vis.g.poly(pts, false).stroke({ width: 1.5, color: 0xfff2b0, alpha: 0.95 * (1 - k) });
    vis.g.circle(dx, dy, Math.max(2.5, s * 0.7)).fill({ color: 0xfff2b0, alpha: 0.9 * (1 - k) });
  },
};
