"""电路的核心数据模型：元件类型枚举与不可变的元件记录。

节点方向约定（直流与瞬态共用同一份定义，避免两套元件方程互相打架）：
    每个元件的两个节点按 p / n 给出。
    * 电压源 V：value = V(p) - V(n)；支路电流 i 以“从 p 极流入电源”为正。
    * 电流源 I：正的 value 表示向 p 节点注入电流、从 n 节点抽走。
    * 电容 C：端压定义为 v_C = V(p) - V(n)，初始条件 ic = v_C(0)。
    * 电感 L：电流定义为从 p 流向 n 的方向为正，初始条件 ic = i_L(0)。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ComponentKind(str, Enum):
    RESISTOR = "R"
    CAPACITOR = "C"
    INDUCTOR = "L"
    VOLTAGE_SOURCE = "V"
    CURRENT_SOURCE = "I"


# 网表里允许出现的类型写法，统一归一到枚举。
TYPE_ALIASES: dict[str, ComponentKind] = {
    "r": ComponentKind.RESISTOR,
    "resistor": ComponentKind.RESISTOR,
    "电阻": ComponentKind.RESISTOR,
    "c": ComponentKind.CAPACITOR,
    "capacitor": ComponentKind.CAPACITOR,
    "电容": ComponentKind.CAPACITOR,
    "l": ComponentKind.INDUCTOR,
    "inductor": ComponentKind.INDUCTOR,
    "电感": ComponentKind.INDUCTOR,
    "v": ComponentKind.VOLTAGE_SOURCE,
    "vsource": ComponentKind.VOLTAGE_SOURCE,
    "voltage_source": ComponentKind.VOLTAGE_SOURCE,
    "voltage-source": ComponentKind.VOLTAGE_SOURCE,
    "电压源": ComponentKind.VOLTAGE_SOURCE,
    "i": ComponentKind.CURRENT_SOURCE,
    "isource": ComponentKind.CURRENT_SOURCE,
    "current_source": ComponentKind.CURRENT_SOURCE,
    "current-source": ComponentKind.CURRENT_SOURCE,
    "电流源": ComponentKind.CURRENT_SOURCE,
}

# 接地参考节点允许的名字；解析时统一规范化为 "0"。
GROUND_ALIASES = frozenset({"0", "gnd", "GND", "Gnd"})
GROUND = "0"


@dataclass(frozen=True)
class Component:
    """一个二端元件。"""

    name: str
    kind: ComponentKind
    p: str                       # 正端 / 第一节点（已规范化）
    n: str                       # 负端 / 第二节点（已规范化）
    value: float                 # R:欧姆, C:法拉, L:亨利, V:伏特, I:安培
    ic: float = 0.0              # 初始条件：电容初压(伏特) / 电感初流(安培)

    @property
    def nodes(self) -> tuple[str, str]:
        return self.p, self.n


@dataclass(frozen=True)
class Circuit:
    """一张解析并校验完毕的网表。"""

    components: tuple[Component, ...]
    nodes: tuple[str, ...]       # 包含地节点 "0" 在内的全部节点，"0" 在首位

    def by_name(self) -> dict[str, Component]:
        return {c.name: c for c in self.components}
