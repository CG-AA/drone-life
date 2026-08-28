"""The example scripts the server hands out or spawns must exist and parse."""

import ast

from app.api.routes_public import TEMPLATES
from app.service import BOT_SCRIPTS, EXAMPLES_DIR


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
