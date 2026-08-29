"""rounds.jsonl: append-only, one record a line, corrupt lines skipped; the
service writes a line at every reset that ends a played round."""

import json

from app.core import rounds
from app.service import DroneLifeService
from tests.conftest import make_settings


def test_append_and_read_round_trip_and_skip_garbage(tmp_path):
    path = tmp_path / "state" / "rounds.jsonl"
    rounds.append(path, {"round": 1, "kills": 3})
    rounds.append(path, {"round": 2, "kills": 5, "pilots": {"s0": {"zapped": 1}}})
    path.write_text(path.read_text() + "{not json\n\n")
    rounds.append(path, {"round": 3})
    assert [r["round"] for r in rounds.read(path)] == [1, 2, 3]
    assert rounds.read(tmp_path / "nothing.jsonl") == []
    lines = path.read_text().splitlines()
    assert json.loads(lines[0]) == {"kills": 3, "round": 1}


async def test_a_reset_after_play_appends_a_round_line(tmp_path):
    settings = make_settings(tmp_path, mission="siege", sim_seed=11, room_id="lab")
    service = DroneLifeService(settings)
    await service.start()
    try:
        await service.join("Ada")
        m = service.engine.mission
        m.wave, m.stats.zapped, m.stats.best_wave = 2, 4, 2  # something happened
        m.pool, m.wallets["x"] = 7, 3
        await service.reset_world()
        recs = rounds.read(settings.abs_state_dir / "rounds.jsonl")
        assert len(recs) == 1
        rec = recs[0]
        assert rec["mission"] == "siege" and rec["seed"] == 11 and rec["room"] == "lab"
        assert rec["round"] == 1 and rec["zapped"] == 4 and rec["best_wave"] == 2
        assert rec["seats"] == 1 and rec["names"] == ["Ada"]
        assert rec["pool"] == 7 and rec["wallets"] == 3 and "duration_s" in rec
        assert rec["ts"].endswith("+00:00")
        await service.reset_world()  # a fresh room: nothing played, nothing written
        assert len(rounds.read(settings.abs_state_dir / "rounds.jsonl")) == 1
    finally:
        await service.stop()
