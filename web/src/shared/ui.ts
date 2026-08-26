/** Small DOM helpers shared by the submit and admin pages: the banner, the
 * in-flight button guard, the two-step destructive confirm, the run pill.
 * (The viewer builds its own HUD and doesn't use these.) */

import { ApiFailure } from "./http";
import type { RunState } from "./protocol";
import type { RunClass } from "./runstate";
import { pillLabel, runClass } from "./runstate";

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

/** A freshly created button wired through guarded() — for table rows. Pass
 * armedLabel to make it a two-step press (see armedConfirm below); rows that
 * destroy a student's work should. */
export function actionButton(label: string, action: () => Promise<unknown>,
                             failMsg: string, onSuccess?: () => void,
                             armedLabel?: string): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  const fire = (): void => void guarded(b, action, failMsg, onSuccess);
  if (armedLabel === undefined) b.addEventListener("click", fire);
  else armedConfirm(b, armedLabel, fire);
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

/** A destructive press that a stray click cannot reach: the button is
 * replaced by "type <word>", and only that word fires it. For the actions
 * whose blast radius is the whole class, where armedConfirm's two clicks are
 * two clicks in the same place. */
export function typedConfirm(btn: HTMLButtonElement, word: string,
                             fire: () => void): void {
  const box = document.createElement("span");
  box.className = "typed-confirm hidden";
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = `type ${word}`;
  input.setAttribute("aria-label", `type ${word} to confirm`);
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.textContent = "cancel";
  box.append(input, cancel);
  btn.after(box);

  const close = (): void => {
    box.classList.add("hidden");
    btn.classList.remove("hidden");
    input.value = "";
  };
  cancel.addEventListener("click", close);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { close(); return; }
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    if (input.value.trim().toLowerCase() !== word.toLowerCase()) {
      input.select();
      return;
    }
    close();
    fire();
  });
  btn.addEventListener("click", () => {
    btn.classList.add("hidden");
    box.classList.remove("hidden");
    input.focus();
  });
}

/** Render a run state into a .pill element (pill classes live in theme.css).
 * With an age, the pill also says how long it has been that way. */
export function runPill(el: HTMLElement, rs: RunState | null, age?: number): void {
  const cls = runClass(rs);
  el.textContent = age === undefined
    ? plainLabel(rs, cls)
    : pillLabel(rs, age);
  el.className = cls === "idle" ? "pill" : `pill ${cls}`;
}

function plainLabel(rs: RunState | null, cls: RunClass): string {
  if (cls === "idle") return "idle";
  if (cls === "done" || cls === "failed") {
    return rs?.exit_code ? `exited (${rs.exit_code})` : "exited";
  }
  return cls;
}
