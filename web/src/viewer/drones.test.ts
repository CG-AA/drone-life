import { expect, it } from "vitest";
import { tierCount } from "./drones";

it("counts bought tiers for the badge, capped at five chevrons", () => {
  expect(tierCount({})).toBe(0);
  expect(tierCount({ wallet: 40, colour: "#ff8800" })).toBe(0);
  expect(tierCount({ zap: 2, speed: 1 })).toBe(3);
  expect(tierCount({ zap: 3, speed: 2, tower: 2 })).toBe(5);
  expect(tierCount({ zap: "2" })).toBe(0);
});
