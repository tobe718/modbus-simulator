"""Slave configuration models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class FramerMode(str, Enum):
    """Modbus framer selection (global)."""

    TCP = "tcp"
    RTU_OVER_TCP = "rtu_over_tcp"

    @property
    def display_name(self) -> str:
        return {
            FramerMode.TCP: "Modbus TCP",
            FramerMode.RTU_OVER_TCP: "Modbus RTU over TCP",
        }[self]


class RegisterType(str, Enum):
    """Four Modbus register areas."""

    COIL = "coil"             # 0xxxx, read/write bit
    DISCRETE = "discrete"     # 1xxxx, read-only bit
    INPUT = "input"           # 3xxxx, read-only 16-bit
    HOLDING = "holding"       # 4xxxx, read/write 16-bit

    @property
    def display_name(self) -> str:
        return {
            RegisterType.COIL: "Coils (0xxxx)",
            RegisterType.DISCRETE: "Discrete Inputs (1xxxx)",
            RegisterType.INPUT: "Input Registers (3xxxx)",
            RegisterType.HOLDING: "Holding Registers (4xxxx)",
        }[self]


@dataclass
class SlaveConfig:
    """Per-slave configuration."""

    unit_id: int = 1
    port: int = 5020
    coil_count: int = 100
    discrete_count: int = 100
    input_count: int = 100
    holding_count: int = 100
    delay_ms: int = 0
    coil_values: List[int] = field(default_factory=list)
    discrete_values: List[int] = field(default_factory=list)
    input_values: List[int] = field(default_factory=list)
    holding_values: List[int] = field(default_factory=list)

    def ensure_values(self) -> None:
        """Resize value lists to match configured counts (pad zeros / truncate)."""
        self.coil_values = _resize(self.coil_values, self.coil_count)
        self.discrete_values = _resize(self.discrete_values, self.discrete_count)
        self.input_values = _resize(self.input_values, self.input_count)
        self.holding_values = _resize(self.holding_values, self.holding_count)


def _resize(values: List[int], count: int) -> List[int]:
    if len(values) == count:
        return list(values)
    if len(values) > count:
        return list(values[:count])
    return list(values) + [0] * (count - len(values))
