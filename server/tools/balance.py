"""make balance: N headless bot-only siege rounds on fixed seeds, each
written to rounds.jsonl by the reset that ends it, then a table.

    cd server && uv run python -m tools.balance --rounds 3 \\
        --bots "6:bot_siege 2:bot_tower 1:bot_repair 1:bot_scout" --seconds 300 --seed 3

Bots are real subprocesses sleeping on the wall clock, so the sim stays
throttled (real time): three 5-minute rounds are fifteen minutes. Every
round is a fresh service with sim_seed = seed + i, so a knob change can be
compared against the same waves. The numbers land in <state>/rounds.jsonl
(docs/SESSION_PLAN.md §9 says which knob each column speaks to).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import Settings
from app.core import rounds
from app.headless import NullHub, find_port_base
from app.service import DroneLifeService

COLUMNS = ("round", "seed", "seats", "best_wave", "kills", "zapped", "squished", "shot",
           "leaks", "towers", "ring_towers", "bells", "first_tower_s", "quests_solved",
           "quests_missed", "coins_spent", "score", "duration_s")


def parse_bots(spec: str) -> list[tuple[int, str]]:
    """'6:bot_siege 2:bot_tower' -> [(6, 'bot_siege'), (2, 'bot_tower')]."""
    out: list[tuple[int, str]] = []
    for word in spec.split():
        count, _, script = word.partition(":")
        if not script or not count.isdigit() or int(count) <= 0:
            raise ValueError(f"bad bot spec {word!r}: want COUNT:SCRIPT")
        out.append((int(count), script))
    if not out:
        raise ValueError("no bots: pass --bots 'COUNT:SCRIPT …'")
    return out


def table(records: list[dict]) -> str:
    """A fixed-width table of the columns every record carries (missing = -)."""
    rows = [[str(r.get(c, "-")) if r.get(c) is not None else "-" for c in COLUMNS]
            for r in records]
    widths = [max(len(c), *(len(row[i]) for row in rows)) if rows else len(c)
              for i, c in enumerate(COLUMNS)]
    line = "  ".join(c.rjust(w) for c, w in zip(COLUMNS, widths, strict=True))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(v.rjust(w) for v, w in zip(row, widths, strict=True)) for row in rows]
    return "\n".join(out)


async def run_round(i: int, args: argparse.Namespace, bots: list[tuple[int, str]],
                    state_dir: Path) -> None:
    seats = sum(n for n, _ in bots) + 2
    settings = Settings(
        mission="siege", sim_seed=args.seed + i, max_students=seats,
        mavlink_base_port=find_port_base(seats), state_dir=state_dir,
        room_code="balance", admin_token="balance-admin", room_id="balance",
        extra_bot_scripts=args.extra_bot_scripts,
    )
    service = DroneLifeService(settings)
    service.hub = NullHub()
    await service.start()
    try:
        for count, script in bots:
            started = await service.spawn_bots(count, script, "local")
            print(f"round {i + 1}: {len(started['started'])} x {script}", flush=True)
        await asyncio.sleep(args.seconds)
        hud = service.engine.hud()
        print(f"round {i + 1}: wave {hud.get('wave')} after {args.seconds}s — resetting",
              flush=True)
        await service.reset_world()  # the mission's round_end -> rounds.jsonl
    finally:
        await service.stop()


async def main_async(args: argparse.Namespace, state_dir: Path) -> int:
    bots = parse_bots(args.bots)
    path = state_dir / "rounds.jsonl"
    before = len(rounds.read(path))
    for i in range(args.rounds):
        await run_round(i, args, bots, state_dir)
    records = rounds.read(path)[before:]
    print()
    print(table(records))
    print(f"\n{len(records)} round(s) appended to {path}")
    return 0 if len(records) == args.rounds else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--bots", default="6:bot_siege 2:bot_tower")
    ap.add_argument("--seconds", type=float, default=300.0, help="per round, real time")
    ap.add_argument("--seed", type=int, default=3, help="sim_seed of round 1; +1 per round")
    ap.add_argument("--state-dir", default="state/balance")
    ap.add_argument("--extra-bot-scripts", default="",
                    help="comma list under examples/, e.g. answers/quest_route")
    args = ap.parse_args(argv)
    state_dir = Path(args.state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(main_async(args, state_dir))


if __name__ == "__main__":
    sys.exit(main())
