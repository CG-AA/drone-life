/** Reconnecting WebSocket with app-level ping (keeps the OCI proxy awake). */

import { parseEnvelope } from "./protocol";

type Handler = (data: never, t: number) => void;

export class GameSocket {
  private handlers = new Map<string, Handler>();
  private ws: WebSocket | null = null;
  private backoff = 500;
  private pingTimer: number | undefined;
  private closed = false;

  onStatus: (up: boolean) => void = () => {};
  /** Called when the server refuses the connection (bad code/token). */
  onRejected: (code: number) => void = () => {};
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
    this.ws = new WebSocket(`${proto}//${location.host}${this.url}`);
    this.ws.onopen = () => {
      this.backoff = 500;
      this.onStatus(true);
      this.pingTimer = window.setInterval(
        () => this.ws?.send(JSON.stringify({ type: "ping" })), 20000);
    };
    this.ws.onmessage = (ev) => {
      const msg = parseEnvelope(ev.data as string, () => {
        if (!this.skewSeen) {
          this.skewSeen = true;
          this.onSkew();
        }
      });
      if (!msg) return;
      this.handlers.get(msg.type)?.(msg.data as never, msg.t);
    };
    this.ws.onclose = (ev) => {
      window.clearInterval(this.pingTimer);
      this.onStatus(false);
      if (ev.code === 4401 || ev.code === 4403) {
        this.onRejected(ev.code);
        return;
      }
      if (!this.closed) {
        window.setTimeout(() => this.connect(), this.backoff);
        this.backoff = Math.min(this.backoff * 1.7, 5000);
      }
    };
    this.ws.onerror = () => this.ws?.close();
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
