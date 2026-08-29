/** Instructor console: token gate → 3 s roster polling → kill/kick/ban/reset/
 * bots, plus the process itself (switch mission, restart) and the keep-out
 * list. Pure REST over the admin endpoints — which answer only on the
 * server's ADMIN_PORT (reach it over ssh -L); no WebSocket, no state beyond
 * the sessionStorage token. */

import type { AdminInfo, BanList, BotsResult, RestartResult, RosterStudent } from "../shared/protocol";
import { $, actionButton, armedConfirm, banner, guarded, runPill, typedConfirm } from "../shared/ui";
import { ApiFailure, addBan, banStudent, clearBans, clearOverride, clearToken, fetchBans,
  fetchHealth, fetchInfo, fetchRoster, getToken, kickStudent, killScript, removeBan,
  resetWorld, restartServer, setToken, spawnBots, tokenProblem, unlock } from "./api";
import { formatHealth, type HealthSample } from "./health";
import { ageMs, attention, orderRoster, updateAges } from "./glance";
import { banRows, describeRoom, looksLikeAddress, restartNotice } from "./info";

const POLL_MS = 3000;

let pollTimer = 0;
let lastHealth: HealthSample | null = null;
/** When each student entered their current run state. The server sends no
 * timestamps, so this is the only way to tell a long run from a stuck one. */
let ages = new Map<string, number>();
/** A restart was accepted: hold its banner through the outage, and say "back"
 * on the first poll that answers after the server went away. */
let restart: { result: RestartResult; switching: boolean; wentAway: boolean } | null = null;

// ------------------------------------------------------------------ token gate

function showGate(error = ""): void {
  window.clearTimeout(pollTimer);
  $("join-overlay").classList.remove("hidden");
  $("join-error").textContent = error;
  ($("token-input") as HTMLInputElement).focus();
}

async function handleToken(ev: Event): Promise<void> {
  ev.preventDefault();
  const raw = ($("token-input") as HTMLInputElement).value.trim();
  const problem = tokenProblem(raw);
  if (problem !== null) {
    showGate(problem);
    return;
  }
  setToken(raw);
  try {
    await poll();
    $("join-overlay").classList.add("hidden");
    void loadInfo();
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
    const [roster, health, bans] = await Promise.all([
      fetchRoster(), fetchHealth().catch(() => null), fetchBans().catch(() => null)]);
    $("summary").textContent =
      `mission ${roster.mission} — score ${roster.score} — ${roster.students.length} in the sky`;
    const now = Date.now();
    const line = $("health-line");
    line.textContent = health === null ? "" : formatHealth(health, lastHealth, now);
    line.classList.toggle("danger", health !== null && !health.ok);
    lastHealth = health === null ? null : { ticks: health.ticks, at: now };
    renderRoster(roster.students);
    if (bans !== null) renderBans(bans);
    if (restart === null) {
      banner("");
    } else if (restart.wentAway) {
      // the process that left is back: the room line is a different process now
      banner(`back — mission ${roster.mission}`, { info: true });
      restart = null;
      void loadInfo();
    } // else: the old process still answering; keep the restart banner up
  } catch (e) {
    if (e instanceof ApiFailure && e.status === 403) {
      clearToken(); // stops the finally clause from re-arming the poll
      showGate("bad admin token — enter it again");
      throw e;
    }
    // say why: "Failed to fetch" with a 200 in curl is a browser extension
    // (ad/privacy blockers match "/admin" paths), not the server
    const why = e instanceof Error ? e.message : String(e);
    if (restart !== null) {
      restart.wentAway = true;
      $("summary").textContent = "restarting — waiting for the server…";
    } else {
      $("summary").textContent = `server unreachable — retrying… (${why})`;
    }
    $("health-line").textContent = "";
    lastHealth = null; // a gap in the samples would fake a tick rate
  } finally {
    if (getToken()) pollTimer = window.setTimeout(() => void poll(), POLL_MS);
  }
}

/** Once per process: the room line and the dropdowns. Re-fetched after a
 * restart, when the mission and the override may both have changed. */
