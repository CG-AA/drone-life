/** Submit page: join → edit → run → watch logs and your drone strip. */

import type { DroneState, LogLine, RunState, WorldData } from "../shared/protocol";
import { GameSocket } from "../shared/ws";
import { ApiFailure, STUDENT_KEY, TOKEN_KEY, fetchTemplate, join, resetMine,
  stopRun, submitCode } from "./api";
import { Editor } from "./editor";

const $ = (id: string) => document.getElementById(id)!;

const editor = new Editor($("editor"));
let studentId = "";
let ws: GameSocket | null = null;
let scriptRunning = false;

// ------------------------------------------------------------------ join flow

function showJoin(error = ""): void {
  $("join-overlay").classList.remove("hidden");
  $("join-error").textContent = error;
}

async function handleJoin(ev: Event): Promise<void> {
  ev.preventDefault();
  const name = ($("join-name") as HTMLInputElement).value.trim();
  const code = ($("join-code") as HTMLInputElement).value.trim();
  if (!name || !code) return;
  try {
    const info = await join(code, name);
    $("join-overlay").classList.add("hidden");
    await enter(info.student_id, info.name);
  } catch (e) {
    showJoin(e instanceof ApiFailure ? e.error.msg : "could not reach the server");
  }
}

async function enter(id: string, name: string): Promise<void> {
  studentId = id;
  $("pilot-name").textContent = name;
  if (editor.isEmpty) {
    try {
      editor.setCode(await fetchTemplate());
    } catch {
      // the join already succeeded — never bounce back to the overlay over one GET
      banner("could not load the starter template — pick one from the templates menu");
    }
  }
  connectWs();
}

// ------------------------------------------------------------------ websocket

function connectWs(): void {
  ws?.close();
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  ws = new GameSocket(`/ws/student?token=${encodeURIComponent(token)}`);
  ws.on<WorldData>("world", (d) => {
    const me = d.drones.find((drone) => drone.student_id === studentId);
    if (me) updateStrip(me);
  });
  ws.on<{ lines: LogLine[] }>("log", (d) => appendLogs(d.lines));
  ws.on<RunState>("run_state", (d) => setRunState(d));
  ws.onRejected = () => {
    localStorage.removeItem(TOKEN_KEY);
    showJoin("session expired — join again");
  };
  ws.onSkew = () => banner("this page is out of date — refresh to reconnect");
  ws.connect();
}

// ------------------------------------------------------------------- controls

async function run(): Promise<void> {
  banner("");
  const btn = $("run-btn") as HTMLButtonElement;
  btn.disabled = true;
  try {
    await submitCode(editor.code);
    setPill("starting", "");
    $("run-hint").textContent = "watch the sky view — and the log pane on the right";
  } catch (e) {
    if (e instanceof ApiFailure && e.error.code === "syntax") {
      banner(`line ${e.error.line}: ${e.error.msg}`);
      if (e.error.line) editor.gotoLine(e.error.line);
    } else {
      banner(e instanceof ApiFailure ? e.error.msg : "server unreachable");
    }
  } finally {
    btn.disabled = false;
  }
}

/** Disable a button while its request is in flight; surface failures. */
async function guarded(btn: HTMLButtonElement, action: () => Promise<unknown>,
                       failMsg: string): Promise<void> {
  btn.disabled = true;
  try {
    await action();
    banner("");
  } catch (e) {
    banner(e instanceof ApiFailure ? `${failMsg}: ${e.error.msg}` : failMsg);
  } finally {
    btn.disabled = false;
  }
}

interface BannerOpts {
  info?: boolean;
  actions?: Array<[label: string, onClick: () => void]>;
}

