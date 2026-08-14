"""No objectives, no scoring — just the shared sky.

Exists to prove the mission seam stays honest: if freefly works with zero
special-casing anywhere, new missions will too.
"""

from ..mission import Mission


class FreeFlyMission(Mission):
    name = "freefly"
