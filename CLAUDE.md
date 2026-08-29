# drone-life — agent notes

Workshop co-op drone game: FastAPI/asyncio server (`server/`), Vite+TS
frontend (`web/`), podman student sandbox (`runner/`), operator tooling in
`server/tools/` (`balance.py`, on `app/headless.py`). Students fly simulated
drones with real pymavlink scripts; missions are server-side plugins;
`examples/answers/` holds the worked quest answers, kept out of the template
menu and the default bot allowlist (`EXTRA_BOT_SCRIPTS` widens it, dev only).

## Commands

```bash
make test          # server pytest + web vitest — must stay green
make lint          # ruff (server) + eslint (web); make lint-fix autofixes ruff only
make typecheck     # tsc --noEmit (web) + mypy (server)
make build         # tsc + vite build
make e2e           # needs podman + `make image` — silently SKIPS (not fails) without them
make load          # timing-sensitive, local only
make preflight     # workshop-morning box check (podman, image, secrets, XDG_RUNTIME_DIR…)
make balance       # ROUNDS= BOTS= SECONDS=: headless bot-only siege rounds → server/state/balance/rounds.jsonl (real time)
make dev-server    # http://localhost:8000  (MISSION=<name> selects content)
make dev-web       # hot-reload frontend on :5173, proxies /api and /ws to :8000
```

Server deps: `cd server && uv sync` (Python 3.12, uv-managed).
Web deps: `cd web && npm ci` (Node ≥20; `.nvmrc` says 22, CI uses 22).
Setup from a fresh box, deploys, and the workshop-day flow: `README.md`.

## The contracts that matter

- **`docs/MISSIONS.md` is the mission contract**; the generic suite
  `server/tests/test_mission_contract.py` enforces it. New content goes in
  `server/app/game/missions/` + the registry in `missions/__init__.py`.
- **GAME text grammar (law)**: STATUSTEXT starts `GAME: `, ≤50 chars,
  positions as `N <int> E <int>` via `fmt_world`; confirmations end `!`.
- **`Mission.tile_map()` identity is process-stable** — reset() rebuilds the
  same object, never replaces it.
- **Event kinds** must be registered in `server/app/game/events.py`; the web
  HUD table is test-pinned to that file (marker block — keep its format).
- **Wire shapes**: `server/app/api/messages.py` ↔ `web/src/shared/protocol.ts`
  mirror each other; update both sides together.
- **Per-pilot mission data rides `Mission.pilot(student_id)`** on the
  drone rows, never `hud()`/`mission_state` (one dict for the room, at
  10 Hz to every socket). A mission's `round_end` event data is what
  `rounds.jsonl` records at reset (`docs/MISSIONS.md`).
- **The page may live under a prefix** (`/rN/` rooms, `docs/ROOMS.md`):
  frontend REST/WS go through `web/src/shared/http.ts` / `ws.ts`, which add
  `shared/prefix.ts`; never `fetch("/api/…")` or root-absolute hrefs/assets
  directly (Vite `base: "./"`). The server stays prefix-unaware.
- Architecture seams and bring-up order: see `CONTRIBUTING.md`.

## Gotchas

- mavutil is blocking — server-side only the generated dialect parser is
  used (`app/mav/wire.py`); MAVLink 2 everywhere (`MAVLINK20=1`).
- One event loop runs the 20 Hz sim driver and all HTTP/WS — never block it
  (file I/O on request paths → `asyncio.to_thread`).
- Gateway/API tests bind real loopback ports; a rare port-collision flake
  re-runs clean.
- `tests/support/harness.py` is the mission test harness (do not import test
  helpers from conftest).
