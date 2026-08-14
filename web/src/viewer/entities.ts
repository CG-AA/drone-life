/** Mission entities, rendered generically by `kind` — new missions only need a
 * new case here if they invent a new kind. */

import { Container, Graphics, Text } from "pixi.js";
import type { EntityState } from "../shared/protocol";
import { project, projectGround } from "./iso";
import type { Scene } from "./scene";

class EntityVis {
  root = new Container();
  g = new Graphics();
  shadow = new Graphics();

  constructor(public kind: string, scene: Scene) {
    this.root.addChild(this.g);
    scene.spriteLayer.addChild(this.root);
    scene.shadowLayer.addChild(this.shadow);
  }

  destroy(): void {
    this.root.destroy({ children: true });
    this.shadow.destroy();
  }
}

export class EntityRenderer {
  private map = new Map<string, EntityVis>();

  constructor(private scene: Scene) {}

  sync(entities: EntityState[],
       interp: Map<string, { n: number; e: number; alt: number }>,
       timeMs: number): void {
    const seen = new Set<string>();
    for (const ent of entities) {
      seen.add(ent.id);
      let vis = this.map.get(ent.id);
      if (!vis) {
        vis = new EntityVis(ent.kind, this.scene);
        this.map.set(ent.id, vis);
        if (ent.kind === "dropoff") this.addDropLabel(vis);
      }
      const pose = interp.get(ent.id) ?? ent;
      this.draw(vis, ent, pose.n, pose.e, pose.alt, timeMs);
    }
    for (const [id, vis] of this.map) {
      if (!seen.has(id)) {
        vis.destroy();
        this.map.delete(id);
      }
    }
  }

  private addDropLabel(vis: EntityVis): void {
    const label = new Text({
      text: "DROPOFF",
      style: { fontFamily: "Segoe UI, system-ui, sans-serif", fontSize: 12,
               fill: 0x4ade80, fontWeight: "700", letterSpacing: 2 },
    });
    label.anchor.set(0.5, 0);
    label.position.set(0, 10);
    vis.root.addChild(label);
  }

  private draw(vis: EntityVis, ent: EntityState, n: number, e: number, alt: number,
               timeMs: number): void {
    const s = this.scene.scale;
    // carried crates hang a little beneath their carrier
    const drawAlt = ent.kind === "crate" && alt > 0.5 ? Math.max(0, alt - 1.4) : alt;
    const p = project(n, e, drawAlt, s);
    vis.root.position.set(p.x, p.y);
    vis.root.zIndex = p.depth - 0.1; // just behind a drone at the same spot

    const g = vis.g;
    g.clear();
    vis.shadow.clear();

    if (ent.kind === "crate") {
      const u = Math.max(4, s * 1.15); // half-width of the cube
      // top face
      g.poly([0, -u, u * 0.87, -u * 0.5, 0, 0, -u * 0.87, -u * 0.5])
        .fill({ color: 0xffc46b });
      // left + right faces
      g.poly([-u * 0.87, -u * 0.5, 0, 0, 0, u, -u * 0.87, u * 0.5])
        .fill({ color: 0xb87a2e });
      g.poly([u * 0.87, -u * 0.5, 0, 0, 0, u, u * 0.87, u * 0.5])
        .fill({ color: 0xdd9c44 });
      g.poly([0, -u, u * 0.87, -u * 0.5, 0, 0, -u * 0.87, -u * 0.5])
        .stroke({ width: 1, color: 0x6b4415 });
      if (drawAlt > 0.3) {
        const ground = projectGround(n, e, s);
        vis.shadow.ellipse(ground.x, ground.y, u, u * 0.5)
          .fill({ color: 0x000000, alpha: 0.3 });
      }
    } else if (ent.kind === "dropoff") {
      const pulse = 0.75 + 0.25 * Math.sin(timeMs / 400);
      for (const [radius, alpha] of [[4.5, 0.9], [3.0, 0.55], [1.5, 0.35]] as const) {
        const r = radius * pulse;
        g.poly([
          project(r, 0, 0, s).x, project(r, 0, 0, s).y,
          project(0, r, 0, s).x, project(0, r, 0, s).y,
          project(-r, 0, 0, s).x, project(-r, 0, 0, s).y,
          project(0, -r, 0, s).x, project(0, -r, 0, s).y,
        ]).stroke({ width: 2, color: 0x4ade80, alpha });
      }
      vis.root.zIndex = -10_000; // flat marker: always under drones/crates
    } else {
      // unknown kind: neutral diamond so future missions still show something
      g.circle(0, 0, Math.max(4, s)).fill({ color: 0x8899bb, alpha: 0.8 });
    }
  }
}
