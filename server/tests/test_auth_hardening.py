"""Secret compares and abuse limits: the auth helpers and the routes using them."""

import httpx
import pytest

from app.api.auth import RateLimiter, StrikeGuard, constant_time_eq
from app.core.registry import Registry
from tests.conftest import make_settings, running_app


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


def test_constant_time_eq_survives_lone_surrogates():
    """JSON can carry "\\ud800", which plain .encode() refuses to encode."""
    lone = "\ud800"
    assert not constant_time_eq(lone, "test-room")
    assert constant_time_eq(lone, lone)


async def test_join_rejects_lone_surrogate_room_code(tmp_path):
    """End to end: an unencodable room code is a wrong code, not a 500."""
    async with running_app(make_settings(tmp_path)) as app:
        client = await transport_client(app, "10.0.0.14")
        async with client:
            r = await client.post(
                "/api/v1/join",
                content=b'{"room_code": "\\ud800", "name": "Eve"}',
                headers={"content-type": "application/json"},
            )
            assert r.status_code == 403


def test_by_token_survives_unencodable_input(tmp_path):
    """Headers are ASCII on the wire, so this is defence in depth for by_token:
    a restored snapshot or a future caller must not crash the lookup."""
    registry = Registry(max_students=2, base_port=5760)
    student, _ = registry.join("Ada")
    assert registry.by_token("\ud800") is None
    assert registry.by_token(student.token) is student


class FakeClock:
    """An advanceable monotonic clock, so limiter tests never sleep."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_limiter_blocks_past_the_ceiling():
    limiter = RateLimiter(3, clock=FakeClock())
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock)
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    clock.advance(61)
    assert limiter.allow("a")


def test_limiter_keys_are_independent():
    limiter = RateLimiter(1, clock=FakeClock())
    assert limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")


def test_blocked_peeks_without_spending():
    limiter = RateLimiter(2, clock=FakeClock())
    assert not limiter.blocked("a")
    assert not limiter.blocked("a"), "peeking must not consume budget"
    limiter.allow("a")
    limiter.allow("a")
    assert limiter.blocked("a")


def test_blocked_clears_when_the_window_slides():
    clock = FakeClock()
    limiter = RateLimiter(1, clock=clock)
    limiter.allow("a")
    assert limiter.blocked("a")
    clock.advance(61)
    assert not limiter.blocked("a")


def test_limiter_sweeps_stale_keys():
    """Keys are client IPs — without the sweep the dict grows for the process's life."""
    clock = FakeClock()
    limiter = RateLimiter(5, clock=clock)
    limiter.allow("a")
    limiter.allow("b")
    clock.advance(61)
    limiter.allow("c")
    assert set(limiter.hits) == {"c"}