async function loadInfo(): Promise<void> {
  let info: AdminInfo;
  try {
    info = await fetchInfo();
  } catch {
    return; // poll() reports outages and bad tokens; this is furniture
  }
  $("room-line").textContent = describeRoom(info);
  fillSelect($("mission-select") as HTMLSelectElement, info.missions, info.mission);
  fillSelect($("bots-script") as HTMLSelectElement, info.bot_scripts, "bot_patrol");
  $("clear-override-btn").classList.toggle("hidden", info.mission_override === null);
}

function fillSelect(sel: HTMLSelectElement, options: string[], chosen: string): void {
  const keep = sel.value;
  sel.textContent = "";
  for (const name of options) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  }
  sel.value = options.includes(keep) ? keep : chosen;
}

function renderRoster(roster: RosterStudent[]): void {
  const now = Date.now();
  ages = updateAges(ages, roster, now);
  const body = $("roster-body");
  // "really kill?" is armed on the button element, and this rebuilds every row
  // from scratch — redrawing now would disarm it under the instructor's second
  // click, which at a 3 s poll is most of the time. It disarms itself after
  // 3 s; the next poll redraws then. Ages keep advancing meanwhile.
  if (body.querySelector("button.confirm") !== null) return;
  const students = orderRoster(roster, ages, now);
  body.textContent = "";
  if (students.length === 0) {
    emptyRow(body, 5, "no students yet");
    return;
  }
  for (const s of students) {
    const tr = document.createElement("tr");
    const age = ageMs(ages, s, now);
    const attn = attention(s, age);
    if (attn !== "none") tr.className = `attn-${attn}`;

    const name = tr.insertCell();
    name.textContent = s.name;

    const id = tr.insertCell();
    id.className = "id";
    id.textContent = s.student_id;

    const run = tr.insertCell();
    const pill = document.createElement("span");
    runPill(pill, s.run, age);
    run.appendChild(pill);

    const link = tr.insertCell();
    const dot = document.createElement("span");
    dot.className = "link-dot" + (s.connected ? " up" : "");
    dot.textContent = s.crashed ? "crashed" : s.connected ? "up" : "down";
    link.appendChild(dot);

    const actions = tr.insertCell();
    actions.className = "actions";
    // both throw away work the student can't get back, and the rows reorder
    // under the cursor as states change — one click must not be enough
    actions.append(
      actionButton("kill script", () => killScript(s.student_id),
        `could not stop ${s.name}'s script`, () => void poll(), "really kill?"),
      actionButton("kick", () => kickStudent(s.student_id),
        `could not kick ${s.name}`, () => void poll(), "really kick?"),
      banButton(s),
    );

    body.appendChild(tr);
  }
}

function emptyRow(body: HTMLElement, span: number, text: string): void {
  const td = document.createElement("td");
  td.colSpan = span;
  td.className = "empty";
  td.textContent = text;
  body.appendChild(document.createElement("tr")).appendChild(td);
}

function banButton(s: RosterStudent): HTMLButtonElement {
  const b = actionButton("ban", () => banStudent(s.student_id),
    `could not ban ${s.name}`, () => void poll(), "really ban?");
  b.title = "kick, and keep this name and the address it joined from out until " +
    "unbanned below — on a shared wifi that address is everyone behind it";
  b.classList.add("danger");
  return b;
}

// ------------------------------------------------------------------- kept out

function renderBans(bans: BanList): void {
  const body = $("bans-body");
  const rows = banRows(bans);
  body.textContent = "";
  if (rows.length === 0) {
    emptyRow(body, 3, "nobody");
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    const kind = tr.insertCell();
    kind.className = "kind";
    kind.textContent = row.kind === "lockout" ? "locked out" : row.kind === "ip" ? "address" : "name";
    tr.insertCell().textContent = row.label;
    const actions = tr.insertCell();
    actions.className = "actions";
    // lifting a ban is reversible in one click the other way: no arming
    actions.appendChild(row.kind === "lockout"
      ? actionButton("unlock", () => unlock(row.key), `could not unlock ${row.key}`, () => void poll())
      : actionButton("unban", () => removeBan(row.kind === "ip" ? { ip: row.key } : { name: row.key }),
        `could not unban ${row.key}`, () => void poll()));
    body.appendChild(tr);
  }
}

