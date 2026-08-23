/** Viewer page: connect, dead-reckon world frames, render at 60 fps. */

import type { EntityState, EventData, HelloData, TilesData, WorldData }
  from "../shared/protocol";
import { GameSocket } from "../shared/ws";
import { CameraController } from "./controls";
import { DroneRenderer } from "./drones";
import { EntityRenderer } from "./entities";
import { Hud } from "./hud";
import { diffVelocity, predict, smoothPose, type Pose } from "./interp";
import { Scene } from "./scene";
import { TerrainRenderer } from "./terrain";

const CODE_KEY = "dl_room_code";
const CURSOR_IDLE_MS = 3000;
const HINT_MS = 8000;

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
    // a denied fullscreen request is fine; an unhandled rejection is not
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
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

async function boot(): Promise<void> {
  const scene = new Scene();
  await scene.init();
  const controls = new CameraController(scene);
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
  // rendered poses, eased toward the dead-reckoned target each frame
  const dronePoses = new Map<string, Pose>();
  const entityPoses = new Map<string, Pose>();
  let lastTick = performance.now();
  controls.setPoseSource(() => dronePoses);

  const ws = new GameSocket(`/ws/viewer?code=${encodeURIComponent(code)}`);
  ws.on<HelloData>("hello", (d) => {
    scene.setArena(d.arena.half, d.arena.alt_max);
    scene.setHexGeometry(d.arena.hex_size);
    hud.setMission(`mission: ${d.mission}`);
  });
  ws.on<WorldData>("world", (d) => {
    if (d.epoch !== epoch) {
      if (epoch !== -1) {
        droneR.clearTrails();
        dronePoses.clear(); // a new epoch is a teleport, not motion
        entityPoses.clear();
      }
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
  const hint = document.getElementById("nav-hint");
  const hintText = hint?.textContent ?? "";
  window.setTimeout(() => hint?.classList.add("gone"), HINT_MS);
  let shownFollow: string | null = null;

  /** Surface who we are following, and get out of the way once we stop. */
  const updateHint = (): void => {
    const id = controls.following;
    if (id === shownFollow) return;
    shownFollow = id;
    if (!hint) return;
    if (id) {
      const name = cur?.data.drones.find((d) => d.id === id)?.name ?? id;
      hint.textContent = `following ${name} — click empty space to stop`;
      hint.classList.remove("gone");
    } else {
      hint.textContent = hintText;
      hint.classList.add("gone");
    }
  };

  scene.app.ticker.add(() => {
    const now = performance.now();
    // clamped so a backgrounded tab's first frame back doesn't ease for seconds
    const dtMs = Math.min(now - lastTick, 100);
    lastTick = now;
    controls.update(dtMs); // moves the camera before terrain reads the scale
    updateHint();
    terrainR.tick(); // cheap scale-key check; tiles redraw only on change
    if (!cur) return;
    const age = now - cur.at;

    // Drones carry their velocity on the wire: predict where each one is now,
    // then ease toward that so the correction when the next frame lands is
    // absorbed instead of popping.
    const seenDrones = new Set<string>();
    for (const d of cur.data.drones) {
      seenDrones.add(d.id);
      const still = d.on_ground || d.crashed;
      const target: Pose = {
        n: predict(d.n, still ? 0 : d.vn, age),
        e: predict(d.e, still ? 0 : d.ve, age),
        alt: predict(d.alt, still ? 0 : d.valt, age),
        yaw: d.yaw,
      };
      dronePoses.set(d.id, smoothPose(dronePoses.get(d.id), target, dtMs));
    }
    for (const id of dronePoses.keys()) {
      if (!seenDrones.has(id)) dronePoses.delete(id);
    }

    // Entities carry no velocity, so difference the last two frames. A crate
    // under a drone must predict with the same velocity or it detaches.
    const interval = prev ? Math.min(Math.max(cur.at - prev.at, 40), 250) : 100;
    const prevEnts = new Map<string, EntityState>(
      (prev?.data.entities ?? []).map((e) => [e.id, e]));
    const seenEnts = new Set<string>();
    for (const ent of cur.data.entities) {
      seenEnts.add(ent.id);
      const p = prevEnts.get(ent.id);
      const target: Pose = {
        n: predict(ent.n, p ? diffVelocity(p.n, ent.n, interval) : 0, age),
        e: predict(ent.e, p ? diffVelocity(p.e, ent.e, interval) : 0, age),
        alt: predict(ent.alt, p ? diffVelocity(p.alt, ent.alt, interval) : 0, age),
        yaw: 0,
      };
      entityPoses.set(ent.id, smoothPose(entityPoses.get(ent.id), target, dtMs));
    }
    for (const id of entityPoses.keys()) {
      if (!seenEnts.has(id)) entityPoses.delete(id);
    }

    droneR.sync(cur.data.drones, dronePoses);
    entityR.sync(cur.data.entities, entityPoses, now);
  });
}

boot().catch((err: unknown) => {
  // Pixi/WebGL init is what most plausibly failed, so plain DOM only here —
  // an unattended projector must show words, not a silent black page
  console.error("viewer boot failed", err);
  const div = document.createElement("div");
  div.className = "boot-error";
  div.textContent =
    "viewer failed to start — refresh to retry; a WebGL-capable browser is required";
  document.body.appendChild(div);
});