async def transport_client(app, ip):
    """A client whose requests carry a specific source IP (the limiter's key)."""
    transport = httpx.ASGITransport(app=app, client=(ip, 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_join_limit_is_per_ip(tmp_path):
    """One student burning their budget must not lock out the rest of the class."""
    settings = make_settings(tmp_path, join_rate_limit_per_minute=3, join_strikes=0)
    async with running_app(settings) as app:
        alice = await transport_client(app, "10.0.0.7")
        bob = await transport_client(app, "10.0.0.8")
        async with alice, bob:
            guess = {"room_code": "wrong", "name": "Ann"}
            for _ in range(3):
                assert (await alice.post("/api/v1/join", json=guess)).status_code == 403
            spent = await alice.post("/api/v1/join", json=guess)
            assert spent.status_code == 429
            assert spent.json()["error"]["code"] == "rate"
            # Bob still has his own budget
            assert (await bob.post("/api/v1/join", json=guess)).status_code == 403


async def test_world_correct_code_never_spends_budget(tmp_path):
    """The projector's own polling must not throttle itself."""
    settings = make_settings(tmp_path, join_rate_limit_per_minute=2)
    async with running_app(settings) as app:
        client = await transport_client(app, "10.0.0.9")
        async with client:
            for _ in range(5):
                assert (await client.get("/api/v1/world?code=test-room")).status_code == 200


async def test_world_stops_answering_once_guessing_exhausts_the_budget(tmp_path):
    """/world was an unlimited room-code oracle.

    Spending budget on wrong codes alone would not fix that: an attacker whose
    budget is gone still learns 'wrong' from a 429 and 'right' from a 200. Once
    the ceiling is hit every answer must look the same.
    """
    settings = make_settings(tmp_path, join_rate_limit_per_minute=2)
    async with running_app(settings) as app:
        client = await transport_client(app, "10.0.0.9")
        async with client:
            for _ in range(2):
                assert (await client.get("/api/v1/world?code=nope")).status_code == 403
            assert (await client.get("/api/v1/world?code=nope")).status_code == 429
            # the correct code is refused identically while the ceiling holds
            assert (await client.get("/api/v1/world?code=test-room")).status_code == 429


async def test_world_accepts_code_with_whitespace(tmp_path):
    async with running_app(make_settings(tmp_path)) as app:
        client = await transport_client(app, "10.0.0.10")
        async with client:
            r = await client.get("/api/v1/world", params={"code": " test-room "})
            assert r.status_code == 200


async def test_submit_is_capped_per_student(tmp_path):
    """Broken syntax never reaches podman, so this stays hermetic."""
    settings = make_settings(tmp_path, submit_rate_limit_per_minute=2)
    async with running_app(settings) as app:
        client = await transport_client(app, "10.0.0.11")
        async with client:
            joined = await client.post(
                "/api/v1/join", json={"room_code": "test-room", "name": "Ada"}
            )
            headers = {"Authorization": f"Bearer {joined.json()['token']}"}
            body = {"code": "def broken(:"}
            for _ in range(2):
                r = await client.post("/api/v1/submit", json=body, headers=headers)
                assert r.status_code == 400
            capped = await client.post("/api/v1/submit", json=body, headers=headers)
            assert capped.status_code == 429
            assert capped.json()["error"]["code"] == "rate"


@pytest.mark.parametrize("token", ["", "bogus"])
async def test_submit_requires_a_real_token(tmp_path, token):
    async with running_app(make_settings(tmp_path)) as app:
        client = await transport_client(app, "10.0.0.12")
        async with client:
            r = await client.post(
                "/api/v1/submit",
                json={"code": "print(1)"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 401


async def test_admin_rejects_wrong_token(tmp_path):
    async with running_app(make_settings(tmp_path)) as app:
        client = await transport_client(app, "10.0.0.13")
        async with client:
            r = await client.get("/api/v1/admin/students", headers={"X-Admin-Token": "nope"})
            assert r.status_code == 403


# ---------------------------------------------------------------- strikes

def test_strikes_lock_after_the_ceiling_and_expire():
    clock = FakeClock()
    guard = StrikeGuard(3, lockout_s=600, clock=clock)
    guard.strike("a")
    guard.strike("a")
    assert not guard.blocked("a")
    guard.strike("a")
    assert guard.blocked("a") and not guard.blocked("b")
    clock.advance(601)
    assert not guard.blocked("a")  # lockout served, slate clean


def test_strikes_zero_lockout_holds_until_restart():
    clock = FakeClock()
    guard = StrikeGuard(1, lockout_s=0, clock=clock)
    guard.strike("a")
    clock.advance(10 ** 6)
    assert guard.blocked("a")
    assert guard.unlock_all() == 1 and not guard.blocked("a")


def test_a_correct_code_clears_earlier_typos():
    guard = StrikeGuard(3, lockout_s=600, clock=FakeClock())
    guard.strike("a")
    guard.strike("a")
    guard.clear("a")
    guard.strike("a")
    guard.strike("a")
    assert not guard.blocked("a")


async def test_three_wrong_codes_lock_the_address_out_everywhere(tmp_path):
    """After the third wrong code the address is refused on /join, /world and
    the viewer socket alike — with the correct code too (no oracle) — while
    another address is unaffected, and the admin can lift it."""
    settings = make_settings(tmp_path, join_strikes=3)
    async with running_app(settings) as app:
        mallory = await transport_client(app, "10.0.0.66")
        alice = await transport_client(app, "10.0.0.7")
        async with mallory, alice:
            guess = {"room_code": "wrong", "name": "M"}
            for _ in range(3):
                assert (await mallory.post("/api/v1/join", json=guess)).status_code == 403
            right = {"room_code": "test-room", "name": "M"}
            locked = await mallory.post("/api/v1/join", json=right)
            assert locked.status_code == 429 and locked.json()["error"]["code"] == "locked"
            assert (await mallory.get("/api/v1/world?code=test-room")).status_code == 429
            ok = await alice.post("/api/v1/join", json={"room_code": "test-room", "name": "Ann"})
            assert ok.status_code == 200
            headers = {"X-Admin-Token": settings.admin_token}
            lifted = await alice.post("/api/v1/admin/unlock", headers=headers)
            assert lifted.json() == {"unlocked": 1}
            assert (await mallory.get("/api/v1/world?code=test-room")).status_code == 200


async def test_two_typos_then_the_right_code_is_not_a_lockout(tmp_path):
    settings = make_settings(tmp_path, join_strikes=3)
    async with running_app(settings) as app:
        client = await transport_client(app, "10.0.0.8")
        async with client:
            async def join(code: str) -> int:
                return (await client.post("/api/v1/join",
                                          json={"room_code": code, "name": "K"})).status_code
            assert [await join(c) for c in ("990045a", "99004a6")] == [403, 403]
            assert await join("test-room") == 200
            assert [await join(c) for c in ("x", "y")] == [403, 403]
            assert await join("test-room") == 200
