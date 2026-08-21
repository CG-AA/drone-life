"""Mission registry. Add your mission class here and select it with MISSION=<name>."""

from ..mission import Mission
from .canyon import CanyonMission
from .delivery import DeliveryMission
from .freefly import FreeFlyMission

MISSIONS: dict[str, type[Mission]] = {
    CanyonMission.name: CanyonMission,
    DeliveryMission.name: DeliveryMission,
    FreeFlyMission.name: FreeFlyMission,
}
