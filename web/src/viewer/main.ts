/** Viewer page: connect, buffer world frames, render interpolated at 60 fps. */

import type { DroneState, EntityState, EventData, HelloData, TilesData, WorldData }
  from "../shared/protocol";
import { GameSocket } from "../shared/ws";
import { DroneRenderer } from "./drones";
import { EntityRenderer } from "./entities";
import { Hud } from "./hud";
import { lerpAngle } from "./iso";
import { Scene } from "./scene";
import { TerrainRenderer } from "./terrain";

const CODE_KEY = "dl_room_code";
const CURSOR_IDLE_MS = 3000;

/** Unattended-projector polish: hide the cursor after a few idle seconds,
 * toggle fullscreen on double-click. */
function projectorControls(): void {
  let idleTimer = 0;
  const wake = (): void => {
    document.body.classList.remove("cursor-idle");
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(
      () => document.body.classList.add("cursor-idle"), CURSOR_IDLE_MS);
  };
  window.addEventListener("pointermove", wake);
  wake();
  window.addEventListener("dblclick", () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen();
  });
}

interface Frame {
  data: WorldData;
  at: number; // performance.now() when received
}

async function askRoomCode(): Promise<string> {
  const overlay = document.getElementById("join-overlay")!;
  const form = document.getElementById("code-form") as HTMLFormElement;
  const input = document.getElementById("code-input") as HTMLInputElement;
  overlay.classList.remove("hidden");
  input.focus();
  return new Promise((resolve) => {
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const code = input.value.trim();
      if (!code) return;
      overlay.classList.add("hidden");
      resolve(code);
    });
  });
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

async function boot(): Promise<void> {
  const scene = new Scene();
  await scene.init();
  const hud = new Hud();
  const droneR = new DroneRenderer(scene);
  const entityR = new EntityRenderer(scene);
  const terrainR = new TerrainRenderer(scene);

  let code = localStorage.getItem(CODE_KEY);
  if (!code) {
    code = await askRoomCode();
    localStorage.setItem(CODE_KEY, code);
  }

  let prev: Frame | null = null;
  let cur: Frame | null = null;
  let epoch = -1;

  const ws = new GameSocket(`/ws/viewer?code=${encodeURIComponent(code)}`);
  ws.on<HelloData>("hello", (d) => {
    scene.setArena(d.arena.half, d.arena.alt_max);
    hud.setMission(`mission: ${d.mission}`);
  });
  ws.on<WorldData>("world", (d) => {
    if (d.epoch !== epoch) {
      if (epoch !== -1) droneR.clearTrails();
      epoch = d.epoch;
    }
    prev = cur;
    cur = { data: d, at: performance.now() };
    hud.setScore(d.score);
    scene.drawPads(d.pads);
  });
  ws.on<TilesData>("tiles", (d) => terrainR.set(d));
  ws.on<EventData>("event", (ev) => hud.addEvent(ev));
  ws.onStatus = (up) => hud.setConn(up);
  ws.onRejected = () => {
    localStorage.removeItem(CODE_KEY);
    location.reload();
  };
  ws.onSkew = () => {
    hud.setMission("page out of date — refresh");
    hud.addEvent({ kind: "stale", msg: "this page is out of date — refresh to reconnect",
                   student_id: null, data: {}, t: 0 });
  };
  ws.connect();
  projectorControls();

  scene.app.ticker.add(() => {
    terrainR.tick(); // cheap scale-key check; tiles redraw only on change
    if (!cur) return;
    const now = performance.now();
    const interval = prev ? Math.max(40, cur.at - prev.at) : 100;
    const alpha = Math.min((now - cur.at) / interval, 1.3);

    const dronePose = new Map<string, { n: number; e: number; alt: number; yaw: number }>();
    const prevDrones = new Map<string, DroneState>(
      (prev?.data.drones ?? []).map((d) => [d.id, d]));
    for (const d of cur.data.drones) {
      const p = prevDrones.get(d.id);
      dronePose.set(d.id, p
        ? { n: lerp(p.n, d.n, alpha), e: lerp(p.e, d.e, alpha),
            alt: lerp(p.alt, d.alt, alpha), yaw: lerpAngle(p.yaw, d.yaw, alpha) }
        : d);
    }
    const entityPose = new Map<string, { n: number; e: number; alt: number }>();
    const prevEnts = new Map<string, EntityState>(
      (prev?.data.entities ?? []).map((e) => [e.id, e]));
    for (const ent of cur.data.entities) {
      const p = prevEnts.get(ent.id);
      entityPose.set(ent.id, p
        ? { n: lerp(p.n, ent.n, alpha), e: lerp(p.e, ent.e, alpha),
            alt: lerp(p.alt, ent.alt, alpha) }
        : ent);
    }

    droneR.sync(cur.data.drones, dronePose);
    entityR.sync(cur.data.entities, entityPose, now);
  });
}

void boot();
