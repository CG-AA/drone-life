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
    on_text(world, drone, text)          # what scripts said (dronelife.say), after events
    tick(world, dt)                      # dt = 0.1 s
    entities(world)                      # serialized to every viewer
    hud()                                # mission_state on every frame → the status strip
    pilot(student_id)                    # per-drone row on every frame (DroneState.pilot)
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
- `on_text` is the one command surface a script has: `dronelife.say(text)`
  sends a STATUSTEXT upstream, the sim strips and truncates it (≤ 50 chars,
  never empty, at most 8 per drone per 50 ms sim tick — so up to 16 per
  mission step), and the engine hands it to you verbatim. Interpret it
  yourself, reply with `send_text`.
  Ignored by default; must tolerate any string. **[enforced]**
- `set_speed` is the one physics knob a mission has, and it is per drone:
  the sim keeps it across a crash/respawn but a rejoined (re-spawned) drone
  is stock again, so re-apply what a pilot bought on every `connected`
  event (siege does — it is idempotent), and put everyone back to 1.0 in
  `reset()`.

## WorldAPI — everything a mission may do

```python
world.rng          # seeded Random — use this, never the random module
world.config      # MissionConfig: arena_half, alt_max, pads (cells)
world.now          # sim seconds
world.drones()     # Sequence[DroneView] — read-only snapshots
world.score        # the team total, read-only (round summaries)
world.emit_event(kind, msg, student_id=None, data=None)   # projector feed
world.add_score(points, reason, student_id=None, feed=True) -> total
world.send_text(drone_id, text, severity=SEV_INFO)   # STATUSTEXT to one drone
world.broadcast_text(text, severity=SEV_INFO)        # STATUSTEXT to everyone
world.set_speed(drone_id, scale)      # scale one drone's speed caps (1.0 = stock)
```

`add_score(..., feed=False)` moves the total (and milestones) without the
generic `+N: reason` feed row — use it whenever you also `emit_event` a
richer line for the same action (one thing that happened, one row), and for
high-frequency scoring (siege's tower shots) that would scroll the 8-row
feed blank. Put the points in your event's message instead.

`send_text` wants a **drone id** (`DroneView.id`); `emit_event`/`add_score`
want a **student id**. Adjacent lines often need both — don't swap them.
`send_text`/`broadcast_text` take an optional `severity` (`SEV_INFO`,
`SEV_WARNING` from `mission.py`) — the STATUSTEXT severity on the wire;
siege marks chews, losses and Keep hits as warnings.

## The GAME text grammar (law) **[enforced]**

STATUSTEXT is 50 chars and students regex it. Every text starts with
`GAME: `, fits in 50 chars, announces positions as
`<thing> at N <int> E <int>` — use `fmt_world(n, e)` from `mission.py`
(or `building.fmt_cell(cell)` for cells) — and ends confirmations with `!`.
Keep the grammar and a parser written for one mission transfers to the next.

The prefix, the length cap, and the position shape are checked on **every**
text the harness sees (`check_text` runs inside `FakeWorld.send_text` /
`broadcast_text`), so any tested code path is covered; the trailing-`!`
clause is style, reviewed by humans. Texts with unbounded interpolations
(ids, totals) are only covered for the values a test happens to produce, so
write a widest-case `check_text` test yourself (see
`test_mission_delivery.py::test_worst_case_texts_fit_the_wire`) — nothing
enforces it, and the wire truncates silently.

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
| `gate` | `label`, `active` (+ `sealed`, `hold` on gate S) | siege.ts |
| `troop` | `dir` (deg), `chewing`, `kind`, `hp`, `max`, `frozen`, `lured` | siege.ts |
| `tower` | `range`, `tier`, `ring` | siege.ts |
| `beacon` | `radius`, `lured`, `chew` | siege.ts |
| `bell` | `hover`, `charge` | siege.ts |
| `bell_ring` | — (an fx, 1.2 s) | siege.ts |
| `quest_mark` | `label`, `quest`, `done` | siege.ts |
| `beam` | `tn`, `te`, `talt` | siege.ts (tower shot, 0.6 s) |
| `zap_arc` | `tn`, `te`, `talt` | siege.ts (a drone's zap, 0.3 s) |
| `poof` | `verb` (zap/squish/tower/leak) | siege.ts (a creep died, 0.6 s) |

Short-lived cosmetics (`beam`, `zap_arc`, `poof`, `bell_ring`) are entities like any
other: the mission keeps them in a list with a wall-clock expiry and prunes
them every tick *before* any "empty room" early return, so they vanish even
when nobody is connected (`test_beams_expire_even_in_an_empty_room`). Ids
come from a monotonic counter so a burst never collides.

## HUD — `hud()`

`Mission.hud() -> dict` (default `{}`) rides every world frame as
`mission_state` and drives the projector's status strip under the score.
JSON-safe, integers and short strings, rebuilt from live state (it is called
on WS connect, possibly before the first tick, and after `reset()`). Siege
returns `wave`, `state`, `timer_s`, `keep_hp`, `keep_max`, `creeps_alive`,
`pending`, `towers`, `pool`, `quests` (`solved`, `missed`, and the live `room`
quest or null), `frozen_s`, `gate_s`, `stats` (the round tally without its
per-pilot map — that rides the drone rows), `last_round` (the record to
beat until wave 1 starts, else null); delivery returns `crates`,
`delivered`.
The strip's wording lives in `web/src/viewer/hud.ts` (`stripModel`, pure and
tested); add a branch there when your mission publishes something new.

**A round's summary is the `round_end` event.** Whatever a mission emits as
`round_end` from its `reset()` — siege does, with `data=stats.as_dict()` plus
`score`, `round`, `duration_s`, `pool`, `wallets`, and only when the round
was played (a reset of an untouched room emits nothing) — the service
appends to `<state>/rounds.jsonl` (`core/rounds.py`) once the reset
completes, with `ts`, `room`, `mission`, `seed`, `seats`, `names` in front
(`seats`/`names` are taken before the reset removes the bots). Only
`reset()` writes a line: a restart mid-round records nothing. Keep the data
JSON-safe and flat-ish: it is what `make balance` (`server/tools/balance.py`)
tabulates.

**Per-pilot state goes in `pilot(student_id)`, not `hud()`.** `hud()` is
one dict for the room; `Mission.pilot(student_id) -> dict` (default `{}`)
rides each drone's own row as `DroneState.pilot` — siege's wallet, bought
tiers and colours, and a compact `detail` tally that `api/messages.py`
copies onto the top-8 score rows for the PILOTS board — and lights up the
student page's strip. Both reach every socket at 10 Hz, so a
64-entry map inside `hud()` is 64× the bytes of the same data on the rows.

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
- **`building.py` hints** — the dwell trackers skip wrong drones silently;
  these speak up: `SourceHints` (too-high / hands-full nags at a pickup
  point), `PlaceHints` (right cell, wrong altitude), composed from
  `HoverHint` + `HintThrottle` (sustain before speaking, per-drone cooldown).
  A mission with a pickup point should tick a `SourceHints` next to its
  `tick_ferry` call — students doing it wrong deserve a next action. (A
  convention, not a checked rule: no test can tell a deliberate silence from a
  forgotten one.)
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
world.text(mission, world.views[0], "wallet")      # what drone.say() delivers
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
