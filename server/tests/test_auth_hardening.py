"""Secret compares and abuse limits: the auth helpers and the routes using them."""

from app.api.auth import constant_time_eq


def test_constant_time_eq_matches():
    assert constant_time_eq("test-room", "test-room")


def test_constant_time_eq_rejects_different():
    assert not constant_time_eq("test-room", "other-room")
    assert not constant_time_eq("", "test-room")
    assert not constant_time_eq("test-room", "")


def test_constant_time_eq_survives_non_ascii():
    """compare_digest raises on non-ASCII str — a pasted 'clé' must 403, not 500."""
    assert not constant_time_eq("clé", "test-room")
    assert constant_time_eq("clé", "clé")
