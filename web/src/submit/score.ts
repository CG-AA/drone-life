/** The pilot's own line on the room's board: points and rank among scorers. */

import type { ScoreRow } from "../shared/protocol";

/** "you 12 · #3 of 29 · z12 t2" — or "you 0" before the first point (the
 * server lists only pilots with points, so absence is a zero, not an error). */
export function myScoreText(scores: ScoreRow[] | undefined, studentId: string): string {
  const rows = scores ?? [];
  const i = rows.findIndex((r) => r.student_id === studentId);
  if (i < 0) return "you 0";
  const me = rows[i];
  let text = `you ${me.points} · #${i + 1} of ${rows.length}`;
  if (me.detail) text += ` · ${me.detail}`;
  return text;
}
