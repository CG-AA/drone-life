/** DOM overlay: big team score, mission status strip, event feed ticker,
 * connection dot. */

import type { EventData } from "../shared/protocol";
import { REDUCED_MOTION } from "../shared/theme";

const FEED_MAX = 8;
const FEED_TTL_MS = 45_000;

/** Severity class per event kind. The full server-side registry lives in
 * server/app/game/events.py; hud.test.ts pins this table to it, so every kind
 * appears here — neutral ones explicitly as "". `stale` is client-only. */
export const EVENT_CLASS: Record<string, string> = {
  score: "score",
  delivery: "score",
  tile_placed: "score",
  milestone: "triumph",
  wave_clear: "triumph",
  wall_complete: "triumph",
  furnace_lit: "triumph",
  tower_up: "triumph",
  crashed: "danger",
  crate_lost: "danger",
  tile_lost: "danger",
  keep_hit: "danger",
  keep_fell: "danger",
  tower_down: "danger",
  mission_error: "danger",
  wave_start: "warn",
  orphan_rtl: "warn",
  script_exit: "warn",
  reset: "warn",
  joined: "",
  kicked: "",
  respawned: "",
  reset_mine: "",
  crate_spawn: "",
  pickup: "",
  stale: "danger", // client-side: protocol version skew, page needs a refresh
};

/** What the status strip shows, derived from a mission_state frame. Null
 * when the mission publishes nothing the strip knows how to show. Pure, so
 * the wording is testable without a DOM. */
export interface StripModel {
  wave: string;
  phase: string;
  keepPct: number;
  keepText: string;
  keepLow: boolean;
  towers: string;
}

export function stripModel(ms: Record<string, unknown>): StripModel | null {
  if (typeof ms.wave !== "number") return null; // not siege (or not yet hello'd)
  const wave = ms.wave;
  const state = String(ms.state ?? "");
  const timer = Math.max(0, Math.round(Number(ms.timer_s ?? 0)));
  const left = Number(ms.creeps_alive ?? 0) + Number(ms.pending ?? 0);
  let phase: string;
  if (state === "grace") phase = `FIRST WAVE IN ${timer}s`;
  else if (state === "build") phase = `WAVE ${wave + 1} IN ${timer}s`;
  else phase = `${left} CREEP${left === 1 ? "" : "S"} LEFT`;
  const hp = Number(ms.keep_hp ?? 0);
  const max = Math.max(1, Number(ms.keep_max ?? 1));
  const towers = Number(ms.towers ?? 0);
  return {
    wave: wave === 0 ? "GET READY" : `WAVE ${wave}`,
    phase,
    keepPct: Math.max(0, Math.min(100, (hp / max) * 100)),
    keepText: `${hp}/${max}`,
    keepLow: hp <= 3,
    towers: `${towers} TOWER${towers === 1 ? "" : "S"}`,
  };
}

export class Hud {
  private score = document.getElementById("score")!;
  private mission = document.getElementById("mission")!;
  private feed = document.getElementById("feed")!;
  private conn = document.getElementById("conn")!;
  private strip = document.getElementById("mstrip")!;
  private lastScore = 0;
  private lastStrip = "";

  setScore(value: number): void {
    if (value !== this.lastScore) {
      this.lastScore = value;
      this.score.textContent = String(value);
      if (!REDUCED_MOTION) {
        this.score.animate(
          [{ transform: "scale(1.35)" }, { transform: "scale(1)" }],
          { duration: 350, easing: "ease-out" });
      }
    }
  }

  setMission(text: string): void {
    this.mission.textContent = text;
  }

  /** The mission's own numbers, under the score: siege shows the wave, the
   * countdown and the Keep's hp bar — the three things a room asks about. */
  setMissionState(ms: Record<string, unknown>): void {
    const m = stripModel(ms);
    const key = m ? JSON.stringify(m) : "";
    if (key === this.lastStrip) return; // 10 Hz frames, but the text rarely changes
    this.lastStrip = key;
    this.strip.hidden = m === null;
    if (!m) return;
    document.getElementById("ms-wave")!.textContent = m.wave;
    document.getElementById("ms-phase")!.textContent = m.phase;
    document.getElementById("ms-keep-hp")!.textContent = m.keepText;
    const fill = document.getElementById("keep-fill")!;
    fill.style.width = `${m.keepPct}%`;
    fill.classList.toggle("low", m.keepLow);
    document.getElementById("ms-towers")!.textContent = m.towers;
  }

  addEvent(ev: EventData): void {
    const div = document.createElement("div");
    div.textContent = ev.msg;
    div.className = EVENT_CLASS[ev.kind] ?? "";
    this.feed.prepend(div);
    while (this.feed.childElementCount > FEED_MAX) this.feed.lastElementChild?.remove();
    setTimeout(() => {
      div.style.opacity = "0";
      setTimeout(() => div.remove(), 1000);
    }, FEED_TTL_MS);
  }

  setConn(up: boolean): void {
    this.conn.classList.toggle("up", up);
    this.conn.textContent = up ? "live" : "reconnecting…";
  }
}
