/** What the roster looks like from across the room.
 *
 * The instructor has one question — who needs me? — and about two seconds to
 * answer it. The server sends no timestamps, so elapsed time is tracked here
 * across polls: a run whose state hasn't changed in a long while is the shape
 * a stuck student takes. Pure; the console renders what these return. */

import type { RosterStudent } from "../shared/protocol";
import { runClass } from "../shared/runstate";

/** Identity of "this student in this state": ages restart when it changes. */
export function stateKey(s: RosterStudent): string {
  return [s.student_id, s.run?.run_id ?? "-", runClass(s.run)].join("\n");
}

/** How long each student has been in their current state. Called once per
 * poll; carries the start time forward while the key holds, and forgets
 * students who have left. */
export function updateAges(prev: ReadonlyMap<string, number>,
                           students: RosterStudent[],
                           now: number): Map<string, number> {
  const next = new Map<string, number>();
  for (const s of students) {
    const key = stateKey(s);
    next.set(key, prev.get(key) ?? now);
  }
  return next;
}

export function ageMs(ages: ReadonlyMap<string, number>, s: RosterStudent,
                      now: number): number {
  return now - (ages.get(stateKey(s)) ?? now);
}

/** Why a row wants attention — in the order an instructor should walk over. */
export type Attention = "failed" | "crashed" | "stuck" | "none";

export const STUCK_AFTER_MS = 10 * 60_000;

export function attention(s: RosterStudent, age: number,
                          stuckAfter = STUCK_AFTER_MS): Attention {
  if (runClass(s.run) === "failed") return "failed";
  if (s.crashed) return "crashed";
  // a long-running script is not wrong, but at ten minutes it is worth a look:
  // the usual cause is a loop with no exit, and the student won't say so
  if (runClass(s.run) === "running" && age >= stuckAfter) return "stuck";
  return "none";
}

const RANK: Record<Attention, number> = { failed: 0, crashed: 1, stuck: 2, none: 3 };

/** Rows that need help first, then by slot. Stable, so equal rows keep the
 * server's order and the table doesn't shuffle under the cursor. */
export function orderRoster(students: RosterStudent[],
                            ages: ReadonlyMap<string, number>,
                            now: number): RosterStudent[] {
  return [...students].sort((a, b) => {
    const d = RANK[attention(a, ageMs(ages, a, now))]
      - RANK[attention(b, ageMs(ages, b, now))];
    return d !== 0 ? d : a.slot - b.slot;
  });
}

