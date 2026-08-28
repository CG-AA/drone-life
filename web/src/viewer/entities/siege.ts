/** Kind renderers owned by the siege mission: troop, keep, tower, beam, and
 * the short-lived cosmetics (zap_arc, poof) that make a kill visible from the
 * back row. The server owns their lifetime; they animate from `vis.bornMs`. */

import { COLORS, REDUCED_MOTION } from "../../shared/theme";
import { ALT_LIFT, project, projectGround } from "../iso";
import { hexPoly, pulse, type KindRenderer } from "./base";

export const troop: KindRenderer = {
  animated: true,
  draw(vis, ent, pose, drawAlt, s, timeMs) {
    const chewing = Boolean(ent.data.chewing);
    const dir = (Number(ent.data.dir ?? 0) * Math.PI) / 180; // server sends degrees
    const jitter = chewing && !REDUCED_MOTION ? Math.sin(timeMs / 30) * s * 0.25 : 0;
    const bob = chewing || REDUCED_MOTION ? 0 : Math.abs(Math.sin(timeMs / 120)) * s * 0.35;
    const r = Math.max(3.5, s * 1.1);
    vis.g.circle(jitter, -bob, r).fill({ color: 0xe14b4b })
      .stroke({ width: 1.5, color: 0x7c1f1f });
    const tip = project(Math.cos(dir) * 1.8, Math.sin(dir) * 1.8, 0, s);
    vis.g.moveTo(jitter, -bob).lineTo(jitter + tip.x, -bob + tip.y)
      .stroke({ width: 2, color: 0xffd0d0 });
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
