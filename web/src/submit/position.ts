/** Server syntax-error coordinates → a CodeMirror document range.
 *
 * CPython reports 1-based line and column (SyntaxError.lineno/offset, which
 * api/routes_public.py passes through as line/col, using 0 when it has none);
 * CodeMirror wants absolute document offsets. Everything is clamped, because
 * a stale draft can be shorter than the script the server rejected. */

import type { Text } from "@codemirror/state";

export interface DocRange {
  from: number;
  to: number;
}

/** Mark one character at line/col, or the whole line when col is absent. */
export function diagnosticRange(doc: Text, line: number, col: number): DocRange {
  const ln = doc.line(Math.min(Math.max(Math.trunc(line), 1), doc.lines));
  if (col < 1) return { from: ln.from, to: ln.to };
  const from = Math.min(ln.from + Math.trunc(col) - 1, ln.to);
  return { from, to: Math.min(from + 1, ln.to) };
}
