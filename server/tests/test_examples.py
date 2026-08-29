"""The example scripts the server hands out or spawns must exist and parse."""

import ast

from app.api.routes_public import TEMPLATES
from app.config import Settings
from app.service import BOT_SCRIPTS, EXAMPLES_DIR, DroneLifeService


def test_every_bot_script_exists_on_disk_and_parses():
    for script in BOT_SCRIPTS:
        path = EXAMPLES_DIR / f"{script}.py"
        assert path.is_file(), script
        ast.parse(path.read_text())


def test_every_template_exists_on_disk_and_parses():
    for filename in TEMPLATES.values():
        path = EXAMPLES_DIR / filename
        assert path.is_file(), filename
        ast.parse(path.read_text())


def test_siege_bots_are_offered_as_templates():
    assert {"bot_siege", "bot_tower"} <= set(TEMPLATES)


def test_worked_answers_parse_and_stay_hidden_until_the_wrap():
    answers = sorted((EXAMPLES_DIR / "answers").glob("*.py"))
    assert {p.stem for p in answers} >= {"quest_route", "quest_predict", "quest_compute"}
    for path in answers:
        ast.parse(path.read_text())
        assert path.name not in TEMPLATES.values(), "not in the template menu"
        assert f"answers/{path.stem}" not in BOT_SCRIPTS, "not spawnable by default"


def test_extra_bot_scripts_widen_the_allowlist_on_a_dev_server(tmp_path):
    svc = DroneLifeService(Settings(state_dir=tmp_path, room_code="x", admin_token="y",
                                    extra_bot_scripts="answers/quest_route, answers/quest_compute"))
    assert svc.bot_scripts == BOT_SCRIPTS | {"answers/quest_route", "answers/quest_compute"}
    assert (EXAMPLES_DIR / "answers/quest_route.py").is_file()
