"""speed_scale: the one mission-driven physics knob, scaling the horizontal
and climb caps and nothing else."""

from app.sim import params as P
from app.sim.drone import DroneSim, Flight
from app.sim.world import World


def flying(scale=1.0) -> DroneSim:
    d = DroneSim(id="d0", student_id="s0", name="A", sysid=1, spawn_n=0, spawn_e=0)
    d.flight, d.armed, d.mode, d.speed_scale = Flight.FLY, True, P.MODE_GUIDED, scale
    d.d = -10.0
    return d


def test_velocity_setpoints_clamp_at_the_scaled_caps():
    d = flying()
    d.vel_sp, d.vel_sp_time = (30.0, 0.0, -30.0), 0.0
    vn, _ve, vd = d._desired_velocity(0.0)
    assert (vn, vd) == (P.V_XY_MAX, -P.V_UP_MAX)
    d = flying(1.5)
    d.vel_sp, d.vel_sp_time = (30.0, 0.0, -30.0), 0.0
    vn, _ve, vd = d._desired_velocity(0.0)
    assert (vn, vd) == (1.5 * P.V_XY_MAX, -1.5 * P.V_UP_MAX)
    d.vel_sp = (0.0, 0.0, 30.0)  # descent is not for sale
    assert d._desired_velocity(0.0)[2] == P.V_DOWN_MAX


def test_gotos_cruise_at_the_scaled_cap():
    d = flying()
    d.tn, d.te, d.td = 500.0, 0.0, d.d
    assert d._desired_velocity(0.0)[0] == P.V_XY_MAX
    d.speed_scale = 1.25
    assert d._desired_velocity(0.0)[0] == 1.25 * P.V_XY_MAX


def test_a_world_reset_restores_stock_but_a_pad_reset_keeps_the_upgrade():
    world = World()
    d = world.spawn("d0", "s0", "A", 0)
    d.speed_scale = 1.5
    d.reset_to_pad()
    assert d.speed_scale == 1.5, "self-service reset: the pilot paid for it"
    world.reset()
    assert d.speed_scale == 1.0, "round reset: everyone flies stock again"
