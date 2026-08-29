"""The roster merge: every pilot from the small rooms gets a seat in the big
one — re-slotted, same token, no score — and a merged snapshot boots."""

from __future__ import annotations

import json

import httpx
import pytest

from app import roster
from app.core.registry import NAME_MAX
from app.roster import RosterError, merge_rosters

from .conftest import find_port_base, make_settings, running_app


def row(name, slot=0, token=None, **over):
    return {"id": f"s{slot}", "name": name, "token": token or f"tok-{name}", "slot": slot,
            "sysid": slot + 1, "port": 5760 + slot, "ip": "10.0.0.9", **over}


def test_everyone_is_reseated_in_order_and_keeps_their_token():
    rows, notes = merge_rosters([("r1", [row("Ann", 0), row("Bo", 3)]),
                                 ("r2", [row("Cy", 0)])], base_port=6000, max_students=64)
    assert notes == []
    assert [(r["id"], r["name"], r["slot"], r["sysid"], r["port"]) for r in rows] == [
        ("s0", "Ann", 0, 1, 6000), ("s1", "Bo", 1, 2, 6001), ("s2", "Cy", 2, 3, 6002)]
    assert [r["token"] for r in rows] == ["tok-Ann", "tok-Bo", "tok-Cy"]
    assert rows[0]["ip"] == "10.0.0.9"
    # exactly the Student fields: an extra key would drop the pilot on restore()
    assert set(rows[0]) == {"id", "name", "token", "slot", "sysid", "port", "ip"}


def test_a_name_seated_twice_gets_a_number_and_stays_within_the_cap():
    long = "x" * NAME_MAX
    rows, notes = merge_rosters([("r1", [row("Sam"), row(long, 1)]),
                                 ("r2", [row("sam "), row(long, 1, token="t2")]),
                                 ("r3", [row("SAM")])], base_port=5760, max_students=10)
    assert [r["name"] for r in rows] == ["Sam", long, "sam 2", long[:NAME_MAX - 2] + " 2", "SAM 3"]
    assert all(len(r["name"]) <= NAME_MAX for r in rows)
    assert len(notes) == 3 and "r2: 'sam'" in notes[0] and "renamed to 'sam 2'" in notes[0]


def test_more_pilots_than_seats_is_an_error_that_names_them():
    with pytest.raises(RosterError, match="3 pilots but MAX_STUDENTS=2 — no seat for: Cy"):
        merge_rosters([("r1", [row("Ann"), row("Bo", 1), row("Cy", 2)])], 5760, 2)


def test_rows_without_a_name_or_token_are_skipped_with_a_note():
    rows, notes = merge_rosters([("r1", [row("Ann"), {"id": "s1", "name": "", "token": "t"},
                                         {"name": "Bo"}])], 5760, 8)
    assert [r["name"] for r in rows] == ["Ann"]
    assert len(notes) == 2 and all("skipped" in n for n in notes)


def snapshot_of(path, rows, score=17):
    path.mkdir(parents=True, exist_ok=True)
    (path / "snapshot.json").write_text(json.dumps(
        {"students": rows, "score": score, "scores": {r["id"]: 3 for r in rows}}))


def test_cli_merges_rooms_into_this_rooms_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(roster, "destination_running", lambda port: False)
    dest = make_settings(tmp_path, max_students=8, mavlink_base_port=6100)
    snapshot_of(dest.abs_state_dir, [row("Host")])
    snapshot_of(tmp_path / "r1", [row("Ann"), row("Bo", 1)])
    snapshot_of(tmp_path / "r2", [row("Cy")])

    assert roster.main(["merge", "--dry-run", str(tmp_path / "r1"), str(tmp_path / "r2")],
                       settings=dest) == 0
    out = capsys.readouterr().out
    assert "4 pilots seated of 8" in out and "untouched" in out
    assert json.loads((dest.abs_state_dir / "snapshot.json").read_text())["score"] == 17

    assert roster.main(["merge", str(tmp_path / "r1"), str(tmp_path / "r2")], settings=dest) == 0
    data = json.loads((dest.abs_state_dir / "snapshot.json").read_text())
    assert data["score"] == 0 and data["scores"] == {}
    assert [(r["name"], r["port"]) for r in data["students"]] == [
        ("Host", 6100), ("Ann", 6101), ("Bo", 6102), ("Cy", 6103)]

    # --fresh: whoever was in the big room already does not come along
    assert roster.main(["merge", "--fresh", str(tmp_path / "r2")], settings=dest) == 0
    data = json.loads((dest.abs_state_dir / "snapshot.json").read_text())
    assert [r["name"] for r in data["students"]] == ["Cy"]


def test_cli_refuses_a_missing_room_and_a_running_destination(tmp_path, monkeypatch, capsys):
    dest = make_settings(tmp_path)
    monkeypatch.setattr(roster, "destination_running", lambda port: False)
    assert roster.main(["merge", str(tmp_path / "nope")], settings=dest) == 1
    assert "no snapshot" in capsys.readouterr().err
    monkeypatch.setattr(roster, "destination_running", lambda port: True)
    snapshot_of(tmp_path / "r1", [row("Ann")])
    assert roster.main(["merge", str(tmp_path / "r1")], settings=dest) == 1
    assert "refusing" in capsys.readouterr().err


async def test_a_merged_64_seat_snapshot_boots_and_the_old_tokens_still_work(tmp_path, monkeypatch):
    """The point of carrying tokens: a page that joined room 3 opens the big
    room and is simply in — under a new id, which /status now tells it."""
    monkeypatch.setattr(roster, "destination_running", lambda port: False)
    big = make_settings(tmp_path, max_students=64, mavlink_base_port=find_port_base(64))
    rooms = []
    for i in range(4):
        rows = [row(f"P{i}-{j}", j, token=f"tok-{i}-{j}") for j in range(16)]
        snapshot_of(tmp_path / f"r{i}", rows)
        rooms.append(str(tmp_path / f"r{i}"))
    assert roster.main(["merge", *rooms], settings=big) == 0

    async with running_app(big) as app:
        service = app.state.service
        assert len(service.registry.students) == 64 and len(service.world.drones) == 64
        assert service.engine.score == 0
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/api/v1/status", headers={"Authorization": "Bearer tok-3-5"})
            assert r.status_code == 200
            assert r.json()["student_id"] == "s53" and r.json()["name"] == "P3-5"
            assert (await c.get("/healthz")).json()["students"] == 64
