/** The room list on the join overlay.
 *
 * The small missions run as several rooms behind the proxy (docs/ROOMS.md),
 * all on the same classroom code; the student picks one by how full it is.
 * Each row comes from that room's own /healthz — a room that does not answer
 * is closed (stopped for the siege, or never started), a room at its cap is
 * full, and neither is a link. Pure so the rule is testable; main.ts polls
 * and renders. */

import type { Health, RoomRow } from "../shared/protocol";

export type RoomStatus = "open" | "full" | "closed";

export interface RoomView {
  id: string;
  href: string;
  label: string;
  status: RoomStatus;
  /** what the right-hand column says: `12/20`, `full 20/20`, `closed` */
  seats: string;
  mission: string;
}

/** `r1` → `Room 1`; anything else is shown as typed. ROOM_LABEL wins. */
export function roomName(id: string, label = ""): string {
  const custom = label.trim();
  if (custom) return custom;
  const m = /^r(\d+)$/.exec(id);
  return m ? `Room ${m[1]}` : id;
}

export function describeRoom(room: RoomRow, h: Health | null): RoomView {
  const href = `${room.path}/submit`;
  if (!h || !h.ok) {
    return { id: room.id, href, label: roomName(room.id, h?.label), status: "closed",
             seats: "closed", mission: h?.mission ?? "" };
  }
  const full = h.students >= h.max_students;
  return {
    id: room.id, href, label: roomName(room.id, h.label),
    status: full ? "full" : "open",
    seats: `${full ? "full " : ""}${h.students}/${h.max_students}`,
    mission: h.mission,
  };
}

/** The room this page is already in, if its prefix names one of them. */
export function currentRoom(rooms: RoomRow[], prefix: string): RoomRow | null {
  return rooms.find((r) => r.path === prefix) ?? null;
}

/** Nothing to pick when every room is closed — the siege runs on this server
 * now, and the plain join form underneath is the right thing to leave. */
export function worthListing(views: RoomView[]): boolean {
  return views.some((v) => v.status !== "closed");
}
