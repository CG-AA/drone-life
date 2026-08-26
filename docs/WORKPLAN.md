# Workshop work plan — tracks, worktrees, tasks

Disposable planning doc for the final days before the workshop. Delete after.

## The layout: four worktrees, four track branches

`main` stays the integration point; each track lives in its own git worktree
so work-in-progress never collides and each can be handed to a separate
person/agent/session:

```bash
git worktree add ../dl-security  -b track/security  main
git worktree add ../dl-realworld -b track/realworld main
git worktree add ../dl-gameplay  -b track/gameplay  main
git worktree add ../dl-frontend  -b track/frontend  main
```

Each worktree needs its own deps (venv and node_modules are per-checkout):
`cd server && uv sync` and `cd web && npm install`. Merge back into `main`
at least daily; every merge keeps `make test lint typecheck build` green
(CONTRIBUTING rule — CI checks all four).

### Ownership map (avoids merge conflicts)

| track | owns | stays out of |
|---|---|---|
| security | `server/app/runner/podman.py`, `api/auth.py`, `config.py`, `runner/Containerfile`, DEPLOY threat-model section | game/, web/ |
| realworld | `server/app/service.py`, `runner/manager.py`, `api/ws.py`, Makefile, DEPLOY runbook | missions, viewer |
| gameplay | `server/app/game/**`, `examples/**`, STUDENT_GUIDE, MISSIONS.md, `web/src/viewer/entities/` | api/, runner/ |
| frontend | `web/src/**` (viewer core, submit, admin) | server/ except `messages.py` |

Pair-file rule (these are test-pinned mirrors — change both sides in ONE
branch, never split across tracks):
- `server/app/api/messages.py` ↔ `web/src/shared/protocol.ts` → frontend owns; gameplay/realworld request changes.
- `server/app/game/events.py` ↔ `web/src/viewer/hud.ts` → gameplay owns (new event kinds land with their HUD row in the same commit).

Priorities: **P0** = can ruin the day, do first. **P1** = the experience
floor. **P2** = polish/stretch, cut without guilt.

---

## Track 1 — security (`track/security`)

Grounded in the current code; the sandbox itself (`podman.py`) is already
tight (cap-drop ALL, read-only, 256m/0.5cpu/64pids, ro mount).

1. **P0 — default-secrets startup guard.** `ROOM_CODE=classroom` /
   `ADMIN_TOKEN=change-me` are only guarded by a docs sentence. Add a loud
   startup refusal (or `ALLOW_DEFAULT_SECRETS=1` escape hatch for dev) in
   `config.py`/`main.py`.
2. **P0 — join rate-limit keying behind the proxy.** `routes_public.py:40`
   keys on `request.client.host`; behind the OCI nginx proxy every student
   shares one IP → 30 joins/min is a *class-wide* bucket and one prankster
   locks everyone out. Honor `X-Forwarded-For` only from the trusted proxy
   (uvicorn `--proxy-headers` + forwarded-allow-ips, or an explicit setting).
3. **P1 — constant-time token compares.** `auth.py:31` uses `!=` for the
   admin token; room-code compare likewise. `secrets.compare_digest`. Tiny.
4. **P1 — outbound-internet decision.** slirp4netns NATs containers to the
   whole internet (loopback is the *extra*, not the limit): student scripts
   can `pip install`, exfiltrate, phone home. Decide: accept + document in
   the threat model, or restrict (custom netns/firewall). Decision first,
   code second.
5. **P1 — WS auth audit.** Confirm `/ws/viewer` and `/ws/student` gate on
   room code / student token like the REST routes do.
6. **P2 — abuse limits.** Per-student submit rate; log-flood ceiling in
   `runner/logs.py`; note in threat model that any student can connect to
   another drone's loopback MAVLink port (accepted: visible on projector).
7. **P2 — run the security-review pass** over the branch + an e2e probe
   that asserts the sandbox properties (no caps, ro fs, mount perms).

## Track 2 — real-world constraints & exceptions (`track/realworld`)

1. **P0 — `make preflight`.** One command for workshop morning: podman
   present, subuid/subgid ranges, slirp4netns, `drone-life-runner` image
   built (`--pull=never` means a missing image = every submit 503s),
   MAVLink ports free, `web/dist` built, state dir writable, disk space.
