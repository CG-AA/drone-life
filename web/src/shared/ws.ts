/** Reconnecting WebSocket with app-level ping (keeps the OCI proxy awake) and
 * a receive watchdog: the server broadcasts world frames at 10 Hz to every
 * client, so "no message for a while" means the link is dead even when the OS
 * never delivers a TCP reset (lid close, wifi drop, proxy timeout). The
 * watchdog closes the socket, which routes staleness through the same
 * onclose → onStatus(false) → backoff path a clean disconnect takes. */

import { parseEnvelope } from "./protocol";

type Handler = (data: never, t: number) => void;

const PING_MS = 10_000;
const WATCHDOG_MS = 5_000;
const STALE_MS = 25_000;

export class GameSocket {
  private handlers = new Map<string, Handler>();
  private ws: WebSocket | null = null;
  private backoff = 500;
  private pingTimer: number | undefined;
  private watchdogTimer: number | undefined;
  private lastMsgAt = 0;
  private closed = false;

  onStatus: (up: boolean) => void = () => {};
  /** Called when the server refuses the connection (bad code/token). */
  onRejected: (code: number) => void = () => {};
  /** Asked when a socket dies before it ever opened. The server refuses a bad
   * code or token *before* accepting the upgrade, so the browser reports a
   * failed handshake — no close code survives that, and 1006 alone can't tell
   * a wrong room code from a server that is merely down. Answer true and we
   * treat it as a refusal instead of retrying forever in silence. */
  verify: (() => Promise<boolean>) | null = null;
  /** Called once if the server speaks a newer protocol version (stale page). */
  onSkew: () => void = () => {};
  private skewSeen = false;

  constructor(private url: string) {}

  on<T>(type: string, handler: (data: T, t: number) => void): this {
    this.handlers.set(type, handler as Handler);
    return this;
  }

  connect(): void {
    this.closed = false;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    // every callback binds this local socket: a stale socket firing late must
    // never act on (or close) the replacement that this.ws points to by then
    const sock = new WebSocket(`${proto}//${location.host}${this.url}`);
    this.ws = sock;
    let opened = false;
    sock.onopen = () => {
      if (this.ws !== sock) return;
      opened = true;
      this.backoff = 500;
      this.lastMsgAt = Date.now();
      this.onStatus(true);
      this.pingTimer = window.setInterval(() => {
        if (sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: "ping" }));
      }, PING_MS);
      this.watchdogTimer = window.setInterval(() => {
        if (Date.now() - this.lastMsgAt > STALE_MS) sock.close();
      }, WATCHDOG_MS);
    };
    sock.onmessage = (ev) => {
      if (this.ws !== sock) return;
      this.lastMsgAt = Date.now();
      const msg = parseEnvelope(ev.data as string, () => {
        if (!this.skewSeen) {
          this.skewSeen = true;
          this.onSkew();
        }
      });
      if (!msg) return;
      this.handlers.get(msg.type)?.(msg.data as never, msg.t);
    };
    sock.onclose = (ev) => {
      if (this.ws !== sock) return;
      window.clearInterval(this.pingTimer);
      window.clearInterval(this.watchdogTimer);
      this.onStatus(false);
      if (ev.code === 4401 || ev.code === 4403) {
        this.onRejected(ev.code);
        return;
      }
      if (this.closed) return;
      const retry = (): void => {
        if (this.closed || this.ws !== sock) return;
        window.setTimeout(() => this.connect(), this.backoff);
        this.backoff = Math.min(this.backoff * 1.7, 5000);
      };
      if (opened || !this.verify) {
        retry();
        return;
      }
      // a handshake that never opened may be a refusal wearing 1006; ask
      void this.verify().then(
        (rejected) => rejected ? this.onRejected(ev.code) : retry(),
        () => retry(), // couldn't ask: assume the server, not the credential
      );
    };
    sock.onerror = () => sock.close();
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
