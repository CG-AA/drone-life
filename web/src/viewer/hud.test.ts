/** Pins the HUD severity table to the server's event-kind registry
 * (server/app/game/events.py) so neither side drifts silently. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { EVENT_CLASS, boardModel, foldedText, foldsInto, roomQuestText, splashFor, stripModel }
  from "./hud";

const CLIENT_ONLY = new Set(["stale"]);

function serverKinds(): string[] {
  const path = fileURLToPath(
    new URL("../../../server/app/game/events.py", import.meta.url));
  const src = readFileSync(path, "utf8");
  const block = src.split("# BEGIN-EVENT-KINDS")[1]?.split("# END-EVENT-KINDS")[0];
  expect(block, "marker block missing from events.py").toBeTruthy();
  return [...block!.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

it("covers every server event kind (list neutrals explicitly as \"\")", () => {
  const kinds = serverKinds();
  expect(kinds.length).toBeGreaterThan(15);
  for (const kind of kinds) {
    expect(EVENT_CLASS, `event kind ${kind} missing from EVENT_CLASS`).toHaveProperty(kind);
  }
});

it("lists no kinds the server no longer emits", () => {
  const kinds = new Set(serverKinds());
  for (const kind of Object.keys(EVENT_CLASS)) {
    if (!CLIENT_ONLY.has(kind)) {
      expect(kinds.has(kind), `stale HUD kind ${kind}`).toBe(true);
    }
  }
});

it("shows no strip for missions that publish nothing", () => {
  expect(stripModel({})).toBeNull();
  expect(stripModel({ crates: 3, delivered: 0 })).toBeNull();
});

it("words each siege phase for the wall", () => {
  const base = { wave: 0, state: "grace", timer_s: 45, keep_hp: 10, keep_max: 10,
                 creeps_alive: 0, pending: 0, towers: 0 };
  const grace = stripModel(base)!;
  expect(grace.wave).toBe("GET READY");
  expect(grace.phase).toBe("FIRST WAVE IN 45s");
  expect(grace.keepPct).toBe(100);
  expect(grace.keepLow).toBe(false);
  expect(grace.towers).toBe("0 TOWERS");
  expect(grace.pot).toBe("");  // an older server: no pot to show
  const active = stripModel({ ...base, wave: 3, state: "active", timer_s: 0,
                              creeps_alive: 2, pending: 5, towers: 1, pool: 45 })!;
  expect(active.wave).toBe("WAVE 3");
  expect(active.phase).toBe("7 CREEPS LEFT");
  expect(active.towers).toBe("1 TOWER");
  expect(active.pot).toBe("POT 45");
  expect(active.quest).toBe("");
  const build = stripModel({ ...base, wave: 3, state: "build", timer_s: 12, keep_hp: 2 })!;
  expect(build.phase).toBe("WAVE 4 IN 12s");
  expect(build.keepLow).toBe(true);
  expect(build.keepText).toBe("2/10");
  expect(build.keepPct).toBe(20);
});

it("keeps last round's record on the strip until the next round starts", () => {
  const base = { wave: 0, state: "grace", timer_s: 45, keep_hp: 10, keep_max: 10,
                 creeps_alive: 0, pending: 0, towers: 0 };
  expect(stripModel(base)!.record).toBe("");
  expect(stripModel({ ...base, last_round: null })!.record).toBe("");
  expect(stripModel({ ...base, last_round: { round: 1, wave: 8, kills: 83, score: 320 } })!.record)
    .toBe("LAST ROUND · WAVE 8 · 320 PTS");
});

const ev = (kind: string, t: number, msg = kind) =>
  ({ kind, msg, student_id: null, data: {}, t });

it("puts a wave start on the banner and a milestone on the overlay", () => {
  expect(splashFor(ev("wave_start", 100, "wave 3: 8 creeps"), 101))
    .toEqual({ slot: "banner", text: "wave 3: 8 creeps", cls: "warn", kind: "wave_start" });
  expect(splashFor(ev("milestone", 100), 101)?.slot).toBe("overlay");
  expect(splashFor(ev("keep_fell", 100), 101)?.cls).toBe("danger");
  expect(splashFor(ev("score", 100), 101)).toBeNull();
});

it("ignores replayed history so a reconnect never flashes twenty banners", () => {
  expect(splashFor(ev("wave_start", 40), 100)).toBeNull();
  expect(splashFor(ev("wave_start", 97), 100)).not.toBeNull();
  // before the first world frame the clock is unknown: trust the event
  expect(splashFor(ev("wave_start", 40), 0)).not.toBeNull();
});

it("boards the top pilots best first, hides zeros, breaks ties by name", () => {
  const rows = boardModel([
    { student_id: "s2", name: "zed", points: 20 },
    { student_id: "s1", name: "amy", points: 20 },
    { student_id: "s3", name: "idle", points: 0 },
    { student_id: "s4", name: "bob", points: 35 },
  ]);
  expect(rows.map((r) => r.name)).toEqual(["bob", "amy", "zed"]);
  expect(boardModel(undefined)).toEqual([]);
  // the whole room, not a top-N: a 64-seat siege lists 64 rows
  expect(boardModel(Array.from({ length: 64 }, (_, i) =>
    ({ student_id: `s${i}`, name: `p${i}`, points: 100 - i }))).length).toBe(64);
});

it("words the room quest for the wall", () => {
  expect(roomQuestText(undefined)).toBe("");
  expect(roomQuestText({ solved: 2, missed: 0, room: null })).toBe("");
  expect(roomQuestText({ room: { id: 6, family: "route", left_s: 32.4, solved: false } }))
    .toBe("ROOM QUEST 6 · ROUTE · 32s");
  expect(roomQuestText({ room: { id: 6, family: "compute", left_s: 0, solved: true } }))
    .toBe("ROOM QUEST 6 · COMPUTE · SOLVED");
});

it("folds a burst of pickups into one row, and nothing else", () => {
  expect(foldsInto(null, "pickup", 1000)).toBe(false);
  expect(foldsInto({ kind: "pickup", atMs: 1000 }, "pickup", 2500)).toBe(true);
  expect(foldsInto({ kind: "pickup", atMs: 1000 }, "pickup", 3500)).toBe(false);
  expect(foldsInto({ kind: "pickup", atMs: 1000 }, "ferried", 1500)).toBe(false);
  expect(foldsInto({ kind: "quest_solved", atMs: 1000 }, "quest_solved", 1500)).toBe(false);
  expect(foldsInto({ kind: "tower_up", atMs: 1000 }, "tower_up", 1500)).toBe(false);
  expect(foldedText("pickup", 6)).toBe("pickups ×6");
  expect(foldedText("built", 2)).toBe("tiles placed ×2");
});
