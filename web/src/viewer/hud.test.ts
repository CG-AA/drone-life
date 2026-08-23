/** Pins the HUD severity table to the server's event-kind registry
 * (server/app/game/events.py) so neither side drifts silently. */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { EVENT_CLASS } from "./hud";

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
