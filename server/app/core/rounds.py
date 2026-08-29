"""rounds.jsonl: one line per siege round, appended at reset — the numbers
the balance session works from (docs/SESSION_PLAN.md §9). Append-only,
one JSON object per line; a corrupt line is skipped on read, never fatal."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def append(path: Path, record: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError):
        log.exception("rounds.jsonl append failed")


def read(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError:
        log.exception("rounds.jsonl read failed")
        return []
    out: list[dict] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            log.warning("rounds.jsonl: skipping a corrupt line")
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out
