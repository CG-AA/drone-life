# drone life — cheat sheet

## Fly

```python
from dronelife import connect
drone = connect()                    # your drone; the server wires this up

drone.takeoff(10)                    # GUIDED + arm + climb to 10 m
drone.goto(20, -40, 10)              # fly there (blocks; wait=False to not)
drone.move(3, 0, 0, seconds=5)       # velocity: 3 m/s north for 5 s
n, e, alt = drone.position()         # where am I? (updates 10×/s)
drone.events()                       # new GAME messages (a list of strings)
drone.next_event(timeout=10)         # block for the next one (or None)
drone.land()          drone.rtl()    # land here / fly home and land
drone.wait(2)         drone.armed    # sleep / motors-armed flag
drone.say("wallet")                  # talk to the game (siege: your coins)
drone.say("buy zap")                 # spend them: say("shop") lists prices
drone.say("quest")                   # opt in to quests (QUESTS.md): route / predict / compute
```

## The map

Arena **−100..100** m on N and E · center **(0, 0)** · your pad on the **south edge** (N −90, rows north of it for a big room) ·
max altitude **60 m** · max speed **10 m/s** · arena edges are soft, walls
are not.

## Read the game

The log pane shows `DRONE: GAME: crate 3 at N 12 E -40`; `drone.events()`
gives you `"crate 3 at N 12 E -40"` (prefix stripped). Every position is
`N <int> E <int>` — feed it straight into `goto(n, e, 2)`.

| you hear | you do |
|---|---|
| `crate 3 at N 12 E -40` | `goto(12, -40, 2)`, hold 2 s → it's yours |
| `got crate 3! drop at N 0 E 0` | carry to center, hover low 1 s → **+10** |
| `crate 3 taken` | someone was faster — next crate |
| `too high, get under 3 m` | descend: pickups happen **below 3 m** |
| `hands full, …` | deliver/place what you carry first (capacity: 1) |
| `no crate! grab one first` | you're at the dropoff empty-handed |
| `quarry at …` / `got steel …` | building games: same hover-low pickup |
| `wall gap at N 9 E -62 hover 4` | go there, hover **at 4 m**, 1.5 s |
| `hover 6 m to place` | right cell, wrong altitude — use the number |
| `creep at N 12 E -40` | siege: hover low on it 1.5 s → zap (1 hp; grunts +2, brutes +5) |
| `zap! brute hp 2` / `drop under 3 m to zap` | keep hovering / get lower |
| `wave 5 at N 0 E 83, 12 creeps + boss` | a champion (8 hp, +20) comes last — gang up |
| `build a tower at N 20 E -8` | between waves: ferry 3 steel there → auto-turret (+15) |
| `steel chewed at …` / `clay chewed at …` / `repair at N 9 E -62 hover 6` | walls reroute creeps; a closed ring (or a beacon) gets eaten, clay 3× faster; carrying the right tile nearby? hover the hole at that height → `repaired! +1` |
| `you spot gate E` → `gate E: 3 grunt 1 sapper` · `formation! hold 5 s to open gate S` | scout: hover 10 m from a gate 2 s, the room hears your reports · gate S (N −63 E 5): 3 drones in a triangle 5 s → 6 raiders that pay everyone |
| `clay pit at N 50 E -44` · `ring tower at …! +25` · `beacon up at …` · `bell up at …, hover 8 m to ring` | clay: cheap walls, beacon ends, the bell · 6 steel around a tower = 28 m reach · clay-steel-clay singles lure creeps within 25 m · 6-clay ring + 3 clay: hover on top 3 s, every creep freezes 15 s |
| `wave 3 clear! +10` (or `2 leaked +5`) | leaks = -1 each and half the bonus |
| `+8 coins, wallet 23` | every kill feeds a team pot; each wave clear splits it into everyone's wallet |
| `bought zap II (3 left)` / `need 40 coins, have 17` | `say("buy zap")`: zap 20/40/80 (reach, faster), speed 30/60, tower 40/80 (your towers), colour/outline 10 (`buy colour #ff8800`) |
| `quest 7: route 3 stops, 42 s` + `quest 7 stop 1 at N 20 E -30` … | a challenge for your code (regex `^(room )?quest (\d+)`): fly the stops / park where a creep will be / hover the Keep at a computed altitude — `docs/QUESTS.md`; +5 and coins for the room; nobody solving a `room quest` buffs the next wave |
| `quarry restocked, 27 steel` / `quarry empty, restock next wave` | the quarry is finite per wave — ferry what you will build |

## Top 5 errors

1. **`gave up waiting for: arming (is the drone crashed or mid-air?)`** —
   crashed, or you took off twice. Press **reset drone**, Run again.
2. **`PreArm: set mode GUIDED first`** — arming by hand in the wrong order.
   Just use `drone.takeoff(alt)`.
3. **Drone stops mid-air and hovers** — velocity commands expire after 3 s.
   Use `drone.move(...)` (it re-sends) or send again yourself.
4. **`CRASH: hit a wall`** — tiles are solid from the side. Fly over the top
   (walls max out at 8 m) — you respawn on your pad after 5 s.
5. **`syntax error, line N`** (red) — the editor jumps to the line. Fix, Run.

Bonus sixth: **drone stops dead at ±100 m** — that's the arena edge. The log
says `DRONE: bounds: clamped at arena edge`, but it is not a `GAME:` line, so
`drone.events()` never mentions it.

Stuck anyway? **reset drone** stops your script and puts you back on your
pad. Full guide: `STUDENT_GUIDE.md`.
