"""The shared world: all drones, one clock, one step() the driver calls at 20 Hz.

Pure and steppable — no asyncio, no wall clock — so tests can run it as fast as
they like and the unthrottled driver can burn through sim time.
"""

from __future__ import annotations

from ..game import hex
from .drone import DroneSim
from .terrain import FLAT, Terrain


class World:
    def __init__(self) -> None:
        self.t = 0.0
        self.epoch = 0  # bumped on reset so viewers clear trails
        self.drones: dict[str, DroneSim] = {}
        self.terrain: Terrain = FLAT  # a mission's TileMap, wired by the service

    @staticmethod
    def pad_position(slot: int) -> tuple[float, float]:
        # the pad row is a lattice row; hex.py is pure math, so this is the
        # one thing the sim borrows from the game package
        return hex.pad_position(slot)

    def spawn(self, drone_id: str, student_id: str, name: str, slot: int) -> DroneSim:
        n, e = self.pad_position(slot)
        drone = DroneSim(
            id=drone_id, student_id=student_id, name=name, sysid=slot + 1,
            spawn_n=n, spawn_e=e,
        )
        self.drones[drone_id] = drone
        return drone

    def remove(self, drone_id: str) -> None:
        self.drones.pop(drone_id, None)

    def step(self, dt: float) -> list[tuple[DroneSim, str]]:
        """Advance sim time; return (drone, lifecycle-event) pairs for the engine."""
        self.t += dt
        events: list[tuple[DroneSim, str]] = []
        for drone in self.drones.values():
            drone.step(self.t, dt, self.terrain)
            for kind in drone.events:
                events.append((drone, kind))
            drone.events.clear()
        return events

    def drain_texts(self) -> list[tuple[DroneSim, str]]:
        """Everything the scripts said since the last drain, for the engine."""
        out: list[tuple[DroneSim, str]] = []
        for drone in self.drones.values():
            if drone.inbox:
                out.extend((drone, text) for text in drone.inbox)
                drone.inbox.clear()
        return out

    def reset(self) -> None:
        self.epoch += 1
        for drone in self.drones.values():
            drone.reset_to_pad()
            drone.speed_scale = 1.0  # bought tiers are round state
