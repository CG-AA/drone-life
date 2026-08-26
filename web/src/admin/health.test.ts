/** formatHealth: the instructor should know the sim is stalled without
 * reading JSON, and a tick rate needs two samples to exist at all. */

import { expect, it } from "vitest";

import { formatHealth } from "./health";
import type { Health } from "../shared/protocol";

function health(over: Partial<Health> = {}): Health {
  return {
    ok: true, drones: 3, ticks: 20_000, overruns: 24, score: 40, mission: "delivery",
    students: 12, uptime_s: 8040, driver_alive: true, last_tick_age_s: 0.03,
    driver_errors: 0, ...over,
  };
}

it("reports rate, overruns, students and uptime once it has two samples", () => {
  const line = formatHealth(health(), { ticks: 19_940, at: 1_000 }, 4_000);
  expect(line).toBe("sim ok — 20.0 ticks/s — overruns 0.12% — 12 students — up 2h 14m");
});

it("omits the rate on the first sample rather than inventing one", () => {
  const line = formatHealth(health(), null, 4_000);
  expect(line).not.toContain("ticks/s");
  expect(line).toContain("overruns 0.12%");
});

it("names sim errors only when there are some", () => {
  expect(formatHealth(health(), null, 0)).not.toContain("sim errors");
  expect(formatHealth(health({ driver_errors: 7 }), null, 0)).toContain("7 sim errors");
});

it("shouts when the sim is stalled and says how stale", () => {
  const line = formatHealth(health({ ok: false, last_tick_age_s: 12.4 }), null, 0);
  expect(line).toContain("SIM STALLED");
  expect(line).toContain("12.4s ago");
});

it("distinguishes a dead loop from a merely stale one", () => {
  const line = formatHealth(health({ ok: false, driver_alive: false }), null, 0);
  expect(line).toContain("the sim loop is gone");
});

it("shows short uptimes in seconds and minutes", () => {
  expect(formatHealth(health({ uptime_s: 42 }), null, 0)).toContain("up 42s");
  expect(formatHealth(health({ uptime_s: 300 }), null, 0)).toContain("up 5m");
});
