/** Drop the log lines a reconnect replays.
 *
 * Every student socket opens with the last 50 lines from the ring buffer
 * (api/ws.py), which is right for a fresh page and wrong for the fifth
 * reconnect of a flaky-wifi afternoon: the pane grows a duplicate block each
 * time. Remember the last line we rendered and skip past it. */

import type { LogLine } from "../shared/protocol";

export interface LogCursor {
  ts: number;
  key: string;
}

export interface MergeResult {
  fresh: LogLine[];
  cursor: LogCursor | null;
}

/** Identity of a line: the server sends no ids, but ts+stream+text is stable
 * across a replay of the same buffer. The separator is a newline because the
 * server splits log text on it, so no single line can contain one and forge
 * another line's key. */
export function lineKey(l: LogLine): string {
  return [l.ts, l.stream, l.line].join("\n");
}

export function freshLines(batch: LogLine[], cursor: LogCursor | null): MergeResult {
  if (batch.length === 0) return { fresh: [], cursor };
  let fresh = batch;
  if (cursor !== null) {
    // the last occurrence, because a script that prints the same line twice
    // in the same millisecond must not truncate the batch at the first copy
    let seen = -1;
    for (let i = batch.length - 1; i >= 0; i--) {
      if (lineKey(batch[i]) === cursor.key) { seen = i; break; }
    }
    fresh = seen >= 0
      ? batch.slice(seen + 1)
      // cursor line has already aged out of the ring — fall back to time
      : batch.filter((l) => l.ts > cursor.ts);
  }
  const last = fresh.at(-1);
  return { fresh, cursor: last ? { ts: last.ts, key: lineKey(last) } : cursor };
}
