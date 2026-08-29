/** GameSocket's reconnect path. The bug worth a test file: a socket that has
 * been closed and replaced can still be woken by its own pending backoff timer,
 * reconnect with a credential the page has already thrown away, and retry
 * forever alongside its replacement. */

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GameSocket } from "./ws";

class FakeWS {
  static OPEN = 1;
  static live: FakeWS[] = [];

  readyState = 0;
  closedByUs = false;
  onopen: (() => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeWS.live.push(this);
  }

  /** The server accepted the upgrade. */
  open(): void {
    this.readyState = FakeWS.OPEN;
    this.onopen?.();
  }

  /** The handshake died — which is all a browser reports for a refusal. */
  fail(code = 1006): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  close(): void {
    this.closedByUs = true;
    this.readyState = 3;
    this.onclose?.({ code: 1005 });
  }

  send(): void {}
}

const latest = (): FakeWS => FakeWS.live[FakeWS.live.length - 1];

beforeEach(() => {
  FakeWS.live = [];
  vi.useFakeTimers();
  vi.stubGlobal("window", globalThis);
  vi.stubGlobal("location", { protocol: "http:", host: "lab:8000" });
  vi.stubGlobal("WebSocket", FakeWS);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("connects to the url it was given", () => {
  new GameSocket("/ws/viewer?code=abc").connect();
  expect(latest().url).toBe("ws://lab:8000/ws/viewer?code=abc");
});

it("keeps the page's room prefix in front of the socket path", () => {
  vi.stubGlobal("location", { protocol: "https:", host: "drones.example.org", pathname: "/r3/submit" });
  new GameSocket("/ws/student?token=t").connect();
  expect(latest().url).toBe("wss://drones.example.org/r3/ws/student?token=t");
});

it("reconnects after a connection it did not close, with a growing backoff", () => {
  const ws = new GameSocket("/ws/viewer");
  ws.connect();
  latest().open();
  latest().fail();

  vi.advanceTimersByTime(499);
  expect(FakeWS.live).toHaveLength(1); // still waiting out the first backoff
  vi.advanceTimersByTime(1);
  expect(FakeWS.live).toHaveLength(2);

  latest().open();
  latest().fail();
  vi.advanceTimersByTime(500);
  expect(FakeWS.live, "an opened socket resets the backoff").toHaveLength(3);
});

it("stays closed when close() lands while a retry is pending", () => {
  const ws = new GameSocket("/ws/student?token=old");
  ws.connect();
  latest().open();
  latest().fail(); // schedules a reconnect ~500ms out

  ws.close(); // the page moved on: rejoined, or built a fresh socket
  vi.advanceTimersByTime(60_000);

  expect(FakeWS.live, "the dead socket reconnected itself").toHaveLength(1);
});

it("does not report a deliberate close as a lost connection", () => {
  const ws = new GameSocket("/ws/student");
  const status: boolean[] = [];
  ws.onStatus = (up) => status.push(up);
  ws.connect();
  latest().open();
  expect(status).toEqual([true]);

  ws.close();
  expect(status, "a stale 'connection lost' banner outlives the socket")
    .toEqual([true]);
});

it("asks verify whether a handshake that never opened was a refusal", async () => {
  const ws = new GameSocket("/ws/viewer?code=wrong");
  let rejected = 0;
  ws.onRejected = () => { rejected += 1; };
  ws.verify = () => Promise.resolve(true);
  ws.connect();
  latest().fail();

  await vi.waitFor(() => expect(rejected).toBe(1));
  vi.advanceTimersByTime(60_000);
  expect(FakeWS.live, "a refused socket must not keep knocking").toHaveLength(1);
});

it("retries instead of giving up when verify says the credential is fine", async () => {
  const ws = new GameSocket("/ws/viewer?code=right");
  let rejected = 0;
  ws.onRejected = () => { rejected += 1; };
  ws.verify = () => Promise.resolve(false); // server down, not a bad code
  ws.connect();
  latest().fail();

  await vi.waitFor(() => expect(FakeWS.live.length).toBeGreaterThan(0));
  vi.advanceTimersByTime(500);
  expect(rejected).toBe(0);
  expect(FakeWS.live).toHaveLength(2);
});

it("treats an unanswerable verify as a server problem, not a bad credential", async () => {
  const ws = new GameSocket("/ws/viewer?code=right");
  let rejected = 0;
  ws.onRejected = () => { rejected += 1; };
  ws.verify = () => Promise.reject(new Error("offline"));
  ws.connect();
  latest().fail();

  await vi.waitFor(() => expect(FakeWS.live.length).toBeGreaterThan(0));
  vi.advanceTimersByTime(500);
  expect(rejected).toBe(0);
  expect(FakeWS.live).toHaveLength(2);
});
