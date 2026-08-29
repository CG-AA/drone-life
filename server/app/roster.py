"""Carry the roster — not the score — from the small rooms into the big one.

    set -a; . /etc/drone-life.env; . /etc/drone-life.d/main.env; set +a
    uv run python -m app.roster merge state/r1 state/r2 state/r3 state/r4 state/r5

Reads each room's snapshot.json, re-seats every pilot in the destination's
slot space (the destination is whatever Settings the environment describes:
STATE_DIR, MAVLINK_BASE_PORT, MAX_STUDENTS) and writes the destination
snapshot with the score zeroed. Tokens are kept, so a page that joined a small
room reconnects to the big one without re-joining — the same origin serves
every room, and the page already re-reads its id and name from /status
(docs/ROOMS.md). Bans are not in the snapshot and do not carry.

Run it with every room *stopped*: a stop flushes the small rooms' snapshots,
and a running destination would overwrite the merged file within 30 s.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .config import Settings
from .core import snapshot
from .core.registry import NAME_MAX, Student, _norm


class RosterError(Exception):
    pass


def merge_rosters(sources: list[tuple[str, list[dict]]], base_port: int,
                  max_students: int) -> tuple[list[dict], list[str]]:
    """Seat every pilot from `sources` (label, snapshot rows) in order, from
    slot 0. Returns the rows to snapshot plus human notes (renames, skips).

    Slot is the pivot of a pilot's identity — id, sysid, MAVLink port, pad and
    drone are all derived from it — so everyone is re-slotted, and every row is
    rebuilt through `Student` so it carries exactly the fields `restore()`
    accepts (an extra key would drop the pilot on boot)."""
    rows: list[dict] = []
    notes: list[str] = []
    seen: set[str] = set()
    for label, source in sources:
        for row in source:
            token = row.get("token")
            name = str(row.get("name", "")).strip()[:NAME_MAX]
            if not token or not name:
                notes.append(f"{label}: skipped a row with no name or token: {row!r}")
                continue
            if _norm(name) in seen:
                # two rooms had a Sam (or one Sam wandered): both keep a seat,
                # the later one under a name the room can tell apart
                base, n = name, 2
                while _norm(name) in seen:
                    suffix = f" {n}"
                    name = base[:NAME_MAX - len(suffix)] + suffix
                    n += 1
                notes.append(f"{label}: {base!r} was already seated — renamed to {name!r}")
            seen.add(_norm(name))
            slot = len(rows)
            rows.append(asdict(Student(id=f"s{slot}", name=name, token=str(token), slot=slot,
                                       sysid=slot + 1, port=base_port + slot,
                                       ip=str(row.get("ip", "")))))
    if len(rows) > max_students:
        over = ", ".join(r["name"] for r in rows[max_students:])
        raise RosterError(f"{len(rows)} pilots but MAX_STUDENTS={max_students} — no seat for: "
                          f"{over}. Raise MAX_STUDENTS for the big room, or kick before merging")
    return rows, notes


def load_room(path: Path) -> tuple[str, list[dict]]:
    """A room's state dir (or its snapshot.json) → (label, rows). Missing is an
    error: a typo must not silently merge four rooms instead of five."""
    file = path / "snapshot.json" if path.is_dir() else path
    if not file.is_file():
        raise RosterError(f"{file}: no snapshot — is that the room's STATE_DIR?")
    data = snapshot.load(file)
    if data is None:
        raise RosterError(f"{file}: unreadable snapshot")
    label = file.parent.name
    return label, list(data.get("students", []))


def destination_running(port: int) -> bool:
    from .preflight import server_running  # lazy: preflight pulls in podman probes
    return server_running(f"http://127.0.0.1:{port}/healthz")


def merge(args: argparse.Namespace, settings: Settings) -> int:
    dest = settings.abs_state_dir / "snapshot.json"
    port = int(os.environ.get("PORT", "8000"))
    if not args.force and destination_running(port):
        print(f"refusing: a server answers on :{port} and would overwrite {dest} within 30 s "
              "— stop it first (or --force if that port is not this room)", file=sys.stderr)
        return 1
    sources: list[tuple[str, list[dict]]] = []
    if not args.fresh:
        existing = snapshot.load(dest) if dest.is_file() else None
        if existing:
            sources.append((f"{settings.room_id} (already here)",
                            list(existing.get("students", []))))
    sources.extend(load_room(Path(p)) for p in args.rooms)
    rows, notes = merge_rosters(sources, settings.mavlink_base_port, settings.max_students)
    for note in notes:
        print(f"note: {note}")
    for r in rows:
        print(f"  {r['id']:<4} {r['name']:<24} sysid {r['sysid']:<3} port {r['port']}")
    last = settings.mavlink_base_port + settings.max_students - 1
    print(f"{len(rows)} pilots seated of {settings.max_students} "
          f"(MAVLink {settings.mavlink_base_port}-{last})")
    if args.dry_run:
        print(f"dry run — {dest} untouched")
        return 0
    snapshot.save(dest, {"students": rows, "score": 0, "scores": {}})
    print(f"wrote {dest} — start the big room; pages reconnect on their stored tokens")
    return 0


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.roster", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge", help="seat the given rooms' pilots in this room's snapshot")
    m.add_argument("rooms", nargs="+", help="each room's STATE_DIR (or its snapshot.json)")
    m.add_argument("--dry-run", action="store_true", help="show the seating, write nothing")
    m.add_argument("--fresh", action="store_true",
                   help="drop whoever is already in this room's snapshot")
    m.add_argument("--force", action="store_true",
                   help="write even if a server answers on this room's PORT")
    args = parser.parse_args(argv)
    try:
        return merge(args, settings or Settings())
    except RosterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