function banTyped(kind: "name" | "ip"): void {
  const input = $("ban-input") as HTMLInputElement;
  const value = input.value.trim();
  const btn = $(kind === "ip" ? "ban-ip-btn" : "ban-name-btn") as HTMLButtonElement;
  if (!value) {
    banner(`type the ${kind === "ip" ? "address" : "name"} to ban first`);
    return;
  }
  if (kind === "ip" && !looksLikeAddress(value)) {
    banner(`"${value}" does not look like an address — use "ban name" for a pilot`);
    return;
  }
  let kicked: string[] = [];
  void guarded(btn, async () => {
    kicked = (await addBan(kind === "ip" ? { ip: value } : { name: value })).kicked;
    input.value = "";
    await poll();
  }, `could not ban ${value}`, () => {
    if (kicked.length) banner(`banned ${value} — kicked ${kicked.join(", ")}`, { info: true });
  });
}

$("ban-name-btn").addEventListener("click", () => banTyped("name"));
$("ban-ip-btn").addEventListener("click", () => banTyped("ip"));
$("ban-form").addEventListener("submit", (ev) => {
  ev.preventDefault(); // Enter in the box: a name unless it reads as an address
  banTyped(looksLikeAddress(($("ban-input") as HTMLInputElement).value.trim()) ? "ip" : "name");
});
const unbanAllBtn = $("unban-all-btn") as HTMLButtonElement;
unbanAllBtn.addEventListener("click", () =>
  void guarded(unbanAllBtn, clearBans, "could not clear the bans", () => void poll()));
const unlockAllBtn = $("unlock-all-btn") as HTMLButtonElement;
unlockAllBtn.addEventListener("click", () =>
  void guarded(unlockAllBtn, () => unlock(), "could not unlock", () => void poll()));

// -------------------------------------------------------------------- controls

// reset throws away the whole class's world at once — the one action worth
// making someone type, since two clicks land in the same place as one
const resetBtn = $("reset-world-btn") as HTMLButtonElement;
typedConfirm(resetBtn, "reset", () =>
  void guarded(resetBtn, resetWorld, "reset failed", () => void poll()));

// the process: same blast radius as reset, plus a few seconds of nobody home
function requestRestart(btn: HTMLButtonElement, mission: string | null): void {
  const keepScore = ($("keep-score") as HTMLInputElement).checked;
  let result: RestartResult | null = null;
  void guarded(btn, async () => {
    result = await restartServer(mission, keepScore);
  }, "restart refused", () => {
    if (result === null) return;
    restart = { result, switching: mission !== null, wentAway: false };
    banner(restartNotice(result, mission !== null), { info: true });
  });
}
// two presses, not a typed word: the instructor does this at every block
// boundary with the class waiting, and the drop-down already names the target
const switchBtn = $("switch-btn") as HTMLButtonElement;
armedConfirm(switchBtn, "really switch?", () =>
  requestRestart(switchBtn, ($("mission-select") as HTMLSelectElement).value));
const restartBtn = $("restart-btn") as HTMLButtonElement;
armedConfirm(restartBtn, "really restart?", () => requestRestart(restartBtn, null));
$("mission-form").addEventListener("submit", (ev) => ev.preventDefault());
const clearOverrideBtn = $("clear-override-btn") as HTMLButtonElement;
clearOverrideBtn.addEventListener("click", () => {
  let env = "";
  void guarded(clearOverrideBtn, async () => {
    env = (await clearOverride()).mission_env;
    await loadInfo();
  }, "could not clear the override", () =>
    banner(`override cleared — the next boot runs MISSION=${env}`, { info: true }));
});

$("bots-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const btn = $("bots-form").querySelector("button")!;
  const count = Number(($("bots-count") as HTMLInputElement).value) || 1;
  const script = ($("bots-script") as HTMLSelectElement).value || "bot_patrol";
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

const storedProblem = getToken() ? tokenProblem(getToken()) : "";
if (storedProblem) {
  clearToken(); // a stored paste that fetch() would reject: back to the gate, not a retry loop
  showGate(storedProblem);
} else if (getToken()) {
  poll().then(loadInfo).catch(() => { /* gate shown by poll on 403; transient errors retry */ });
} else {
  showGate();
}
