"""电路仿真内核：解析 / MNA / 直流 / 瞬态。"""

from .dc import DCOperatingPoint, dc_operating_point
from .errors import ErrorCode
from .exceptions import CircuitError
from .model import Circuit, Component, ComponentKind
from .parser import parse_netlist
from .transient import MAX_STEPS, METHOD, TransientResult, transient_analysis

__all__ = [
    "Circuit",
    "Component",
    "ComponentKind",
    "CircuitError",
    "ErrorCode",
    "DCOperatingPoint",
    "dc_operating_point",
    "MAX_STEPS",
    "METHOD",
    "TransientResult",
    "transient_analysis",
    "parse_netlist",
]
