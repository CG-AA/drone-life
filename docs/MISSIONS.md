# Writing a mission

Missions are the game's content. Everything else — physics, MAVLink,
networking, rendering — is finished machinery you compose. A mission is one
Python class in `server/app/game/missions/`, and `freefly.py` proves the
floor is two lines.

This document is the contract. The generic test suite
(`server/tests/test_mission_contract.py`) enforces most of it mechanically:
if your mission is registered and `make test` is green, you have honored
everything marked **[enforced]**.

## The lifecycle, in the order the engine really calls it

```
MISSION=yours → service._bind_mission()
    __init__()                 # build your state; construct your TileMap here
    tile_map()                 # read ONCE at bind — the sim + viewer wire to
                               # this exact object for the process lifetime
service.start() → engine.start()
    tm.protect_pads(...)       # engine-owned: pads are unbuildable, always
    setup(world)               # world.drones() is already valid
each driver step (10 Hz):
    on_drone_event(world, drone, kind)   # all queued events, BEFORE tick
    tick(world, dt)                      # dt = 0.1 s
    entities(world)                      # serialized to every viewer
admin reset:
    reset(world)               # rebuild to post-setup state
```

Facts that bite if you don't know them:

- **`entities(world)` also runs on WebSocket connect — possibly before your
  first `tick`.** Read live state from `world`; never stash drone views in
  `tick` for `entities` to use. **[enforced]**
- **`tile_map()` identity is forever.** `reset()` clears and rebuilds the
  same `TileMap`; returning a new one silently disconnects the sim and the
  viewer from your terrain. **[enforced]**
- **`reset()` must end in the same state `setup()` produces.** Every in-tree
  mission clears its state then calls `self.setup(world)` — do the same.
- **An empty room must not raise** — and usually should freeze your clocks
  (see siege's early return). **[enforced: must not raise]**
- Every hook is exception-guarded by the engine: a bug in your mission logs,
  emits a throttled `mission_error` feed event, and the sim keeps flying.
  Exception: a broken `tile_map()` fails the boot loudly, on purpose.
- `on_drone_event` kinds are `DRONE_EVENT_KINDS` in `mission.py`
  (`joined … orphan_rtl`). Your handler must tolerate all of them.
  **[enforced]**

## WorldAPI — everything a mission may do

```python
world.rng          # seeded Random — use this, never the random module
world.config      # MissionConfig: arena_half, alt_max, pads (cells)
world.now          # sim seconds
world.drones()     # Sequence[DroneView] — read-only snapshots
world.emit_event(kind, msg, student_id=None, data=None)   # projector feed
world.add_score(points, reason, student_id=None) -> total # team score
world.send_text(drone_id, text)       # STATUSTEXT to one drone
world.broadcast_text(text)            # STATUSTEXT to everyone
```

`send_text` wants a **drone id** (`DroneView.id`); `emit_event`/`add_score`
want a **student id**. Adjacent lines often need both — don't swap them.

## The GAME text grammar (law) **[enforced]**

STATUSTEXT is 50 chars and students regex it. Every text starts with
`GAME: `, fits in 50 chars, announces positions as
`<thing> at N <int> E <int>` — use `fmt_world(n, e)` from `mission.py`
(or `building.fmt_cell(cell)` for cells) — and ends confirmations with `!`.
Keep the grammar and a parser written for one mission transfers to the next.

## Events — register your kinds

Every `emit_event` kind must be listed in `server/app/game/events.py`
**[enforced]** — that registry also pins the viewer HUD's severity table
(`web/src/viewer/hud.ts`, checked by `hud.test.ts`), so give your new kind a
severity class there (or an explicit `""` for neutral).

## Entities — what the viewer draws

Return `Entity(id, kind, n, e, alt, data)` records. Ids must be unique per
frame **[enforced]**. Kinds in play today, and who renders them
(`web/src/viewer/entities/`):

| kind | data | renderer |
|---|---|---|
| `crate` | `carried_by?` | delivery.ts |
| `dropoff` | — | delivery.ts |
| `tile_source` | `material`, `remaining` | building.ts |
| `tile_carried` | `carried_by`, `material` | building.ts |
| `ghost_tile` | `material`, `need`, `have`, `size` | building.ts |
| `furnace` | — | building.ts |
| `keep` | `hp`, `max` | siege.ts |
| `troop` | `dir` (deg), `chewing` | siege.ts |
| `tower` | `range` | siege.ts |
| `beam` | `tn`, `te`, `talt` | siege.ts |

- **`data.carried_by` is magic**: `api/messages.py` derives the drone's
  `carrying` field from it, which lights up the student page.
- An unknown kind renders as a neutral marker — your mission works before
  its renderer exists. Add the real renderer in a new module under
  `web/src/viewer/entities/` plus one `RENDERERS` entry in its `index.ts`.

## Building blocks (compose, don't reimplement)

- **`tiles.TileMap`** — hex cells → material stacks; doubles as sim terrain
  (drones crash into stacks, land on them). Pads are engine-protected;
  `set_keep_out([...])` is for your landmarks (quarries, gates).
  Materials live in `VALID_MATERIALS` (one string + a viewer color to add one).
- **`building.py`** — the ferry loop, reified: `TileSource` (hover-dwell
  pickup), `CarrySlots` (one tile per drone, lost on crash/disarm),
  `PlaceTracker` (hover-dwell placement with an `allowed` rule), and
  `tick_ferry(world, drones, carry, sources, dt, FerryTexts(...))` which runs
  the whole standard preamble. See rampart for guided placement, forge for
  free placement.
- **`blueprints.py`** — relative hex patterns that become structures when
  tiles complete them (`ring_blueprint`, `BlueprintTracker`); matching is
  anchored at the placed cell and rotation-invariant. Forge's furnace and
  siege's tower are data, not code.
- **`path.py` / `units.py`** — chew-aware Dijkstra flow fields and ground
  units that walk them (siege's creeps).
- **`hex.py`** — the lattice: `axial_to_world`, `world_to_axial`, `ring`,
  `disc`, `line`, `cells_along`, `pad_cell`.

## Testing your mission

The harness is `server/tests/support/harness.py`:

```python
from tests.support.harness import FakeWorld, assert_grammar, view

world = FakeWorld()
mission = MyMission()
world.start(mission)              # engine order: pads protected, then setup
world.views = [view("d0", n=10, e=-55, alt=4.0)]   # place a fake drone
world.run(mission, 5.0)           # ticks at 10 Hz, entities() every tick
world.drone_event(mission, world.views[0], "crashed")
assert world.score == ...         # world.scores, world.events, world.texts
assert_grammar(world)
```

The contract suite already covers your lifecycle basics the moment you
register; write mission tests for your *rules* (scoring, win conditions,
edge cases). Existing mission test files are the pattern book.

## New-mission checklist

1. `server/app/game/missions/yours.py` — subclass `Mission`, set a unique
   `name`.
2. Register it in `missions/__init__.py` (`YourMission.name: YourMission`).
3. New event kinds → `app/game/events.py` + a severity in `hud.ts`.
4. New entity kinds → renderer module + `RENDERERS` entry (or accept the
   neutral fallback for a first playtest).
5. `server/tests/test_mission_yours.py` for your rules.
6. Optional: a demo bot in `examples/` + the `BOT_SCRIPTS` set in
   `service.py`; a paragraph in `docs/STUDENT_GUIDE.md`.
7. `MISSION=yours make dev-server` + `make bots` — watch it play.
