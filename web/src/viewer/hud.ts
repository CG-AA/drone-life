/** DOM overlay: big team score, event feed ticker, connection dot. */

import type { EventData } from "../shared/protocol";

const FEED_MAX = 8;
const FEED_TTL_MS = 45_000;

export class Hud {
  private score = document.getElementById("score")!;
  private mission = document.getElementById("mission")!;
  private feed = document.getElementById("feed")!;
  private conn = document.getElementById("conn")!;
  private lastScore = 0;

  setScore(value: number): void {
    if (value !== this.lastScore) {
      this.lastScore = value;
      this.score.textContent = String(value);
      this.score.animate(
        [{ transform: "scale(1.35)" }, { transform: "scale(1)" }],
        { duration: 350, easing: "ease-out" });
    }
  }

  setMission(text: string): void {
    this.mission.textContent = text;
  }

  addEvent(ev: EventData): void {
    const div = document.createElement("div");
    div.textContent = ev.msg;
    if (ev.kind === "score" || ev.kind === "delivery") div.className = "score";
    if (ev.kind === "crashed" || ev.kind === "crate_lost") div.className = "crash";
    this.feed.prepend(div);
    while (this.feed.childElementCount > FEED_MAX) this.feed.lastElementChild?.remove();
    setTimeout(() => {
      div.style.opacity = "0";
      setTimeout(() => div.remove(), 1000);
    }, FEED_TTL_MS);
  }

  setConn(up: boolean): void {
    this.conn.classList.toggle("up", up);
    this.conn.textContent = up ? "live" : "reconnecting…";
  }
}
