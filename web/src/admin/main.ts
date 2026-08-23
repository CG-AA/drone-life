/** Instructor console: token gate → 3 s roster polling → kill/kick/reset/bots.
 * Pure REST over the existing admin endpoints; no WebSocket, no state beyond
 * the sessionStorage token. */

import { ApiFailure, clearToken, fetchRoster, getToken, kickStudent, killScript,
  resetWorld, setToken, spawnBots } from "./api";
import type { RosterStudent } from "./api";

const POLL_MS = 3000;

const $ = (id: string) => document.getElementById(id)!;

let pollTimer = 0;

// ------------------------------------------------------------------ token gate

function showGate(error = ""): void {
  window.clearTimeout(pollTimer);
  $("join-overlay").classList.remove("hidden");
  $("join-error").textContent = error;
  ($("token-input") as HTMLInputElement).focus();
}

async function handleToken(ev: Event): Promise<void> {
  ev.preventDefault();
  setToken(($("token-input") as HTMLInputElement).value.trim());
  try {
    await poll();
    $("join-overlay").classList.add("hidden");
  } catch (e) {
    if (!(e instanceof ApiFailure && e.status === 403)) {
      clearToken();
      showGate("could not reach the server");
    } // 403: poll() already cleared the token and re-showed the gate
  }
}

// --------------------------------------------------------------------- polling

async function poll(): Promise<void> {
  window.clearTimeout(pollTimer);
  try {
    const roster = await fetchRoster();
    $("summary").textContent =
      `mission ${roster.mission} — score ${roster.score} — ${roster.students.length} in the sky`;
    renderRoster(roster.students);
    banner("");
  } catch (e) {
    if (e instanceof ApiFailure && e.status === 403) {
      clearToken(); // stops the finally clause from re-arming the poll
      showGate("bad admin token — enter it again");
      throw e;
    }
    $("summary").textContent = "server unreachable — retrying…";
  } finally {
    if (getToken()) pollTimer = window.setTimeout(() => void poll(), POLL_MS);
  }
}

function renderRoster(students: RosterStudent[]): void {
  const body = $("roster-body");
  body.textContent = "";
  if (students.length === 0) {
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty";
    td.textContent = "no students yet";
    body.appendChild(document.createElement("tr")).appendChild(td);
    return;
  }
  for (const s of students) {
    const tr = document.createElement("tr");

    const name = tr.insertCell();
    name.textContent = s.name;

    const id = tr.insertCell();
    id.className = "id";
    id.textContent = s.student_id;

    const run = tr.insertCell();
    const pill = document.createElement("span");
    pill.className = "pill";
    if (s.run?.state === "running" || s.run?.state === "starting") {
      pill.classList.add("running");
      pill.textContent = s.run.state;
    } else if (s.run?.state === "exited") {
      pill.classList.add("exited");
      pill.textContent = s.run.exit_code === null
        ? "exited" : `exited (${s.run.exit_code})`;
    } else {
      pill.textContent = "idle";
    }
    run.appendChild(pill);

    const link = tr.insertCell();
    const dot = document.createElement("span");
    dot.className = "link-dot" + (s.connected ? " up" : "");
    dot.textContent = s.crashed ? "crashed" : s.connected ? "up" : "down";
    link.appendChild(dot);

    const actions = tr.insertCell();
    actions.className = "actions";
    actions.append(
      actionButton("kill script", () => killScript(s.student_id),
        `could not stop ${s.name}'s script`),
      actionButton("kick", () => kickStudent(s.student_id),
        `could not kick ${s.name}`),
    );

    body.appendChild(tr);
  }
}

function actionButton(label: string, action: () => Promise<unknown>,
                      failMsg: string): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.addEventListener("click", () => {
    b.disabled = true;
    action()
      .then(() => poll())
      .catch((e: unknown) => banner(
        e instanceof ApiFailure ? `${failMsg}: ${e.error.msg}` : failMsg))
      .finally(() => { b.disabled = false; });
  });
  return b;
}

function banner(text: string): void {
  const el = $("banner");
  el.textContent = text;
  el.classList.toggle("show", text.length > 0);
}

// -------------------------------------------------------------------- controls

// reset wipes the whole class's world, so make it a two-step press
const resetBtn = $("reset-world-btn") as HTMLButtonElement;
let resetArmTimer = 0;

function disarmReset(): void {
  window.clearTimeout(resetArmTimer);
  resetArmTimer = 0;
  resetBtn.textContent = "reset world";
  resetBtn.classList.remove("confirm");
}

resetBtn.addEventListener("click", () => {
  if (resetArmTimer === 0) {
    resetBtn.textContent = "really reset everyone?";
    resetBtn.classList.add("confirm");
    resetArmTimer = window.setTimeout(disarmReset, 3000);
    return;
  }
  disarmReset();
  resetBtn.disabled = true;
  resetWorld()
    .then(() => poll())
    .catch((e: unknown) => banner(
      e instanceof ApiFailure ? `reset failed: ${e.error.msg}` : "reset failed"))
    .finally(() => { resetBtn.disabled = false; });
});

$("bots-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const btn = $("bots-form").querySelector("button")!;
  btn.disabled = true;
  const count = Number(($("bots-count") as HTMLInputElement).value) || 1;
  const script = ($("bots-script") as HTMLInputElement).value.trim() || "bot_patrol";
  const mode = ($("bots-mode") as HTMLSelectElement).value;
  spawnBots(count, mode, script)
    .then((r) => {
      if (r.room_full) banner(`room filled up — started ${r.started} bot(s)`);
      return poll();
    })
    .catch((e: unknown) => banner(
      e instanceof ApiFailure ? `could not spawn bots: ${e.error.msg}` : "could not spawn bots"))
    .finally(() => { btn.disabled = false; });
});

$("signout-btn").addEventListener("click", () => {
  clearToken();
  showGate();
});

// ----------------------------------------------------------------------- boot

$("token-form").addEventListener("submit", (ev) => void handleToken(ev));

if (getToken()) {
  poll().catch(() => { /* gate shown by poll on 403; transient errors retry */ });
} else {
  showGate();
}
