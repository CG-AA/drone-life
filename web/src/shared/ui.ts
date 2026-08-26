/** Small DOM helpers shared by the submit and admin pages: the banner, the
 * in-flight button guard, the two-step destructive confirm, the run pill.
 * (The viewer builds its own HUD and doesn't use these.) */

import { ApiFailure } from "./http";
import type { RunState } from "./protocol";

/** getElementById that throws on a missing id — a typo fails loudly at boot. */
export function $(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element #${id}`);
  return el;
}

export interface BannerOpts {
  info?: boolean;
  actions?: Array<[label: string, onClick: () => void]>;
}

/** Fill the page's #banner element; empty text hides it. */
export function banner(text: string, opts: BannerOpts = {}): void {
  const el = $("banner");
  el.textContent = text;
  el.classList.toggle("info", Boolean(opts.info));
  for (const [label, onClick] of opts.actions ?? []) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", onClick);
    el.appendChild(b);
  }
  el.classList.toggle("show", text.length > 0);
}

/** Run an async action behind a button: disabled while in flight (re-entry is
 * a no-op), failures land in the banner, success clears it. */
export async function guarded(btn: HTMLButtonElement, action: () => Promise<unknown>,
                              failMsg: string, onSuccess?: () => void): Promise<void> {
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    await action();
    banner("");
    onSuccess?.();
  } catch (e) {
    banner(e instanceof ApiFailure ? `${failMsg}: ${e.error.msg}` : failMsg);
  } finally {
    btn.disabled = false;
  }
}

/** A freshly created button wired through guarded() — for table rows. */
export function actionButton(label: string, action: () => Promise<unknown>,
                             failMsg: string, onSuccess?: () => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.addEventListener("click", () => void guarded(b, action, failMsg, onSuccess));
  return b;
}

/** Two-step destructive press: while armWhen() holds, the first click arms the
 * button ("really …?") and a second click within 3 s fires; otherwise it fires
 * immediately. */
export function armedConfirm(btn: HTMLButtonElement, armedLabel: string,
                             fire: () => void,
                             armWhen: () => boolean = () => true): void {
  const restLabel = btn.textContent ?? "";
  let timer = 0;
  const disarm = (): void => {
    window.clearTimeout(timer);
    timer = 0;
    btn.textContent = restLabel;
    btn.classList.remove("confirm");
  };
  btn.addEventListener("click", () => {
    if (armWhen() && timer === 0) {
      btn.textContent = armedLabel;
      btn.classList.add("confirm");
      timer = window.setTimeout(disarm, 3000);
      return;
    }
    disarm();
    fire();
  });
}

/** Pinned to manager.py's END_REASONS by ui.test.ts — "error" is absent on
 * purpose: it renders its exit code, which is the student's debugging handle. */
export const END_LABEL: Record<string, string> = {
  done: "finished",
  timeout: "timed out",
  stopped: "stopped",
  replaced: "replaced",
  start_failed: "failed to start",
  runner_failed: "sandbox error",
};

/** Pill text for a run. An exit code alone doesn't say what happened, so prefer
 * the server's reason; "error" and an older server fall back to the code. */
export function runLabel(rs: RunState | null): string {
  if (rs === null) return "idle";
  if (rs.state !== "exited") return rs.state;
  const label = rs.reason ? END_LABEL[rs.reason] : undefined;
  if (label) return label;
  return rs.exit_code === null ? "exited" : `exited (${rs.exit_code})`;
}

/** Render a run state into a .pill element (pill classes live in theme.css). */
export function runPill(el: HTMLElement, rs: RunState | null): void {
  el.textContent = runLabel(rs);
  if (rs === null) el.className = "pill";
  else el.className = rs.state === "exited" ? "pill exited" : "pill running";
}
