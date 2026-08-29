/** DOM overlay: big team score, mission status strip, event feed ticker,
 * connection dot. */

import type { EventData, ScoreRow } from "../shared/protocol";
import { REDUCED_MOTION } from "../shared/theme";

const FEED_MAX = 8;
const FEED_TTL_MS = 45_000;
const BANNER_MS = 2800;
const OVERLAY_MS = 2200;
/** the round summary is the one overlay worth reading twice */
const OVERLAY_LONG: Record<string, number> = { round_end: 7000 };
/** events older than this (sim seconds) are replay on connect, not news */
const FRESH_S = 5;

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
  boss_down: "triumph",
  round_end: "triumph",
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
  restarting: "warn",
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
  /** the record to beat, shown until the next wave 1 ("" when none) */
  record: string;
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
  const last = ms.last_round as Record<string, unknown> | null | undefined;
  const record = last && typeof last.wave === "number"
    ? `LAST ROUND · WAVE ${last.wave} · ${Number(last.score ?? 0)} PTS`
    : "";
  return {
    record,
    wave: wave === 0 ? "GET READY" : `WAVE ${wave}`,
    phase,
    keepPct: Math.max(0, Math.min(100, (hp / max) * 100)),
    keepText: `${hp}/${max}`,
    keepLow: hp <= 3,
    towers: `${towers} TOWER${towers === 1 ? "" : "S"}`,
  };
}

/** Which events get a big moment on the wall, and where. */
export interface Splash { slot: "banner" | "overlay"; text: string; cls: string; kind: string }

const BANNER_KINDS: Record<string, string> = { wave_start: "warn" };
const OVERLAY_KINDS: Record<string, string> = {
  milestone: "triumph",
  keep_fell: "danger",
  boss_down: "triumph",
  round_end: "triumph",
};

/** A splash for `ev`, or null: unknown kind, or stale relative to the sim
 * clock — a fresh socket replays the last 20 feed events, and a wall that
 * flashes twenty banners on every reconnect teaches the room to ignore
 * them. Pure so the rule is testable. */
export function splashFor(ev: EventData, simT: number): Splash | null {
  if (simT > 0 && ev.t < simT - FRESH_S) return null;
  const banner = BANNER_KINDS[ev.kind];
  if (banner !== undefined) return { slot: "banner", text: ev.msg, cls: banner, kind: ev.kind };
  const overlay = OVERLAY_KINDS[ev.kind];
  if (overlay !== undefined) return { slot: "overlay", text: ev.msg, cls: overlay, kind: ev.kind };
  return null;
}

/** The board's rows: top `limit` pilots by points, best first (the server
 * already sorts, but never trust the wire for what the wall shows). Empty
 * when nobody has scored — the panel hides rather than listing zeros. */
export function boardModel(scores: ScoreRow[] | undefined, limit = 8): ScoreRow[] {
  return (scores ?? [])
    .filter((r) => r.points !== 0)
    .sort((a, b) => b.points - a.points || a.name.localeCompare(b.name))
    .slice(0, limit);
}

export class Hud {
  private score = document.getElementById("score")!;
  private board = document.getElementById("board")!;
  private boardRows = document.getElementById("board-rows")!;
  private lastBoard = "";
  private mission = document.getElementById("mission")!;
  private feed = document.getElementById("feed")!;
  private conn = document.getElementById("conn")!;
  private strip = document.getElementById("mstrip")!;
  private banner = document.getElementById("banner")!;
  private overlay = document.getElementById("overlay")!;
  private lastScore = 0;
  private lastStrip = "";
  private simT = 0;
  private timers = { banner: 0, overlay: 0 };

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

  setScores(scores: ScoreRow[] | undefined): void {
    const rows = boardModel(scores);
    const key = rows.map((r) => `${r.student_id}:${r.points}`).join("|");
    if (key === this.lastBoard) return;  // 10 Hz frames, but the board rarely moves
    this.lastBoard = key;
    this.board.hidden = rows.length === 0;
    this.boardRows.replaceChildren(...rows.map((r) => {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = r.name;
      const pts = document.createElement("span");
      pts.className = "pts";
      pts.textContent = String(r.points);
      li.append(name, pts);
      return li;
    }));
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
    const rec = document.getElementById("ms-record")!;
    rec.textContent = m.record;
    rec.hidden = m.record === "";
  }

  /** The sim clock from the latest world frame, for the replay gate. */
  setSimTime(t: number): void {
    this.simT = t;
  }

  /** A wave banner / a full-screen moment — shown for a few seconds, one
   * at a time per slot; a newer one replaces an older one outright. */
  splash(s: Splash): void {
    const el = s.slot === "banner" ? this.banner : this.overlay;
    el.textContent = s.text;
    el.className = s.cls;
    el.hidden = false;
    if (!REDUCED_MOTION) {
      el.classList.remove("in");
      void el.offsetWidth; // restart the entrance animation
      el.classList.add("in");
    }
    window.clearTimeout(this.timers[s.slot]);
    const ms = s.slot === "banner" ? BANNER_MS : (OVERLAY_LONG[s.kind] ?? OVERLAY_MS);
    this.timers[s.slot] = window.setTimeout(() => { el.hidden = true; }, ms);
  }

  addEvent(ev: EventData): void {
    const s = splashFor(ev, this.simT);
    if (s) this.splash(s);
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
