"""The Mission contract, enforced generically over every registered mission.

Whatever a mission does, it must: register under its own unique name, survive
the real engine call order (including entities() before the first tick — the
WS-connect path), tolerate an empty room, keep tile_map() identity across
reset(), and obey the STATUSTEXT grammar law. A new mission gets all of this
checked by writing zero new test code.
"""

import importlib
import pkgutil

import pytest

import app.game.missions as missions_pkg
from app.game.mission import DRONE_EVENT_KINDS, Mission
from app.game.missions import MISSIONS
from tests.support.harness import FakeWorld, assert_grammar, view


def all_mission_classes() -> list[type[Mission]]:
    classes: list[type[Mission]] = []
    for info in pkgutil.iter_modules(missions_pkg.__path__):
        mod = importlib.import_module(f"{missions_pkg.__name__}.{info.name}")
        classes += [obj for obj in vars(mod).values()
                    if isinstance(obj, type) and issubclass(obj, Mission)
                    and obj is not Mission and obj.__module__ == mod.__name__]
    return classes


def test_registry_is_complete_and_consistent():
    classes = all_mission_classes()
    names = [cls.name for cls in classes]
    assert len(names) == len(set(names)), f"duplicate mission names: {sorted(names)}"
    assert "base" not in names, "a mission forgot to set its own name"
    for cls in classes:
        assert MISSIONS.get(cls.name) is cls, f"{cls.__name__} not registered as {cls.name!r}"
    assert set(MISSIONS) == set(names), "registry and missions/ package disagree"


@pytest.mark.parametrize("name", sorted(MISSIONS))
def test_lifecycle_contract(name):
    world = FakeWorld()
    mission = MISSIONS[name]()
    tm = mission.tile_map()  # the service reads this before setup runs

    world.start(mission)
    mission.entities(world)  # WS connect can serialize before the first tick

    world.views = [view()]
    for kind in DRONE_EVENT_KINDS:  # every documented event, with a live drone
        world.drone_event(mission, world.views[0], kind)
    world.run(mission, 5.0)

    world.views = []
    world.run(mission, 5.0)  # an empty room must never raise

    assert mission.tile_map() is tm, "tile_map identity must be process-stable"
    mission.reset(world)
    assert mission.tile_map() is tm, "reset() rebuilds the same map, never replaces it"

    ids = [ent.id for ent in mission.entities(world)]
    assert len(ids) == len(set(ids)), "entity ids must be unique"
    assert_grammar(world)
