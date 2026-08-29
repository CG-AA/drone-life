/** What the projector shows so people can join.
 *
 * An empty arena tells a room of students nothing, so while nobody is flying
 * the room code and the address fill the wall. Once the first drone appears
 * the same two facts shrink to a corner card and stay there — a class trickles
 * in over the whole warmup, and every latecomer would otherwise have to ask.
 * Pure so the rule is testable; main.ts owns the DOM. */

export type AttractMode = "full" | "corner" | "hidden";

export interface AttractView {
  mode: AttractMode;
  /** the full-screen invitation is up (kept for readers of the old shape) */
  show: boolean;
  code: string;
  joinUrl: string;
}

/** `host` is an origin (location.origin); /submit is a real server route.
 * `publicUrl` is the server's PUBLIC_URL — it wins when set, because the
 * projector is usually opened on localhost or the LAN while students arrive
 * through a gateway, and its own origin would send them to the wrong place. */
export function attractView(connected: boolean, droneCount: number,
                            code: string | null, host: string,
                            publicUrl = ""): AttractView {
  // deliberately keyed on the drone count rather than on hello, because a
  // fresh socket usually delivers a world frame before hello arrives
  let mode: AttractMode = "hidden";
  if (connected && code) mode = droneCount === 0 ? "full" : "corner";
  return {
    mode,
    show: mode === "full",
    code: code ?? "",
    joinUrl: `${(publicUrl.trim() || host).replace(/\/+$/, "")}/submit`,
  };
}
