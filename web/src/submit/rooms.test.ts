/** The room list: open rooms are links with a count, full and closed ones are
 * not, and the whole list steps aside once every room is gone. */

import { expect, it } from "vitest";
import type { Health } from "../shared/protocol";
import { currentRoom, describeRoom, roomName, worthListing } from "./rooms";

function health(over: Partial<Health> = {}): Health {
  return {
    ok: true, drones: 3, ticks: 1, overruns: 0, score: 0, mission: "freefly",
    students: 12, room: "r1", label: "", max_students: 20, uptime_s: 1,
    driver_alive: true, last_tick_age_s: 0.03, driver_errors: 0, ...over,
  };
}
const R1 = { id: "r1", path: "/r1" };

it("names rooms from their id unless the room has a label", () => {
  expect(roomName("r1")).toBe("Room 1");
  expect(roomName("r12")).toBe("Room 12");
  expect(roomName("north")).toBe("north");
  expect(roomName("r1", "Room 1 — north tables")).toBe("Room 1 — north tables");
  expect(roomName("r1", "   ")).toBe("Room 1");
});

it("an answering room with seats left is an open link with its count", () => {
  const v = describeRoom(R1, health());
  expect(v).toMatchObject({ status: "open", seats: "12/20", href: "/r1/submit",
                            label: "Room 1", mission: "freefly" });
});

it("a room at its cap is full", () => {
  const v = describeRoom(R1, health({ students: 20 }));
  expect(v.status).toBe("full");
  expect(v.seats).toBe("full 20/20");
});

it("a room that does not answer, or whose sim is stalled, is closed", () => {
  expect(describeRoom(R1, null)).toMatchObject({ status: "closed", seats: "closed", label: "Room 1" });
  expect(describeRoom(R1, health({ ok: false })).status).toBe("closed");
});

it("knows when this page is already inside one of the rooms", () => {
  const rooms = [R1, { id: "r2", path: "/r2" }];
  expect(currentRoom(rooms, "/r2")?.id).toBe("r2");
  expect(currentRoom(rooms, "")).toBeNull();
  expect(currentRoom(rooms, "/r9")).toBeNull();
});

it("steps aside when every room is closed — siege time on this server", () => {
  expect(worthListing([describeRoom(R1, null)])).toBe(false);
  expect(worthListing([describeRoom(R1, null), describeRoom(R1, health({ students: 20 }))])).toBe(true);
});