function banner(text: string, opts: BannerOpts = {}): void {
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

function setPill(state: string, extra: string): void {
  const pill = $("run-pill");
  pill.textContent = state + extra;
  pill.className = "pill" + (state === "running" || state === "starting" ? " running"
    : state === "exited" ? " exited" : "");
}

function setRunState(rs: RunState): void {
  scriptRunning = rs.state === "starting" || rs.state === "running";
  if (rs.state === "exited") {
    setPill("exited", rs.exit_code === null ? "" : ` (code ${rs.exit_code})`);
  } else {
    setPill(rs.state, "");
  }
}

// reset kills a running script, so make a running reset a two-step press
const resetBtn = $("reset-btn") as HTMLButtonElement;
let resetArmTimer = 0;

function disarmReset(): void {
  window.clearTimeout(resetArmTimer);
  resetArmTimer = 0;
  resetBtn.textContent = "reset drone";
  resetBtn.classList.remove("confirm");
}

function onResetClick(): void {
  if (scriptRunning && resetArmTimer === 0) {
    resetBtn.textContent = "really reset?";
    resetBtn.classList.add("confirm");
    resetArmTimer = window.setTimeout(disarmReset, 3000);
    return;
  }
  disarmReset();
  void guarded(resetBtn, resetMine, "could not reset your drone");
}

// ----------------------------------------------------------------- templates

const templateSel = $("template-select") as HTMLSelectElement;

function onTemplatePick(): void {
  const variant = templateSel.value;
  templateSel.selectedIndex = 0; // snap back to the placeholder
  if (!variant) return;
  const apply = (): void => {
    void fetchTemplate(variant)
      .then((code) => { editor.setCode(code); banner(""); })
      .catch(() => banner(`could not load the ${variant} template`));
  };
  if (editor.isEmpty) {
    apply();
    return;
  }
  banner(`load the ${variant} template? this replaces your current code`, {
    info: true,
    actions: [["replace", apply], ["keep mine", () => banner("")]],
  });
}

// ---------------------------------------------------------------------- panes

const logPane = $("log-pane");

function appendLogs(lines: LogLine[]): void {
  const stickToBottom =
    logPane.scrollTop + logPane.clientHeight > logPane.scrollHeight - 40;
  for (const line of lines) {
    const div = document.createElement("div");
    div.className = line.stream;
    div.textContent = line.line;
    logPane.appendChild(div);
  }
  while (logPane.childElementCount > 2000) logPane.firstElementChild?.remove();
  if (stickToBottom) logPane.scrollTop = logPane.scrollHeight;
}

const linkEl = $("d-link");
const carryingEl = $("d-carrying");
let lastCarrying = false;

function updateStrip(me: DroneState): void {
  $("d-mode").textContent = me.mode;
  $("d-armed").textContent = me.crashed ? "CRASHED" : me.armed ? "yes" : "no";
  linkEl.classList.toggle("down", !me.connected);
  linkEl.querySelector("b")!.textContent = me.connected ? "up" : "down";
  $("d-n").textContent = me.n.toFixed(1);
  $("d-e").textContent = me.e.toFixed(1);
  $("d-alt").textContent = `${me.alt.toFixed(1)} m`;
  const nowCarrying = Boolean(me.carrying);
  if (nowCarrying !== lastCarrying) {
    lastCarrying = nowCarrying;
    carryingEl.textContent = "";
    if (nowCarrying) {
      carryingEl.append("📦 ");
      const b = document.createElement("b");
      b.textContent = "carrying a crate!";
      carryingEl.append(b);
    }
  }
}

// ----------------------------------------------------------------------- boot

$("join-form").addEventListener("submit", handleJoin);
$("run-btn").addEventListener("click", () => void run());
$("stop-btn").addEventListener("click", () => void guarded(
  $("stop-btn") as HTMLButtonElement, stopRun, "could not stop the script"));
resetBtn.addEventListener("click", onResetClick);
templateSel.addEventListener("change", onTemplatePick);

interface SavedStudent { student_id: string; name: string }
let saved: SavedStudent | null = null;
try {
  saved = JSON.parse(localStorage.getItem(STUDENT_KEY) ?? "null") as SavedStudent | null;
} catch {
  // corrupt storage must not blank the page — fall through to the join overlay
}
if (localStorage.getItem(TOKEN_KEY) && saved?.student_id) {
  enter(saved.student_id, saved.name)
    .catch(() => showJoin("could not restore your session — join again"));
} else {
  showJoin();
}
