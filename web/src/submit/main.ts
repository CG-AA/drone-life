/** Submit page: join → edit → run → watch logs and your drone strip. */

import { prefix } from "../shared/prefix";
import type { DroneState, HelloData, LogLine, RoomRow, RunState, WorldData }
  from "../shared/protocol";
import { $, armedConfirm, banner, guarded, runPill } from "../shared/ui";
import { GameSocket } from "../shared/ws";
import { ApiFailure, CODE_KEY, STUDENT_KEY, TOKEN_KEY, fetchRoomHealth, fetchRooms,
  fetchStatus, fetchTemplate, join, resetMine, stopRun, submitCode } from "./api";
import { currentRoom, describeRoom, roomName, worthListing } from "./rooms";
import { Editor } from "./editor";
import type { ErrorView } from "./errors";
import { codeTooBig, describeError, tooBigText } from "./errors";
import type { LogCursor } from "./logmerge";
import { freshLines } from "./logmerge";
import { upgradesText, walletText } from "./wallet";

const editor = new Editor($("editor"));
let studentId = "";
let ws: GameSocket | null = null;
let scriptRunning = false;

interface SavedStudent { student_id: string; name: string }
let saved: SavedStudent | null = null;
try {
  saved = JSON.parse(localStorage.getItem(STUDENT_KEY) ?? "null") as SavedStudent | null;
} catch {
  // corrupt storage must not blank the page — fall through to the join overlay
}

// ------------------------------------------------------------------ join flow

function showJoin(error = ""): void {
  $("join-overlay").classList.remove("hidden");
  $("join-error").textContent = error;
  const nameEl = $("join-name") as HTMLInputElement;
  const codeEl = $("join-code") as HTMLInputElement;
  // coming back after an expiry should not mean retyping what we know
  if (!nameEl.value) nameEl.value = saved?.name ?? "";
  if (!codeEl.value) codeEl.value = localStorage.getItem(CODE_KEY) ?? "";
  const empty = [nameEl, codeEl].find((el) => !el.value);
  (empty ?? nameEl).focus();
}

// ------------------------------------------------------------------ rooms

const ROOMS_POLL_MS = 3000;

function renderRooms(rooms: RoomRow[], healths: Parameters<typeof describeRoom>[1][]): void {
  const list = $("room-list");
  const views = rooms.map((r, i) => describeRoom(r, healths[i]));
  list.classList.toggle("hidden", !worthListing(views));
  list.replaceChildren(...views.map((v) => {
    const row = document.createElement(v.status === "open" ? "a" : "span");
    row.className = `room ${v.status}`;
    row.setAttribute("role", "listitem");
    if (row instanceof HTMLAnchorElement) row.href = v.href;
    const name = document.createElement("span");
    name.className = "room-name";
    name.textContent = v.label;
    const seats = document.createElement("span");
    seats.className = "room-seats";
    seats.textContent = v.status === "open" && v.mission ? `${v.seats} · ${v.mission}` : v.seats;
    row.append(name, seats);
    return row;
  }));
}

/** The small rooms behind the proxy (docs/ROOMS.md): if this server lists
 * any, the join overlay offers them with live counts — unless this page is
 * already one of them, which gets a one-line "switch room" instead. Polled
 * only while the overlay is up; a server with no ROOMS shows nothing. */
async function offerRooms(): Promise<void> {
  let rooms: RoomRow[];
  try {
    rooms = (await fetchRooms()).rooms;
  } catch {
    return; // an older server, or unreachable: the join form alone is fine
  }
  if (rooms.length === 0) return;
  const here = currentRoom(rooms, prefix());
  if (here) {
    const el = $("room-here");
    el.replaceChildren(`you are in ${roomName(here.id)} · `);
    const link = document.createElement("a");
    link.href = "../submit";
    link.textContent = "switch room";
    el.append(link);
    el.classList.remove("hidden");
    return;
  }
  const tick = async (): Promise<void> => {
    if ($("join-overlay").classList.contains("hidden")) return; // joined: nothing to pick
    renderRooms(rooms, await Promise.all(rooms.map((r) => fetchRoomHealth(r.path))));
  };
  await tick();
  window.setInterval(() => void tick(), ROOMS_POLL_MS);
}