2. **P0 — failure drills, on the real lab server.** Kill podman mid-run;
   kill the server mid-class (state snapshot restore); yank the projector's
   network; submit while image missing. Each must surface a clear message
   somewhere a human looks. Fix what doesn't.
3. **P0 — `make load` at class size** (`MAX_STUDENTS=20`, 20 bots) on the
   actual hardware; watch `overruns` via `/healthz`. Tune if >1%.
4. **P1 — driver-loop crash containment.** Verify (test!) that a raising
   `Mission.tick()` cannot kill `service._driver`. If it can, guard + emit
   an event instead of dying silently at 20 Hz.
5. **P1 — run-death reasons.** Script that crashes instantly, hangs, or
   hits the 900 s wall cap: does the student's log tail *say why it ended*?
   Improve end-of-run messages in `runner/manager.py` / status payload.
6. **P1 — reconnects.** Viewer WS auto-reconnect with backoff (projector
   sits for hours); submit page survives a refresh (token persistence +
   rejoin path — verify, it looks built).
7. **P2 — admin observability.** Surface `/healthz`'s overruns/tick/score
   and per-student run states on the admin console.
8. **P2 — contingency runbook.** DEPLOY.md additions: proxy dead → hotspot
   fallback; restart procedure; "switch mission" = env edit + restart
   (30-second script, since MISSION is boot-time).

## Track 3 — gameplay experience (`track/gameplay`)

The judgment-heavy track — keep this one for yourself.

1. **P0 — the session plan.** Pick the day's arc (e.g. freefly warmup →
   delivery main → siege finale), rehearse every transition with
   `make bots` + `make reset`, write the minute-by-minute plan into the
   runbook. Missions exist; the *sequence* is the product.
2. **P0 — balance delivery at class size.** 20 bots: is the crate flow
   starved or flooded? Does the score arc peak mid-session? Tune spawn
   rates/values, not mechanics.
3. **P1 — GAME-message audit.** For every wrong thing a student will do
   (wrong altitude, not over the crate, cargo full, out of bounds…) there
   must be a terse `GAME:` line telling them the *next action*. The grammar
   suite pins format; this is about coverage.
4. **P1 — STUDENT_GUIDE + printable cheat sheet.** The handout read cold:
   dronelife helper API, GAME message glossary, top-5 errors. One page.
5. **P1 — first-five-minutes check.** `template.py` unedited must produce a
   visible win (takeoff + move) on the day's first mission. Verify.
6. **P2 — flourish.** Per-student attribution in the feed ("Alice
   delivered!"), celebration event kinds (pair-file rule applies),
   bot_courier as a pace-setter during lulls.
7. **P2 — stretch missions tuning** (rampart/siege wave pacing) only if the
   session plan actually uses them.

## Track 4 — frontend UI/UX (`track/frontend`)

1. **P0 — projector readability pass.** Stand five meters back: HUD font
   sizes, score, event feed, drone name labels, contrast on a washed-out
   projector. `viewer.css`, `hud.ts`, `colors.ts`.
2. **P0 — submit-page error UX.** The server already sends structured
   errors (syntax line/col, 503 runner, 401 token, 413 too-big, 429 rate).
   Render each humanely; jump the editor to the syntax-error line.
3. **P1 — scene resize staleness** (`scene.ts:144` known issue) — matters
   the moment the projector goes fullscreen or changes resolution.
4. **P1 — join-flow polish.** Room code entry, rejoin-after-refresh, clear
   room-full / name-reserved messages.
5. **P1 — admin glance test.** Instructor must spot a stuck student in
   ~2 s: run-state colors, one-click kill with confirm, type-to-confirm on
   world reset.
6. **P2 — camera.** Auto-fit the arena on load; optional follow-drone mode
   for highlight moments.
7. **P2 — idle/attract state.** Pre-class viewer shows the arena + the
   room code huge, so joining is self-serve as students trickle in.

---

## Sequencing (days, not weeks)

- **Now → day −2:** all P0s in parallel across the four worktrees; merge to
  `main` nightly.
- **Day −2 → −1:** P1s; stop taking new scope.
- **Day −1: freeze.** No features. Full dry run on the lab server:
  `make preflight`, `make e2e`, `make load`, then the runbook end-to-end
  with 3 bots and one real phone/laptop as a fake student.

## Offloading

Security, realworld, and frontend tasks above are specified tightly enough
to hand to someone else (or a Claude session per worktree) verbatim.
Gameplay needs your taste and a rehearsal loop — that's the focus track.
