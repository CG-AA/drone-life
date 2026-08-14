# drone life — pilot's guide

You have a drone in a shared sky. You fly it by writing Python. Everyone in the
class flies at the same time, on the same map, toward the same team score.

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

## The map

- Coordinates are meters. **N** (north) and **E** (east) both run **-100 to 100**.
- The center (0, 0) is the dropoff. Your pad is on the south edge.
- Max altitude 60 m. Max speed 10 m/s. The walls are soft — you just stop.

## Your toolkit (the `dronelife` helper)

```python
from dronelife import connect

drone = connect()                # your drone; the server wires this up

drone.takeoff(10)                # GUIDED mode + arm + climb to 10 m
drone.goto(20, -40, 10)          # fly there, waits until you arrive
drone.goto(20, -40, 2, wait=False)   # ...or don't wait
drone.move(3, 0, 0, seconds=5)   # velocity flying: 3 m/s north for 5 s
n, e, alt = drone.position()     # where am I?
drone.events()                   # new GAME messages since last call (a list)
drone.next_event(timeout=10)     # block until the next GAME message
drone.land()                     # land right here
drone.rtl()                      # fly home to your pad and land
drone.wait(2)                    # plain sleep
```

`print()` anything — it shows up live in your log pane.

## What's really happening (the pymavlink underneath)

`dronelife` is ~150 lines of ordinary **pymavlink** — the same library that
flies real ArduPilot drones. Open the `pymavlink` template on the submit page
(or read `dronelife`'s source) to see exactly what each helper sends:

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
| script hangs forever | a `recv_match(blocking=True)` with no `timeout` | always pass `timeout=...` in raw pymavlink |
| drone stops mid-flight and hovers | your velocity setpoints stopped arriving | that's the 3 s rule — use `move()` or re-send |
| drone flew home by itself | your script ended (or crashed) | check the log pane for the traceback |
| `syntax error, line N` in red | Python couldn't parse your script | click the banner — the editor jumps to the line |
| drone stuck somewhere weird | — | press **reset drone**: script stops, drone back on your pad |
| picked up nothing over a crate | too high, or not 2 full seconds | below 3 m altitude, hold still, count to 2 |

## Pro moves

- `drone.goto(n, e, alt, wait=False)` + your own loop over `drone.position()`
  = react to GAME events *while* flying.
- Crates get announced every ~20 s. `drone.events()` after takeoff catches the
  full map soon enough.
- When someone else grabs "your" crate you'll hear `GAME: crate 3 taken` —
  have a plan B.
