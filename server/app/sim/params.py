"""Physics + world constants. One place to tune the feel of the whole game."""

TICK_HZ = 20
DT = 1.0 / TICK_HZ
MISSION_HZ = 10  # engine + WS run every 2nd sim tick

# speeds / accelerations (m/s, m/s^2)
V_XY_MAX = 10.0
V_UP_MAX = 4.0
V_DOWN_MAX = 2.5
V_DOWN_FINAL = 1.0  # descent speed below FINAL_ALT (pretty landings)
FINAL_ALT = 3.0
A_XY_MAX = 4.0
A_Z_MAX = 2.5
YAW_RATE_MAX = 2.1  # rad/s (~120 deg/s), cosmetic

ARRIVE_RADIUS = 0.5  # m, position target reached -> hold
VEL_SP_TIMEOUT = 3.0  # s without a fresh velocity setpoint -> brake to hover

# arena (NED: x = north, y = east, z = down; altitude = -z)
ARENA_HALF = 100.0  # x, y in [-100, 100]
ALT_MAX = 60.0
RTL_ALT = 15.0  # RTL cruise altitude (climb first if below)

DISARM_DELAY = 3.0  # s after touchdown before auto-disarm
ORPHAN_GRACE = 10.0  # s after script disconnect before auto-RTL
CRASH_FALL_SPEED = 8.0  # m/s drop when force-disarmed mid-air
CRASH_DOWN_TIME = 5.0  # s shown crashed on the ground before respawn

# spawn pads: a row along the south edge
SPAWN_X = -90.0
SPAWN_Y0 = -76.0
SPAWN_SPACING = 8.0

BOUNDS_WARN_INTERVAL = 5.0  # s between "clamped at wall" STATUSTEXTs

# ArduCopter custom_mode numbers we speak
MODE_STABILIZE = 0
MODE_GUIDED = 4
MODE_LOITER = 5
MODE_RTL = 6
MODE_LAND = 9
MODE_NAMES = {
    MODE_STABILIZE: "STABILIZE",
    MODE_GUIDED: "GUIDED",
    MODE_LOITER: "LOITER",
    MODE_RTL: "RTL",
    MODE_LAND: "LAND",
}
