"""The balance tool's pure parts: the bot spec and the table. The rounds
themselves are `make balance` (minutes of wall clock), not a test."""

import pytest

from tools.balance import COLUMNS, parse_bots, table


def test_bot_spec_parses_and_rejects_nonsense():
    assert parse_bots("6:bot_siege 2:bot_tower") == [(6, "bot_siege"), (2, "bot_tower")]
    assert parse_bots(" 1:answers/quest_route ") == [(1, "answers/quest_route")]
    for bad in ("", "bot_siege", "0:bot_siege", "x:bot_siege", "3:"):
        with pytest.raises(ValueError, match=r"bot spec|no bots"):
            parse_bots(bad)


def test_table_lines_up_and_marks_missing_numbers():
    recs = [{"run": 1, "seed": 3, "best_wave": 7, "kills": 41, "first_tower_s": None},
            {"run": 2, "seed": 4, "best_wave": 12, "kills": 130, "first_tower_s": 38.5}]
    out = table(recs).splitlines()
    assert out[0].split() == list(COLUMNS)
    assert len({len(line) for line in out}) == 1, "every line the same width"
    assert out[2].split()[0] == "1" and out[3].split()[3] == "12"
    assert "-" in out[2].split() and "38.5" in out[3].split()
    assert table([]).splitlines()[0].split() == list(COLUMNS)
