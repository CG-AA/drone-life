/** freshLines: a reconnect replays the log ring, and the pane must not grow a
 * second copy of what the student already read. */

import { expect, it } from "vitest";
import type { LogLine } from "../shared/protocol";
import { freshLines, lineKey } from "./logmerge";

const line = (ts: number, text: string): LogLine =>
  ({ ts, stream: "stdout", line: text });

/** A cursor pointing at a line the pane has already rendered. */
const at = (l: LogLine) => ({ ts: l.ts, key: lineKey(l) });

const run = [line(1, "takeoff"), line(2, "flying"), line(3, "landed")];

it("passes everything through on a fresh page", () => {
  const r = freshLines(run, null);
  expect(r.fresh).toEqual(run);
  expect(r.cursor).toEqual(at(run[2]));
});

it("drops a replay of exactly what we already have", () => {
  const first = freshLines(run, null);
  expect(freshLines(run, first.cursor).fresh).toEqual([]);
});

it("keeps only what came after the overlap", () => {
  const first = freshLines(run.slice(0, 2), null);
  const replay = [...run, line(4, "done")];
  expect(freshLines(replay, first.cursor).fresh)
    .toEqual([line(3, "landed"), line(4, "done")]);
});

it("falls back to timestamps when the cursor line aged out of the ring", () => {
  const cursor = { ts: 2, key: lineKey(line(2, "no longer in the ring")) };
  expect(freshLines(run, cursor).fresh).toEqual([line(3, "landed")]);
});

it("splits at the last copy of a line printed twice in one millisecond", () => {
  const tick = line(1, "tick");
  expect(freshLines([tick, tick, line(2, "after")], at(tick)).fresh)
    .toEqual([line(2, "after")]);
});

it("holds the cursor when a batch is empty", () => {
  const cursor = at(line(7, "x"));
  const r = freshLines([], cursor);
  expect(r.fresh).toEqual([]);
  expect(r.cursor).toBe(cursor);
});

it("distinguishes stdout from stderr at the same instant", () => {
  const both: LogLine[] = [
    { ts: 1, stream: "stdout", line: "same" },
    { ts: 1, stream: "stderr", line: "same" },
  ];
  expect(freshLines(both, at(both[0])).fresh).toEqual([both[1]]);
});
