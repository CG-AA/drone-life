"""Mission registry. Add your mission class here and select it with MISSION=<name>."""

from ..mission import Mission
from .canyon import CanyonMission
from .delivery import DeliveryMission
from .forge import ForgeMission
from .freefly import FreeFlyMission
from .rampart import RampartMission

MISSIONS: dict[str, type[Mission]] = {
    CanyonMission.name: CanyonMission,
    DeliveryMission.name: DeliveryMission,
    ForgeMission.name: ForgeMission,
    FreeFlyMission.name: FreeFlyMission,
    RampartMission.name: RampartMission,
}
