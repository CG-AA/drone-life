/** Kind renderers owned by the building missions (rampart, forge):
 * tile_source, ghost_tile, furnace, tile_carried. */

import { ALT_LIFT, project } from "../iso";
import { MATERIAL_COLORS, UNKNOWN_MATERIAL } from "../terrain";
import { hexPoly, pulse, type KindRenderer } from "./base";

/** The pile's label: "STEEL" for an infinite source, "STEEL · 12" for a
 * stock (siege's quarry is finite per wave), "STEEL · EMPTY" at zero. Pure so
 * the wording is testable. */
export function sourceLabel(data: Record<string, unknown>): string {
  const name = String(data.material ?? "?").toUpperCase();
  const left = data.remaining;
  if (typeof left !== "number") return name;
  return left <= 0 ? `${name} · EMPTY` : `${name} · ${Math.round(left)}`;
}

export const tileSource: KindRenderer = {
  init(vis, ent) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    vis.addLabel(sourceLabel(ent.data), mat.top, 11, 12);
  },
  draw(vis, ent, _pose, _drawAlt, s) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    const left = ent.data.remaining;
    const empty = typeof left === "number" && left <= 0;
    if (vis.label) vis.label.text = sourceLabel(ent.data);
    // a little pile: three flat hex slabs, one perched on top — one greyed
    // slab when the stock is spent, so the room sees an empty quarry
    const slabs: Array<[number, number, number]> = empty
      ? [[0.1, 0.1, 0]]
      : [[0.9, -1.0, 0], [-0.6, 1.1, 0], [0.1, 0.1, 0.9]]; // (dn, de, liftM)
    for (const [dn, de, lift] of slabs) {
      const at = project(dn, de, lift, s);
      const poly = hexPoly(1.5, s);
      const out: number[] = [];
      for (let i = 0; i < poly.length; i += 2) out.push(poly[i] + at.x, poly[i + 1] + at.y);
      vis.g.poly(out).fill({ color: mat.side, alpha: empty ? 0.35 : 1 })
        .stroke({ width: 1.5, color: mat.top, alpha: empty ? 0.4 : 0.9 });
    }
  },
};

export const ghostTile: KindRenderer = {
  animated: true,
  init(vis, ent) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    vis.addLabel("", mat.top, 10, 6);
  },
  draw(vis, ent, _pose, _drawAlt, s, timeMs) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    const size = Number(ent.data.size ?? 3);
    vis.g.poly(hexPoly(size * 0.92, s))
      .stroke({ width: 2, color: mat.top, alpha: pulse(timeMs, 350, 0.55, 0.35) });
    if (vis.label) {
      const have = Number(ent.data.have ?? 0);
      const need = Number(ent.data.need ?? 1);
      vis.label.text = `${have}/${need}`;
    }
  },
};

export const furnace: KindRenderer = {
  animated: true,
  draw(vis, _ent, _pose, _drawAlt, s, timeMs) {
    const glow = pulse(timeMs, 300, 0.35, 0.2);
    vis.g.circle(0, 0, Math.max(6, s * 2.6)).fill({ color: 0xff9a3c, alpha: glow * 0.5 });
    // squat clay prism with an ember-lit top
    const base = hexPoly(2.2, s);
    const lift = 1.6 * ALT_LIFT * s; // a squat ~1.6 m chimney
    const top: number[] = [];
    for (let i = 0; i < base.length; i += 2) top.push(base[i], base[i + 1] - lift);
    vis.g.poly(base).fill({ color: 0x8f5a3c });
    vis.g.poly(top).fill({ color: 0xc98d68 }).stroke({ width: 1, color: 0x10141c, alpha: 0.5 });
    vis.g.circle(0, -lift, Math.max(2.5, s * 1.0)).fill({ color: 0xffb054, alpha: glow + 0.3 });
  },
};

export const tileCarried: KindRenderer = {
  poseAlt: (_ent, alt) => (alt > 0.5 ? Math.max(0, alt - 1.4) : alt),
  draw(vis, ent, pose, drawAlt, s) {
    const mat = MATERIAL_COLORS[String(ent.data.material)] ?? UNKNOWN_MATERIAL;
    vis.g.poly(hexPoly(1.4, s)).fill({ color: mat.top })
      .stroke({ width: 1, color: mat.sideDark });
    if (drawAlt - pose.groundAlt > 0.3) {
      const ground = project(pose.n, pose.e, pose.groundAlt, s);
      vis.shadow.ellipse(ground.x, ground.y, Math.max(4, s * 1.2), Math.max(2, s * 0.6))
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};
