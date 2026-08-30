import { expect, it } from "vitest";
import type { AdminInfo, RestartResult } from "../shared/protocol";
import { banRows, describeRoom, looksLikeAddress, restartNotice, uptime } from "./info";

const info = (o: Partial<AdminInfo> = {}): AdminInfo => ({
  room: "main", label: "", mission: "freefly", mission_env: "freefly", mission_override: null,
  missions: ["freefly", "siege"], bot_scripts: ["bot_patrol"], supervised: true,
  admin_port: 8121, uptime_s: 3720, ...o,
});

it("formats uptime coarsely", () => {
  expect(uptime(45)).toBe("45s");
  expect(uptime(61)).toBe("1m");
  expect(uptime(3720)).toBe("1h02");
  expect(uptime(-3)).toBe("0s");
});

it("names the room, the mission's source, the console port and the restart story", () => {
  expect(describeRoom(info())).toBe(
    "main · mission freefly (MISSION=) · console :8121 · up 1h02 · restart: systemd brings it back");
  expect(describeRoom(info({ label: "Room 1", mission: "siege", mission_override: "siege",
    supervised: false, admin_port: 0, uptime_s: 12 }))).toBe(
    "main · Room 1 · mission siege (override; MISSION=freefly ignored) · console on the public port" +
    " · up 12s · restart: by hand");
  expect(describeRoom(info({ mission_override: "freefly" }))).toContain("(override; same as MISSION=)");
});

it("says whether anyone will bring the server back", () => {
  const r: RestartResult = { restarting: true, mission: "siege", supervised: true };
  expect(restartNotice(r, true)).toBe(
    "restarting into siege — systemd brings the room back in a few seconds; pages reconnect on their own");
  expect(restartNotice({ ...r, supervised: false }, false)).toMatch(
    /^restarting — nobody will bring it back: start the server again by hand/);
});

it("lists bans first, then lockouts with the time left", () => {
  const rows = banRows({ names: ["mal"], ips: ["10.0.0.5"],
    lockouts: [{ ip: "10.0.0.9", remaining_s: 890 }, { ip: "10.0.0.8", remaining_s: null }] });
  expect(rows).toEqual([
    { kind: "name", key: "mal", label: "mal" },
    { kind: "ip", key: "10.0.0.5", label: "10.0.0.5" },
    { kind: "lockout", key: "10.0.0.9", label: "10.0.0.9 · 15 min left" },
    { kind: "lockout", key: "10.0.0.8", label: "10.0.0.8 · until restart" },
  ]);
  expect(banRows({ names: [], ips: [], lockouts: [{ ip: "x", remaining_s: 3 }] })[0].label)
    .toBe("x · 1 min left");
});

it("tells an address from a name, loosely", () => {
  expect(looksLikeAddress("10.0.0.5")).toBe(true);
  expect(looksLikeAddress("fe80::1")).toBe(true);
  expect(looksLikeAddress("Mallory")).toBe(false);
  expect(looksLikeAddress("123")).toBe(false);
});
