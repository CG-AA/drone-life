# Contributing

## Ground rules

- Every commit leaves `make test`, `make lint`, `make typecheck`, and
  `make build` green — CI (`.github/workflows/ci.yml`) checks all four on
  every PR. `make lint` covers `server/app`, `server/tests` and
  `server/tools` (the operator tooling, `make balance`).
- New game content = a mission plugin. Read `docs/MISSIONS.md` first; it is
  the contract, and `tests/test_mission_contract.py` enforces it.
- Keep the seams below intact. If a change needs to cross one, that's a
  design conversation, not a patch.

## Architecture: the seams

One Python process (FastAPI + asyncio, one event loop) hosts everything.
`DroneLifeService` (`server/app/service.py`) is the whole game in one object;
`main.py` is a thin FastAPI shell around it, and tests drive the service
directly.

| seam | where | what it isolates |
|---|---|---|
| `DroneBackend` / `DroneView` | `app/sim/backend.py` | everything above the sim sees snapshots and an async spawn/remove/send_text interface, plus one deliberate physics knob, `set_speed(drone_id, scale)` (siege's speed upgrade — a backend that cannot honour it may ignore it); a future ArduPilot-SITL backend implements the same ABC out-of-process |
| `Terrain` (structural Protocol) | `app/sim/terrain.py` | the sim asks only `height_at(n, e)`; a mission's `TileMap` satisfies it without importing sim behavior |
| `WorldAPI` / `Mission` | `app/game/mission.py` | missions see the world only through WorldAPI and describe themselves only as `Entity` records — physics, networking, rendering never change for content |
| `WorldSink` | `app/service.py` | what the driver hands each frame to (`broadcast_world`, `broadcast_tiles`, `send_run_state`): the WS `Hub` in the app, `app/headless.py`'s `NullHub` when nobody is watching (the load test, `make balance`) |
| `Hub` | `app/api/ws.py` | fan-out only: latest-wins world slot per socket, bounded FIFO for events/logs, one sender task per socket; the driver loop never awaits a send |
| wire shapes | `app/api/messages.py` ↔ `web/src/shared/protocol.ts` | one module per side mirrors the other; the event-kind registry (`app/game/events.py` ↔ `hud.ts`) is test-pinned |

The driver loop (`service._driver`) steps the sim at 20 Hz and runs
mission + broadcast every 2nd tick (`MISSION_HZ`). Anything that blocks the
event loop stalls the whole game — file I/O on hot paths goes through
`asyncio.to_thread`.

## Bring-up / teardown order

`running_app()` in `server/tests/conftest.py` is the canonical order, shared
by the API tests and the podman e2e so it cannot drift:

```
app = create_app(settings)
await service.start()      # restore snapshot → spawn drones → engine.start
hub.start()                # log flusher
...
await hub.stop()           # flusher awaited out
await service.stop()       # driver/snapshotter cancelled+awaited, runner, gateway
```

## Layout and where things go

See the Layout table in `README.md`. Rules of thumb:

- Game mechanics that two missions could share belong in `app/game/`
  (`building.py`, `blueprints.py`, `path.py`, `units.py`), not in a mission.
- `app/sim/` stays pymavlink-free; the dialect boundary is `app/mav/wire.py`.
- Config is `app/config.py` only — no scattered `os.getenv`. Document new
  settings in `docs/DEPLOY.md`'s table.
- Web: wire types in `shared/protocol.ts`, page-shared DOM helpers in
  `shared/ui.ts`, per-mission renderers in `viewer/entities/`.
- Operator tooling that drives the service headless lives in
  `server/tools/` (`python -m tools.balance` from `server/`) on top of
  `app/headless.py` (`NullHub`, `find_port_base`) — never in `app/`.

## Tests

```bash
make test          # default suite: server pytest + web vitest
make lint          # ruff (server) + eslint (web); make lint-fix autofixes ruff only
make typecheck     # tsc --noEmit (web) + mypy (server)
make e2e           # needs podman + `make image` — without them the suite SKIPS, it does not fail
make load          # timing-sensitive: run on a quiet machine (LOAD_BOTS=20 for class size)
make preflight     # not a test: checks the box a workshop is about to run on
make balance       # not a test: N headless bot-only siege rounds → state/balance/rounds.jsonl (real minutes)
```

- Mission tests use `tests/support/harness.py` (`FakeWorld`, `view`,
  `assert_grammar`) — no MAVLink, no sim.
- Gateway/API tests bind real loopback TCP ports and drive real `mavutil`
  clients; they are fast but not parallel-safe across processes.
- The suite must stay green on a plain runner: anything needing podman is
  `@pytest.mark.e2e`, anything timing-sensitive `@pytest.mark.load` (both
  excluded by default addopts).