/** Render a mapped failure into the banner, wiring up whatever it offers. */
function showError(view: ErrorView, retry?: () => void): void {
  const actions: Array<[string, () => void]> = [];
  for (const a of view.actions) {
    if (a.kind === "rejoin") {
      actions.push([a.label, () => {
        localStorage.removeItem(TOKEN_KEY);
        banner("");
        showJoin("your session expired — join again");
      }]);
    } else if (a.kind === "retry" && retry) {
      actions.push([a.label, retry]);
    } else if (a.kind === "dismiss") {
      actions.push([a.label, () => banner("")]);
    }
  }
  banner(view.text, { info: view.tone === "info", actions });
}

async function handleJoin(ev: Event): Promise<void> {
  ev.preventDefault();
  const name = ($("join-name") as HTMLInputElement).value.trim();
  const code = ($("join-code") as HTMLInputElement).value.trim();
  if (!name || !code) {
    showJoin("type your name and the room code, then press join");
    return;
  }
  try {
    const info = await join(code, name);
    saved = { student_id: info.student_id, name: info.name };
    $("join-overlay").classList.add("hidden");
    await enter(info.student_id, info.name);
    if (info.rejoined) {
      // the server matches on name, so this is also what a student sees when
      // they take someone else's drone by typing their name
      banner(`welcome back, ${info.name} — you're back on your drone. `
        + "Not you? join again with a different name.", {
        info: true,
        actions: [["not me", () => { banner(""); showJoin(); }]],
      });
    }
  } catch (e) {
    showJoin(describeError(e, "join").text);
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

/** Catch a returning page up before its socket opens: prove the stored token
 * is still good (a refresh otherwise looks fine until the first run), and
 * restore the run pill and log tail that the reload threw away. */
async function restore(): Promise<boolean> {
  try {
    const st = await fetchStatus();
    // the roster can be re-seated under a stored token (rooms merged into the
    // big one, docs/ROOMS.md): the server's id and name win over the cached ones
    const name = st.name ?? saved?.name ?? ""; // ?? : a server from before /status carried it
    if (saved && (st.student_id !== saved.student_id || name !== saved.name)) {
      saved = { student_id: st.student_id, name };
      localStorage.setItem(STUDENT_KEY, JSON.stringify(saved));
    }
    if (st.run) setRunState(st.run);
    else runPill($("run-pill"), null);
    appendLogs(st.log_tail);
    return true;
  } catch (e) {
    if (e instanceof ApiFailure && e.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      showJoin("your session expired — join again");
      return false;
    }
    return true; // offline or a server blip: the socket keeps retrying
  }
}

// ------------------------------------------------------------------ websocket

function connectWs(): void {
  ws?.close();
  const token = localStorage.getItem(TOKEN_KEY) ?? "";
  ws = new GameSocket(`/ws/student?token=${encodeURIComponent(token)}`);
  // the game the room is playing and the number everyone is adding to — the
  // student's page is otherwise the only screen in the room that can't tell
  ws.on<HelloData>("hello", (d) => {
    $("mission-pill").textContent = `mission: ${d.mission}`;
  });
  ws.on<WorldData>("world", (d) => {
    $("score-pill").textContent = `team ${d.score}`;
    const me = d.drones.find((drone) => drone.student_id === studentId);
    if (me) updateStrip(me);
  });
  ws.on<{ lines: LogLine[] }>("log", (d) => appendLogs(d.lines));
  ws.on<RunState>("run_state", (d) => setRunState(d));
  // a dead token is refused before the upgrade is accepted, so the socket
  // reports a failed handshake with no code to read; /status can say which
  ws.verify = async () => {
    try {
      await fetchStatus();
      return false;
    } catch (e) {
      return e instanceof ApiFailure && e.status === 401;
    }
  };
  ws.onRejected = () => {
    localStorage.removeItem(TOKEN_KEY);
    showJoin("your session expired — join again");
  };
  ws.onSkew = () => banner("this page is out of date — refresh to reconnect");
  let wasDown = false;
  ws.onStatus = (up) => {
    if (!up) {
      wasDown = true;
      banner("connection lost — reconnecting…");
    } else if (wasDown) {
      wasDown = false;
      banner("");
    }
  };
  ws.connect();
}

// ------------------------------------------------------------------- controls

async function run(): Promise<void> {
  banner("");
  const code = editor.code;
  // the server would reject it anyway; refusing here saves the round trip
  const oversize = codeTooBig(code);
  if (oversize !== null) {
    banner(tooBigText(oversize));
    return;
  }
  const btn = $("run-btn") as HTMLButtonElement;
  btn.disabled = true;
  try {
    await submitCode(code);
    editor.clearDiagnostics();
    runPill($("run-pill"), { run_id: "", state: "starting", exit_code: null, reason: null });
    $("run-hint").textContent = "watch the sky view — and the log pane on the right";
  } catch (e) {
    const view = describeError(e, "submit");
    showError(view, () => void run());
    if (view.goto) editor.showSyntaxError(view.goto.line, view.goto.col, view.text);
  } finally {
    btn.disabled = false;
  }
}

function setRunState(rs: RunState): void {
  scriptRunning = rs.state === "starting" || rs.state === "running";
  runPill($("run-pill"), rs);
  // a missing sandbox image never reaches the API as an error — the container
  // starts, dies, and the reason is in the log pane. Say where to look.
  if (rs.state === "exited" && (rs.reason === "stopped" || rs.reason === "replaced")) {
    $("run-hint").textContent = "stopped — press run to fly again";
  } else if (rs.state === "exited" && rs.exit_code !== null && rs.exit_code !== 0) {
    $("run-hint").textContent =
      "your script ended with an error — the reason is in the log pane";
  }
}

// reset kills a running script, so make a running reset a two-step press
const resetBtn = $("reset-btn") as HTMLButtonElement;
armedConfirm(resetBtn, "really reset?",
  () => void guarded(resetBtn, resetMine, "could not reset your drone"),
  () => scriptRunning);

// ----------------------------------------------------------------- templates

const templateSel = $("template-select") as HTMLSelectElement;

function onTemplatePick(): void {
  const variant = templateSel.value;
  templateSel.selectedIndex = 0; // snap back to the placeholder
  if (!variant) return;
  const apply = (): void => {
    void fetchTemplate(variant)
      .then((code) => { editor.setCode(code); banner(""); })
      .catch((e: unknown) => showError(describeError(e, "template"), apply));
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
let logCursor: LogCursor | null = null;

function appendLogs(batch: LogLine[]): void {
  // every reconnect re-sends the tail of the ring buffer; render only what is
  // actually new, or a bad afternoon of wifi doubles the pane
  const merged = freshLines(batch, logCursor);
  logCursor = merged.cursor;
  const lines = merged.fresh;
  if (lines.length === 0) return;
  const stickToBottom =
    logPane.scrollTop + logPane.clientHeight > logPane.scrollHeight - 40;
  for (const line of lines) {
    const div = document.createElement("div");
    div.className = line.stream;
    // the game talking to you is the one channel worth spotting in a wall of
    // prints: "DRONE: GAME: …" lines get their own colour and a marker
    if (line.stream === "stdout" && line.line.startsWith("DRONE: GAME:")) {
      div.classList.add("game");
    }
    div.textContent = line.line;
    logPane.appendChild(div);
  }
  while (logPane.childElementCount > 2000) logPane.firstElementChild?.remove();
  if (stickToBottom) logPane.scrollTop = logPane.scrollHeight;
}

const linkEl = $("d-link");
const carryingEl = $("d-carrying");
const walletEl = $("d-wallet");
let lastCarrying = false;

function updateStrip(me: DroneState): void {
  $("d-mode").textContent = me.mode;
  $("d-armed").textContent = me.crashed ? "CRASHED" : me.armed ? "yes" : "no";
  linkEl.classList.toggle("down", !me.connected);
  linkEl.querySelector("b")!.textContent = me.connected ? "up" : "down";
  $("d-n").textContent = me.n.toFixed(1);
  $("d-e").textContent = me.e.toFixed(1);
  $("d-alt").textContent = `${me.alt.toFixed(1)} m`;
  const wallet = walletText(me.pilot) + upgradesText(me.pilot);
  if (wallet !== walletEl.textContent) walletEl.textContent = wallet;
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

const stopBtn = $("stop-btn") as HTMLButtonElement;
async function stop(): Promise<void> {
  if (stopBtn.disabled) return;
  stopBtn.disabled = true;
  try {
    await stopRun();
    banner("");
  } catch (e) {
    showError(describeError(e, "stop"), () => void stop());
  } finally {
    stopBtn.disabled = false;
  }
}
stopBtn.addEventListener("click", () => void stop());
templateSel.addEventListener("change", onTemplatePick);

if (localStorage.getItem(TOKEN_KEY) && saved?.student_id) {
  void (async () => {
    // status first: it decides whether the stored token is still worth using,
    // refreshes who we are, and seeds the log cursor so the socket's replay
    // doesn't double-print
    if (await restore() && saved) await enter(saved.student_id, saved.name);
  })().catch(() => showJoin("could not restore your session — join again"));
} else {
  showJoin();
}
void offerRooms();
