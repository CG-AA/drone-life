/** nextFollowId: touring the class with one key, including the awkward
 * moments — nobody flying, and the drone we were watching leaving. */

import { expect, it } from "vitest";
import { nextFollowId } from "./follow";

const roster = ["a", "b", "c"];

it("starts at the first drone", () => {
  expect(nextFollowId(roster, null)).toBe("a");
});

it("steps through and wraps", () => {
  expect(nextFollowId(roster, "a")).toBe("b");
  expect(nextFollowId(roster, "c")).toBe("a");
});

it("starts over when the followed drone has left", () => {
  expect(nextFollowId(roster, "gone")).toBe("a");
});

it("follows nobody in an empty sky", () => {
  expect(nextFollowId([], null)).toBeNull();
  expect(nextFollowId([], "a")).toBeNull();
});

it("stays put with a single drone", () => {
  expect(nextFollowId(["only"], "only")).toBe("only");
});
