"""Fake GPS origin so GLOBAL_POSITION_INT / global setpoints line up with tutorials.

Origin = ArduPilot SITL's default home (CMAC, Canberra): any coordinates students
google from SITL guides land in a sane spot in our arena frame.
"""

import math

ORIGIN_LAT = -35.363262
ORIGIN_LON = 149.165237
ORIGIN_ALT_AMSL = 584.0  # m

_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = _M_PER_DEG_LAT * math.cos(math.radians(ORIGIN_LAT))


def ned_to_geo(n: float, e: float, alt: float) -> tuple[float, float, float]:
    """(north m, east m, altitude m AGL) -> (lat deg, lon deg, alt m AMSL)."""
    return (
        ORIGIN_LAT + n / _M_PER_DEG_LAT,
        ORIGIN_LON + e / _M_PER_DEG_LON,
        ORIGIN_ALT_AMSL + alt,
    )


def geo_to_ned(lat: float, lon: float) -> tuple[float, float]:
    """(lat deg, lon deg) -> (north m, east m) relative to the fake origin."""
    return (
        (lat - ORIGIN_LAT) * _M_PER_DEG_LAT,
        (lon - ORIGIN_LON) * _M_PER_DEG_LON,
    )
