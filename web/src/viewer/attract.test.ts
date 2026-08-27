/** attractView: the pre-class screen shows only when it can actually help —
 * connected, nobody flying, and a code worth putting on the wall. */

import { expect, it } from "vitest";
import { attractView } from "./attract";

const HOST = "https://drones.example.org";

it("invites the room while the sky is empty", () => {
  const v = attractView(true, 0, "swallow", HOST);
  expect(v.show).toBe(true);
  expect(v.code).toBe("swallow");
  expect(v.joinUrl).toBe("https://drones.example.org/submit");
});

it("gets out of the way once someone is flying", () => {
  expect(attractView(true, 1, "swallow", HOST).show).toBe(false);
});

it("stays hidden while disconnected — the count is stale then", () => {
  expect(attractView(false, 0, "swallow", HOST).show).toBe(false);
});

it("has nothing to advertise without a code", () => {
  expect(attractView(true, 0, null, HOST).show).toBe(false);
  expect(attractView(true, 0, "", HOST).show).toBe(false);
});

it("builds one join url whatever the origin's trailing slashes", () => {
  expect(attractView(true, 0, "x", "http://localhost:8000/").joinUrl)
    .toBe("http://localhost:8000/submit");
});
