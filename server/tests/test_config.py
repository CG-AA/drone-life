"""The startup guard: the server must refuse placeholder access-control secrets."""

import pytest

from app.config import check_secrets
from app.main import create_app
from tests.conftest import make_settings


def test_real_secrets_pass(tmp_path):
    assert check_secrets(make_settings(tmp_path)) is None


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"room_code": "classroom"}, "ROOM_CODE"),
        ({"admin_token": "change-me"}, "ADMIN_TOKEN"),
        ({"room_code": ""}, "ROOM_CODE"),
        ({"admin_token": "   "}, "ADMIN_TOKEN"),
    ],
)
def test_placeholder_and_empty_secrets_refused(tmp_path, overrides, expected):
    refusal = check_secrets(make_settings(tmp_path, **overrides))
    assert refusal is not None and expected in refusal


def test_secrets_are_stripped_so_the_env_file_cannot_lock_the_room(tmp_path):
    """systemd's EnvironmentFile does not trim, and every compare strips what
    the browser sent — `ROOM_CODE=abc ` would 403 the whole class while the
    guard and preflight both saw a real value."""
    settings = make_settings(tmp_path, room_code="abc \t", admin_token=" tok\n")
    assert settings.room_code == "abc" and settings.admin_token == "tok"
    assert check_secrets(settings) is None


def test_a_whitespace_only_secret_is_empty_not_real(tmp_path):
    refusal = check_secrets(make_settings(tmp_path, room_code="  \t "))
    assert refusal is not None and "ROOM_CODE" in refusal


def test_both_bad_names_both(tmp_path):
    refusal = check_secrets(make_settings(tmp_path, room_code="classroom", admin_token="change-me"))
    assert refusal is not None and "ROOM_CODE" in refusal and "ADMIN_TOKEN" in refusal


def test_escape_hatch_allows_defaults(tmp_path):
    settings = make_settings(
        tmp_path, room_code="classroom", admin_token="change-me", allow_default_secrets=True
    )
    assert check_secrets(settings) is None


async def test_lifespan_refuses_default_secrets(tmp_path):
    """Uvicorn aborts startup when the lifespan raises — that is the loud refusal."""
    app = create_app(make_settings(tmp_path, room_code="classroom"))
    with pytest.raises(RuntimeError, match="ROOM_CODE"):
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover — bring-up must not get this far


async def test_lifespan_starts_with_real_secrets(tmp_path):
    app = create_app(make_settings(tmp_path))
    async with app.router.lifespan_context(app):
        assert app.state.service.world is not None


@pytest.mark.parametrize("bad", ["", "Room 1", "r1/", "../main", "R1"])
def test_room_id_must_be_a_plain_name(tmp_path, bad):
    """ROOM_ID becomes a state path segment, a podman label and a systemd
    instance name — anything that needs quoting in one of them is refused."""
    with pytest.raises(ValueError, match="ROOM_ID"):
        make_settings(tmp_path, room_id=bad)


def test_rooms_parses_a_comma_list(tmp_path):
    assert make_settings(tmp_path, rooms=" r1, r2,,r3 ").room_list == ["r1", "r2", "r3"]
    assert make_settings(tmp_path).room_list == []
