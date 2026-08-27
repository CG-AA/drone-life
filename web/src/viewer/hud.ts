/** DOM overlay: big team score, event feed ticker, connection dot. */

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
  tile_placed: "",
  stale: "danger", // client-side: protocol version skew, page needs a refresh
};

export class Hud {
  private score = document.getElementById("score")!;
  private mission = document.getElementById("mission")!;
  private feed = document.getElementById("feed")!;
  private conn = document.getElementById("conn")!;
  private lastScore = 0;

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
