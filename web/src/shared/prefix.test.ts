/** derivePrefix: the page's own address says which room's server to talk to. */

import { afterEach, expect, it, vi } from "vitest";
import { derivePrefix, withPrefix } from "./prefix";

afterEach(() => vi.unstubAllGlobals());

it.each([
  ["/r1/submit", "/r1"],
  ["/r1/admin", "/r1"],
  ["/r1/", "/r1"],
  ["/r1", "/r1"],
  ["/submit", ""],
  ["/admin", ""],
  ["/", ""],
  ["", ""],
  [undefined, ""],
  ["/r12/submit", "/r12"],
  ["/lab/r3/", "/lab/r3"],
])("derives the room prefix from %j", (pathname, want) => {
  expect(derivePrefix(pathname)).toBe(want);
});

it("prefixes a server path with the page's room", () => {
  vi.stubGlobal("location", { pathname: "/r2/submit" });
  expect(withPrefix("/api/v1/join")).toBe("/r2/api/v1/join");
  vi.stubGlobal("location", { pathname: "/submit" });
  expect(withPrefix("/api/v1/join")).toBe("/api/v1/join");
});

it("tolerates a stubbed location with no pathname", () => {
  vi.stubGlobal("location", { host: "lab:8000" });
  expect(withPrefix("/ws/viewer")).toBe("/ws/viewer");
});
