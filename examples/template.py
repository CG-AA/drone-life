"""Your drone, your code. Edit fly() and press Run.

Cheat sheet (full guide on the workshop page):
    drone.takeoff(alt)               climb to alt meters
    drone.goto(north, east, alt)     fly there; arena is -100..100 on both axes
    drone.move(vn, ve, vup, secs)    fly by velocity (m/s)
    drone.position()                 -> (north, east, altitude)
    drone.events()                   -> new GAME messages (where things are!)
    drone.land()   drone.rtl()       land here / fly home

Every game talks to you through drone.events() — "crate 3 at N 40 E -12",
"creep at N 10 E 55" — and position_in(msg) turns one into (north, east).
Delivery: hover low (under 3 m) over a crate for 2 s, carry it to N 0 E 0.
Siege: hover low near a creep to zap it; stack 3 steel = a watchtower.
Whatever your instructor has running, the game tells you what to do next;
the templates menu has a starter for each game.
"""

from dronelife import connect

drone = connect()


def fly():
    drone.takeoff(10)
    drone.goto(20, 20, 10)
    print("I am at", drone.position())
    drone.land()


fly()
