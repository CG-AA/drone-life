# drone life — pilot's guide

You have a drone in a shared sky. You fly it by writing Python. Everyone in the
class flies at the same time, on the same map, toward the same team score.

Your instructor announces which mission is live — the day usually starts in
**freefly** (no objectives, just fly) before the scoring games below. The
one-page version of this guide is `CHEATSHEET.md` (on your desk).

## The game

**Co-op delivery.** Crates appear around the arena. Hover **low (below 3 m)**
over a crate for **2 seconds** to pick it up, then carry it to the **dropoff
pad at N 0, E 0** and hover low for 1 second. Every delivery is **+10 for the
whole class**.

Your drone tells you where crates are — watch your script's output:

```
DRONE: GAME: crate 3 at N 12 E -40
```

That means: `drone.goto(12, -40, 2)` puts you right on top of it.

## The building games (if your instructor picked one)

Some sessions run a **hex-tile building mission** instead of delivery. Tiles
stack into real walls — drones **crash into them** from the side, but can fly
over and even **land on top**.

- **rampart** — ferry steel from the quarry onto the ghost wall. Hover **low
  (below 3 m)** at the quarry for **2 s** to grab a tile, then hover at the
  announced spot **at the announced altitude** for **1.5 s** to place it:

  ```
  DRONE: GAME: quarry at N -30 E 40
  DRONE: GAME: wall gap at N 10 E -55 hover 4
  ```

  means `drone.goto(-30, 40, 2)`, wait for `got steel`, then
  `drone.goto(10, -55, 4)` and hold still. Each block climbs the target
  altitude by 2 m — the game always tells you the right number. Every
  placed tile is **+2**, and finishing the whole wall pays **+40**.
- **forge** — same ferry loop from the clay pit, but you build anywhere
  (**+1** per tile): close a **ring of 6 clay tiles** and a furnace
  lights for +30.
- **canyon** — no scoring, just walls in the sky. Practice flying over
  (or through the corridor) without becoming a wreck on the ramparts.
- **siege** — tower defense. Creep waves march from a gate toward the
  **Keep at (0, 0)**; every one that arrives costs it hp (and the class
  points — the Keep falling is **−25**, though it rebuilds). Every kill
  pays **+2** and a cleared wave **+10**. Three ways to fight back:
  1. **Zap**: hover low over a creep for **1.5 s** — the game texts you your
     nearest target (`GAME: creep at N 12 E -40`) every few seconds.
  2. **Squish**: place a tile right on top of one (same ferry loop as
     rampart — steel comes from the announced quarry).
  3. **Watchtower**: stack **3 steel on one cell** (+15) and it auto-fires
     at everything within 12 m.

  Walls 2 tiles high reroute the creeps into your kill zones — but nothing
  is forever: a blocked creep **chews** through (watch for `wall chewed`
  warnings, and rebuild). You get 45 s of peace before wave 1, and 20 s
  between waves. Waves grow; the Keep pays -25 if it falls, then rebuilds.

Crashing into a wall costs you your tile and 5 s on the ground — the arena
edges are still soft, but steel is not.

## The map

- Coordinates are meters. **N** (north) and **E** (east) both run **-100 to 100**.
- The center (0, 0) is the dropoff. Your pad is on the south edge (N −90).
- Max altitude 60 m. Max speed 10 m/s. The walls are soft — you just stop.

## Your toolkit (the `dronelife` helper)

```python
from dronelife import connect

drone = connect()                # your drone; the server wires this up

drone.takeoff(10)                # GUIDED mode + arm + climb to 10 m
drone.goto(20, -40, 10)          # fly there, waits until you arrive
drone.goto(20, -40, 2, wait=False)   # ...or don't wait
drone.goto(0, 0, 2, tolerance=0.5, timeout=30)  # arrival slack (m) / give-up (s)
drone.move(3, 0, 0, seconds=5)   # velocity flying: 3 m/s north for 5 s
n, e, alt = drone.position()     # where am I?
drone.events()                   # new GAME messages since last call (a list)
drone.next_event(timeout=10)     # block until the next GAME message (or None)
drone.land()                     # land right here
drone.rtl()                      # fly home to your pad and land
drone.wait(2)                    # plain sleep
drone.armed                      # True while the motors are armed
drone.set_mode(5)                # raw mode switch (4=GUIDED 5=LOITER 6=RTL 9=LAND)
drone.close()                    # hang up cleanly (scripts may also just end)
```

`print()` anything — it shows up live in your log pane.

One subtlety worth knowing: your log pane shows `DRONE: GAME: crate 3 at
N 12 E -40`, but the strings `drone.events()` hands you have the `GAME: `
prefix already stripped — match against `"crate 3 at N 12 E -40"`. (The bot
examples in `examples/` regex exactly that form.)

## GAME messages — glossary

Every message names your next action. Positions are always `N <int> E <int>`
— feed them straight into `goto`.

**Delivery**

| message | it means → do this |
|---|---|
| `crate 3 at N 12 E -40` | a crate is on the ground → `goto(12, -40, 2)` and hold |
| `got crate 3! drop at N 0 E 0` | it's yours → carry it to the center, hover low |
| `crate 3 taken` | someone beat you to it → pick another crate |
| `delivered! +10 (team 128)` | scored — the number is the team total |
| `too high, get under 3 m` | you're over the spot but too high → descend |
| `hands full, drop at N 0 E 0` | you already carry a crate → deliver it first |
| `no crate! grab one first` | you're at the dropoff empty-handed → go get one |
| `crate lost, grab another` | your crash dropped it → a fresh one just spawned |

**Building (rampart / forge / siege share the ferry loop)**

