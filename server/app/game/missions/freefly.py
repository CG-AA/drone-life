"""No objectives, no scoring — just the shared sky.

Exists to prove the mission seam stays honest: if freefly works with zero
special-casing anywhere, new missions will too. The one thing it does say is
a welcome on connect, so the very first script a student runs already sees
`drone.events()` deliver something — the mechanic every later mission leans on.
"""

from ...sim.backend import DroneView
from ..mission import Mission, WorldAPI

WELCOME = ("GAME: welcome to the sky! fly anywhere",
           "GAME: crashes are free, walls are soft")


class FreeFlyMission(Mission):
    name = "freefly"

    def on_drone_event(self, world: WorldAPI, drone: DroneView, kind: str) -> None:
        if kind == "connected":
            for text in WELCOME:
                world.send_text(drone.id, text)
