/** What the projector shows before the class arrives.
 *
 * An empty arena tells a room of students nothing. While nobody is flying,
 * put the room code and the address on the wall so joining is self-serve as
 * they trickle in — and get out of the way the moment the first drone
 * appears. Pure so the rule is testable; main.ts owns the DOM. */

export interface AttractView {
  show: boolean;
  code: string;
  joinUrl: string;
}

/** `host` is an origin (location.origin); /submit is a real server route. */
export function attractView(connected: boolean, droneCount: number,
                            code: string | null, host: string): AttractView {
  return {
    // deliberately keyed on the drone count rather than on hello, because a
    // fresh socket usually delivers a world frame before hello arrives
    show: connected && droneCount === 0 && Boolean(code),
    code: code ?? "",
    joinUrl: `${host.replace(/\/+$/, "")}/submit`,
  };
}
