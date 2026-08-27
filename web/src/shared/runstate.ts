/** Reading a run state the way a person does.
 *
 * The wire has three states and an exit code; a reader has five questions,
 * and the one the wire hides is whether "exited" was success or wreckage.
 * Shared because the student's pill and the instructor's roster must not
 * disagree about what a run is doing. */

import type { RunState } from "./protocol";

export type RunClass = "idle" | "starting" | "running" | "done" | "failed";

export function runClass(rs: RunState | null): RunClass {
  if (rs === null) return "idle";
  if (rs.state !== "exited") return rs.state;
  // null means we stopped it (kill, resubmit) — deliberate, not a failure
  return rs.exit_code === null || rs.exit_code === 0 ? "done" : "failed";
}

/** Pinned to manager.py's END_REASONS by ui.test.ts — "error" is absent on
 * purpose: it renders its exit code, which is the student's debugging handle. */
export const END_LABEL: Record<string, string> = {
  done: "finished",
  timeout: "timed out",
  stopped: "stopped",
  replaced: "replaced",
  start_failed: "failed to start",
  runner_failed: "sandbox error",
};

/** How an ended run reads. An exit code alone doesn't say what happened, so
 * prefer the server's reason; "error" and an older server fall back to the
 * code, which is what the student debugs against. */
export function endLabel(rs: RunState | null): string {
  const label = rs?.reason ? END_LABEL[rs.reason] : undefined;
  if (label) return label;
  return rs?.exit_code ? `exited (${rs.exit_code})` : "exited";
}

/** Short enough for a table cell: "running 12m", "timed out", "exited (137)". */
export function pillLabel(rs: RunState | null, age: number): string {
  const cls = runClass(rs);
  if (cls === "idle") return "idle";
  if (cls === "done" || cls === "failed") return endLabel(rs);
  return `${cls} ${formatAge(age)}`;
}

/** Coarse on purpose — this is read at a glance, not timed. */
export function formatAge(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h${m % 60}m`;
}
