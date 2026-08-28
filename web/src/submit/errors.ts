/** Every failure a student can hit, turned into words they can act on.
 *
 * The server's error envelope is terse and occasionally raw (a 503 carries a
 * Python exception string), so this is the one place that decides what a
 * twelve-year-old sees and what they should do next. Pure: main.ts renders,
 * this decides. */

import { ApiFailure } from "../shared/http";
import type { ApiError } from "../shared/http";

/** Which call failed — the same code means different things per route. */
export type ErrorContext = "join" | "submit" | "stop" | "template" | "status";

/** rejoin re-opens the join overlay; retry re-runs the action; dismiss clears. */
export type ActionKind = "rejoin" | "retry" | "dismiss";

export interface ErrorAction {
  label: string;
  kind: ActionKind;
}

export interface ErrorView {
  text: string;
  tone: "error" | "info";
  actions: ErrorAction[];
  /** Where to put the cursor, for syntax errors that name a place. */
  goto?: { line: number; col: number };
}

/** The server's cap, mirrored so we can refuse a too-big script without the
 * round trip (server: MAX_CODE_BYTES in api/routes_public.py). */
export const MAX_CODE_BYTES = 64 * 1024;

const REJOIN: ErrorAction = { label: "join again", kind: "rejoin" };
const RETRY: ErrorAction = { label: "try again", kind: "retry" };

/** Byte length if the script is over the limit, else null. */
export function codeTooBig(code: string, limit = MAX_CODE_BYTES): number | null {
  const bytes = new TextEncoder().encode(code).length;
  return bytes > limit ? bytes : null;
}

/** The client pre-check knows the real size; the server's 413 doesn't say. */
export function tooBigText(bytes?: number): string {
  const size = bytes === undefined ? "" : ` (${Math.ceil(bytes / 1024)} KB)`;
  return `your script${size} is over the 64 KB limit — trim it down and run again`;
}

function view(text: string, actions: ErrorAction[] = [],
              tone: "error" | "info" = "error"): ErrorView {
  return { text, tone, actions };
}

/** Turn anything thrown by the api helpers into something worth reading. */
export function describeError(e: unknown, ctx: ErrorContext): ErrorView {
  if (!(e instanceof ApiFailure)) {
    // fetch rejects with a TypeError when the network is gone, not an
    // ApiFailure — the classroom wifi, almost always
    return view("can't reach the server — check the wifi, then try again", [RETRY]);
  }
  return fromApiError(e.error, e.status, ctx);
}

function fromApiError(err: ApiError, status: number, ctx: ErrorContext): ErrorView {
  switch (err.code) {
    case "syntax": {
      // line 0 means CPython couldn't place the error (usually EOF)
      const line = err.line ?? 0;
      if (line < 1) return view(`${err.msg} — check the end of your script`);
      const v = view(`line ${line}: ${err.msg}`);
      return { ...v, goto: { line, col: err.col ?? 0 } };
    }
    case "too_big":
      return view(tooBigText());
    case "runner": {
      // the raw text can carry a Python exception — true, and useless to a
      // student. But the server ends these with the instructor's actual fix
      // ("run `make image`"), and the only person who can act on it is standing
      // in the room, so that clause is exactly what to put on screen.
      const fix = /—\s*instructor:\s*(.+)$/.exec(err.msg)?.[1]?.trim();
      return view("the drone box didn't start — that's a server problem, not "
        + "your code. Tell your instructor"
        + (fix ? `: ${fix}` : "."));
    }
    case "auth":
      return ctx === "join"
        ? view(err.msg, [RETRY])
        : view("your session expired — join again to keep flying", [REJOIN]);
    case "rate":
      // two different limiters answer 429. Submitting is per-student, so this
      // one IS the student's own doing; joining keys on IP, which behind the
      // workshop proxy the whole class shares.
      return ctx === "submit"
        ? view("you're pressing Run too fast — wait a few seconds, then try again",
               [RETRY])
        : view("the whole class is joining at once — wait a moment, then "
          + "try again", [RETRY]);
    case "room_code":
      return view("that room code isn't right — check the board, or ask your "
        + "instructor");
    case "room_full":
      return view(`${err.msg} — ask your instructor to free a slot`);
    case "name":
      return view(err.msg); // already plain: length limits and the Bot- rule
    case "template":
      return view("couldn't load that template — try again", [RETRY]);
    default:
      // unknown code, or a shape with no error envelope at all (FastAPI's
      // 422 validation body, a proxy error page)
      return view(`something went wrong (${err.code} ${status}) — try again, `
        + "and tell your instructor if it keeps happening", [RETRY]);
  }
}
