/** Instructor console: token gate → 3 s roster polling → kill/kick/reset/bots.
 * Pure REST over the existing admin endpoints; no WebSocket, no state beyond
 * the sessionStorage token. */

import type { BotsResult, RosterStudent } from "../shared/protocol";
import { $, actionButton, armedConfirm, banner, guarded, runPill } from "../shared/ui";
import { ApiFailure, clearToken, fetchHealth, fetchRoster, getToken, kickStudent, killScript,
  resetWorld, setToken, spawnBots } from "./api";
import { formatHealth, type HealthSample } from "./health";

const POLL_MS = 3000;

let pollTimer = 0;
let lastHealth: HealthSample | null = null;

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
    // the roster is what unsticks a student — never lose it over the health line
    const [roster, health] = await Promise.all([fetchRoster(), fetchHealth().catch(() => null)]);
    $("summary").textContent =
      `mission ${roster.mission} — score ${roster.score} — ${roster.students.length} in the sky`;
    const now = Date.now();
    const line = $("health-line");
    line.textContent = health === null ? "" : formatHealth(health, lastHealth, now);
    line.classList.toggle("danger", health !== null && !health.ok);
    lastHealth = health === null ? null : { ticks: health.ticks, at: now };
    renderRoster(roster.students);
    banner("");
  } catch (e) {
    if (e instanceof ApiFailure && e.status === 403) {
      clearToken(); // stops the finally clause from re-arming the poll
      showGate("bad admin token — enter it again");
      throw e;
    }
    $("summary").textContent = "server unreachable — retrying…";
    $("health-line").textContent = "";
    lastHealth = null; // a gap in the samples would fake a tick rate
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
    runPill(pill, s.run);
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
        `could not stop ${s.name}'s script`, () => void poll()),
      actionButton("kick", () => kickStudent(s.student_id),
        `could not kick ${s.name}`, () => void poll()),
    );

    body.appendChild(tr);
  }
}

// -------------------------------------------------------------------- controls

// reset wipes the whole class's world, so make it a two-step press
const resetBtn = $("reset-world-btn") as HTMLButtonElement;
armedConfirm(resetBtn, "really reset everyone?", () =>
  void guarded(resetBtn, resetWorld, "reset failed", () => void poll()));

$("bots-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const btn = $("bots-form").querySelector("button")!;
  const count = Number(($("bots-count") as HTMLInputElement).value) || 1;
  const script = ($("bots-script") as HTMLInputElement).value.trim() || "bot_patrol";
  const mode = ($("bots-mode") as HTMLSelectElement).value;
  let r: BotsResult | null = null;
  void guarded(btn, async () => {
    r = await spawnBots(count, mode, script);
    await poll();
  }, "could not spawn bots", () => {
    // onSuccess runs after guarded clears the banner, so this one sticks
    if (r?.room_full) banner(`room filled up — started ${r.started.length} bot(s)`);
  });
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
