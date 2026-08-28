/** Pins the HUD severity table to the server's event-kind registry
 * (server/app/game/events.py) so neither side drifts silently. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { EVENT_CLASS, stripModel } from "./hud";

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
  const active = stripModel({ ...base, wave: 3, state: "active", timer_s: 0,
                              creeps_alive: 2, pending: 5, towers: 1 })!;
  expect(active.wave).toBe("WAVE 3");
  expect(active.phase).toBe("7 CREEPS LEFT");
  expect(active.towers).toBe("1 TOWER");
  const build = stripModel({ ...base, wave: 3, state: "build", timer_s: 12, keep_hp: 2 })!;
  expect(build.phase).toBe("WAVE 4 IN 12s");
  expect(build.keepLow).toBe(true);
  expect(build.keepText).toBe("2/10");
  expect(build.keepPct).toBe(20);
});