| message | it means → do this |
|---|---|
| `quarry at N -31 E 39` / `clay pit at …` | the pile → hover it low (below 3 m) for 2 s |
| `got steel, place on the wall` (or clay…) | carrying → fly to a target cell |
| `wall gap at N 10 E -55 hover 4` | rampart tells you where AND the altitude |
| `hover 6 m to place` | right cell, wrong height → hover at that altitude |
| `placed! wall 12/34 +2` / `clay placed +1` | it landed — progress and points |
| `not a wall cell` / `can't build there` | wrong spot → aim for the announced cells |
| `steel lost, grab another` | a carrier crashed → back to the pile |
| `hands full, place your steel/clay` | you can carry exactly one tile |
| `rampart complete! +40` / `furnace lit! +30` | the team finished a structure |

**Siege**

| message | it means → do this |
|---|---|
| `keep at N 0 E 0, protect it!` | the thing creeps are marching toward |
| `wave 3 at N 85 E 0, 8 creeps` | where they enter, how many are coming |
| `creep at N 12 E -40` | your nearest target — it's moving, lead it |
| `hover low on a creep to zap it` | stay within ~4 m, low, for 1.5 s |
| `zap! creep down +2` / `squish! creep under tile +2` | a kill, either way |
| `stack 3 steel = watchtower` | 3 tiles on one cell → auto-firing tower (+15) |
| `tower up! +15` / `tower down at …` | a tower rose / was chewed from under |
| `wall chewed at N 10 E -55` | a blocked creep is eating through → rebuild, zap it |
| `wave 3 clear! +10` / `wave 4 in 20s, build!` | breathe, then build |
| `keep hit! hp 7` / `keep fell! -25, rebuilt` | leaks cost points; it never game-overs |

## What's really happening (the pymavlink underneath)

`dronelife` is ~150 lines of ordinary **pymavlink** — the same library that
flies real ArduPilot drones. Pick **pymavlink** from the template menu in the
submit-page toolbar (or read `dronelife`'s source) to see exactly what each
helper sends:

| helper | MAVLink underneath |
|---|---|
| `connect()` | `mavutil.mavlink_connection(url)` + `wait_heartbeat()` |
| `takeoff(10)` | `COMMAND_LONG: DO_SET_MODE(GUIDED=4)`, `ARM_DISARM(1)`, `NAV_TAKEOFF(alt=10)` |
| `goto(n, e, alt)` | `SET_POSITION_TARGET_LOCAL_NED` (type_mask 3576, z = **-alt** — NED z points down!) |
| `move(vn, ve, vup, s)` | `SET_POSITION_TARGET_LOCAL_NED` (type_mask 3527, velocity), re-sent 2×/s |
| `land()` / `rtl()` | `COMMAND_LONG: NAV_LAND` / `NAV_RETURN_TO_LAUNCH` |
| `position()` | reads the `LOCAL_POSITION_NED` telemetry stream |
| `events()` | reads `STATUSTEXT` messages starting with `GAME:` |

Everything you learn here transfers: point the same code at a real drone's
connection string and the messages are identical.

## Rules the sim enforces (same as real ArduPilot, roughly)

1. You must be in **GUIDED** mode to arm.
2. You must **arm** before takeoff.
3. Position/velocity commands only work **while airborne**.
4. Velocity commands expire after **3 s** — keep re-sending them (or use `move()`).
5. Force-disarming mid-air **crashes your drone** (it respawns on your pad after 5 s).
6. If your script exits or crashes, your drone waits 10 s, then **flies itself home**.

## When things go wrong

| symptom | why | fix |
|---|---|---|
| `DRONE: PreArm: set mode GUIDED first` | armed before setting mode | `drone.takeoff()` does the right order for you |
| `gave up waiting for: arming (is the drone crashed or mid-air?)` | ran takeoff while crashed or already flying | press **reset drone**, then Run again |
| `DRONE: replaced by a new connection` | two scripts (or two `connect()`s) at once | one Run at a time — the newest wins |
| script hangs forever | a `recv_match(blocking=True)` with no `timeout` | always pass `timeout=...` in raw pymavlink |
| drone stops mid-flight and hovers | your velocity setpoints stopped arriving | that's the 3 s rule — use `move()` or re-send |
| drone flew home by itself | your script ended (or crashed) | check the log pane for the traceback |
| `syntax error, line N` in red | Python couldn't parse your script | the editor jumps to the line for you |
| drone stuck somewhere weird | — | press **reset drone**: script stops, drone back on your pad |
| picked up nothing over a crate | too high, or not 2 full seconds | below 3 m altitude, hold still, count to 2 — the drone now tells you (`too high, get under 3 m`) |
| `DRONE: CRASH: hit a wall` | flew into a tile stack side-on | go over the top (walls max out at 8 m) or around |
| tile won't place | wrong altitude, wrong cell, or empty hands | hover at the **announced** altitude on the announced spot, carrying |
| creep won't die under me | too high, or it walked out from under you | stay within ~4 m of it, **below its feet + 3 m**, for a full 1.5 s |
| my wall is disappearing | a blocked creep is chewing it | that's the `wall chewed` warning — zap the chewer, rebuild the tile |

## Pro moves

- `drone.goto(n, e, alt, wait=False)` + your own loop over `drone.position()`
  = react to GAME events *while* flying.
- Crates get announced every ~20 s. `drone.events()` after takeoff catches the
  full map soon enough.
- When someone else grabs "your" crate you'll hear `GAME: crate 3 taken` —
  have a plan B.

## Level up (for the engineers in the room)

Done early? Pick **pymavlink** from the templates menu and re-fly your script
in the raw protocol — everything `dronelife` does is ~150 lines you can read.
Then try beating the house bots (`examples/bot_courier.py`,
`examples/bot_siege.py` — note how the siege bot *leads* its target). Your
instructor has more where that came from.
