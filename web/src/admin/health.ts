/** The instructor's one-line answer to "is the sim actually running?".
 * ticks and overruns are counters since boot, so the rate comes from the
 * delta between two polls — the raw totals say nothing about right now. */

import type { Health } from "../shared/protocol";

export interface HealthSample {
  ticks: number;
  at: number;
}

function uptime(seconds: number): string {
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export function formatHealth(h: Health, prev: HealthSample | null, now: number): string {
  if (!h.ok) {
    const why = h.driver_alive
      ? `last tick ${h.last_tick_age_s.toFixed(1)}s ago`
      : "the sim loop is gone";
    return `SIM STALLED (${why}) — check the server logs`;
  }
  const parts = ["sim ok"];
  if (prev !== null) {
    const elapsed = (now - prev.at) / 1000;
    if (elapsed > 0) parts.push(`${((h.ticks - prev.ticks) / elapsed).toFixed(1)} ticks/s`);
  }
  parts.push(`overruns ${((h.overruns / Math.max(h.ticks, 1)) * 100).toFixed(2)}%`);
  if (h.driver_errors > 0) parts.push(`${h.driver_errors} sim errors`);
  parts.push(`${h.students} students`);
  parts.push(`up ${uptime(h.uptime_s)}`);
  return parts.join(" — ");
}
