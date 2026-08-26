/** diagnosticRange: server line/col land on the right character, and a stale
 * draft that no longer contains that position must not throw. */

import { Text } from "@codemirror/state";
import { expect, it } from "vitest";
import { diagnosticRange } from "./position";

const doc = Text.of(["from dronelife import connect", "", "drone = connect(", "x = 1"]);

it("maps 1-based line and column to a single character", () => {
  const r = diagnosticRange(doc, 1, 6); // the 'd' of dronelife
  expect(doc.sliceString(r.from, r.to)).toBe("d");
});

it("marks the whole line when the server sends no column", () => {
  const r = diagnosticRange(doc, 3, 0);
  expect(doc.sliceString(r.from, r.to)).toBe("drone = connect(");
});

it("clamps a line past the end of the document", () => {
  const r = diagnosticRange(doc, 99, 0);
  expect(doc.sliceString(r.from, r.to)).toBe("x = 1");
});

it("clamps a column past the end of its line", () => {
  const line = doc.line(4);
  const r = diagnosticRange(doc, 4, 500);
  expect(r.from).toBe(line.to);
  expect(r.to).toBe(line.to);
});

it("survives an empty line and a line before the first", () => {
  const empty = diagnosticRange(doc, 2, 3);
  expect(empty.from).toBe(doc.line(2).from);
  expect(empty.to).toBe(doc.line(2).to);
  expect(diagnosticRange(doc, 0, 0).from).toBe(0);
});
