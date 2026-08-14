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
  if (editor.isEmpty) editor.setCode(await fetchTemplate());
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

function banner(text: string): void {
  const el = $("banner");
  el.textContent = text;
  el.classList.toggle("show", text.length > 0);
}

function setPill(state: string, extra: string): void {
  const pill = $("run-pill");
  pill.textContent = state + extra;
  pill.className = "pill" + (state === "running" || state === "starting" ? " running"
    : state === "exited" ? " exited" : "");
}

function setRunState(rs: RunState): void {
  if (rs.state === "exited") {
    setPill("exited", rs.exit_code === null ? "" : ` (code ${rs.exit_code})`);
  } else {
    setPill(rs.state, "");
  }
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

function updateStrip(me: DroneState): void {
  $("d-mode").textContent = me.mode;
  $("d-armed").textContent = me.crashed ? "CRASHED" : me.armed ? "yes" : "no";
  $("d-n").textContent = me.n.toFixed(1);
  $("d-e").textContent = me.e.toFixed(1);
  $("d-alt").textContent = `${me.alt.toFixed(1)} m`;
  $("d-carrying").innerHTML = me.carrying ? "📦 <b>carrying a crate!</b>" : "";
}

// ----------------------------------------------------------------------- boot

$("join-form").addEventListener("submit", handleJoin);
$("run-btn").addEventListener("click", () => void run());
$("stop-btn").addEventListener("click", () => void stopRun().catch(() => {}));
$("reset-btn").addEventListener("click", () => void resetMine().catch(() => {}));

const saved = localStorage.getItem(STUDENT_KEY);
if (localStorage.getItem(TOKEN_KEY) && saved) {
  const info = JSON.parse(saved) as { student_id: string; name: string };
  void enter(info.student_id, info.name);
} else {
  showJoin();
}
