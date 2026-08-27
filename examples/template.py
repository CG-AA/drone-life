"""Your drone, your code. Edit fly() and press Run.

Cheat sheet (full guide on the workshop page):
    drone.takeoff(alt)               climb to alt meters
    drone.goto(north, east, alt)     fly there; arena is -100..100 on both axes
    drone.move(vn, ve, vup, secs)    fly by velocity (m/s)
    drone.position()                 -> (north, east, altitude)
    drone.events()                   -> new GAME messages (crate locations!)
    drone.land()   drone.rtl()       land here / fly home

Co-op delivery (one of the day's games): hover low (below 3 m) over a crate
for 2 seconds to pick it up, then carry it to the dropoff pad at north=0,
east=0 and hover low again. Whatever your instructor has running, watch
drone.events() — the game tells you what to do next.
"""

from dronelife import connect

drone = connect()


def fly():
    drone.takeoff(10)
    drone.goto(20, 20, 10)
    print("I am at", drone.position())
    drone.land()


fly()
