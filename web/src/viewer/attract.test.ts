/** attractView: the invitation fills the wall while the sky is empty, shrinks
 * to a corner card once someone flies, and disappears only when it can't help
 * (disconnected, or no code to show). */

import { expect, it } from "vitest";
import { attractView } from "./attract";

const HOST = "https://drones.example.org";

it("invites the room while the sky is empty", () => {
  const v = attractView(true, 0, "swallow", HOST);
  expect(v.mode).toBe("full");
  expect(v.show).toBe(true);
  expect(v.code).toBe("swallow");
  expect(v.joinUrl).toBe("https://drones.example.org/submit");
});

it("shrinks to a corner card once someone is flying — latecomers still need the code", () => {
  const v = attractView(true, 1, "swallow", HOST);
  expect(v.mode).toBe("corner");
  expect(v.show).toBe(false);
  expect(v.code).toBe("swallow");
});

it("stays hidden while disconnected — the count is stale then", () => {
  expect(attractView(false, 0, "swallow", HOST).mode).toBe("hidden");
  expect(attractView(false, 3, "swallow", HOST).mode).toBe("hidden");
});

it("has nothing to advertise without a code", () => {
  expect(attractView(true, 0, null, HOST).mode).toBe("hidden");
  expect(attractView(true, 2, "", HOST).mode).toBe("hidden");
});

it("builds one join url whatever the origin's trailing slashes", () => {
  expect(attractView(true, 0, "x", "http://localhost:8000/").joinUrl)
    .toBe("http://localhost:8000/submit");
});
