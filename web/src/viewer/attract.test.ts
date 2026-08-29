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

it("advertises the server's PUBLIC_URL over the projector's own origin", () => {
  // the projector is opened on localhost; students come in through the gateway
  expect(attractView(true, 0, "x", "http://localhost:8000", "http://203.0.113.5:8000/").joinUrl)
    .toBe("http://203.0.113.5:8000/submit");
  expect(attractView(true, 3, "x", "http://localhost:8000", "http://203.0.113.5:8000").joinUrl)
    .toBe("http://203.0.113.5:8000/submit");
});

it("falls back to its own origin while PUBLIC_URL is unset or blank", () => {
  expect(attractView(true, 0, "x", HOST, "").joinUrl).toBe("https://drones.example.org/submit");
  expect(attractView(true, 0, "x", HOST, "  ").joinUrl).toBe("https://drones.example.org/submit");
});

it("keeps the room prefix the projector was opened under (main.ts passes origin + prefix)", () => {
  expect(attractView(true, 0, "x", "https://drones.example.org/r2").joinUrl)
    .toBe("https://drones.example.org/r2/submit");
});
