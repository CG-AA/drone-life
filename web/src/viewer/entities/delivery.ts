/** Kind renderers owned by the delivery mission: crate, dropoff. */

import { COLORS } from "../../shared/theme";
import { project } from "../iso";
import { pulse, type KindRenderer } from "./base";

export const crate: KindRenderer = {
  poseAlt: (_ent, alt) => (alt > 0.5 ? Math.max(0, alt - 1.4) : alt),
  draw(vis, _ent, pose, drawAlt, s) {
    const g = vis.g;
    const u = Math.max(4, s * 1.15); // half-width of the cube
    g.poly([0, -u, u * 0.87, -u * 0.5, 0, 0, -u * 0.87, -u * 0.5])
      .fill({ color: 0xffc46b });
    g.poly([-u * 0.87, -u * 0.5, 0, 0, 0, u, -u * 0.87, u * 0.5])
      .fill({ color: 0xb87a2e });
    g.poly([u * 0.87, -u * 0.5, 0, 0, 0, u, u * 0.87, u * 0.5])
      .fill({ color: 0xdd9c44 });
    g.poly([0, -u, u * 0.87, -u * 0.5, 0, 0, -u * 0.87, -u * 0.5])
      .stroke({ width: 1, color: 0x6b4415 });
    if (drawAlt - pose.groundAlt > 0.3) {
      const ground = project(pose.n, pose.e, pose.groundAlt, s);
      vis.shadow.ellipse(ground.x, ground.y, u, u * 0.5)
        .fill({ color: 0x000000, alpha: 0.3 });
    }
  },
};

export const dropoff: KindRenderer = {
  animated: true,
  init(vis) {
    vis.addLabel("DROPOFF", COLORS.ok, 12, 10);
  },
  draw(vis, _ent, _pose, _drawAlt, s, timeMs) {
    const breathe = pulse(timeMs, 400, 0.75, 0.25);
    for (const [radius, alpha] of [[4.5, 0.9], [3.0, 0.55], [1.5, 0.35]] as const) {
      const r = radius * breathe;
      vis.g.poly([
        project(r, 0, 0, s).x, project(r, 0, 0, s).y,
        project(0, r, 0, s).x, project(0, r, 0, s).y,
        project(-r, 0, 0, s).x, project(-r, 0, 0, s).y,
        project(0, -r, 0, s).x, project(0, -r, 0, s).y,
      ]).stroke({ width: 2, color: COLORS.ok, alpha });
    }
    vis.root.zIndex = -10_000; // flat marker: always under drones/crates
  },
};
