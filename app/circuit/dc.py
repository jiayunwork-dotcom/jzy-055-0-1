"""直流工作点分析。

处理规则（与瞬态伴随模型共享 model.py 里的同一套方向/初值语义）：
    * 电阻：贡献电导 1/R。
    * 电容：直流稳态下视为开路，不盖章。其初压 ic 是瞬态初始条件，
      不改变直流稳态解，含义与瞬态中 v_C(0) 完全一致。
    * 电感：直流稳态下视为短路，即一条 0V 的理想电压源支路，
      支路电流就是直流电感电流。其初流 ic 是瞬态初始条件。
    * 独立电流源：向 p 节点注入 value。
    * 独立电压源：扩出一个支路电流未知量。

输出约定：支路电流（含电压源、电感）以“流入元件 p 端”为正方向
（SPICE 约定），所以电源向电路供电时报告的电流为负值。
"""

from __future__ import annotations

from dataclasses import dataclass

from .mna import MNABuilder, solve_linear
from .model import Circuit, ComponentKind


@dataclass(frozen=True)
class DCOperatingPoint:
    node_voltages: dict[str, float]      # 含地节点 "0": 0.0
    voltage_source_currents: dict[str, float]
    inductor_currents: dict[str, float]  # 附加输出：直流电感电流
    success: bool


def dc_operating_point(circuit: Circuit) -> DCOperatingPoint:
    """求直流工作点；矩阵奇异时抛 CircuitError(SINGULAR_MATRIX)。"""
    branch_names = [
        c.name
        for c in circuit.components
        if c.kind in (ComponentKind.VOLTAGE_SOURCE, ComponentKind.INDUCTOR)
    ]
    builder = MNABuilder(circuit, branch_names)

    for comp in circuit.components:
        if comp.kind is ComponentKind.RESISTOR:
            builder.stamp_conductance(comp.p, comp.n, 1.0 / comp.value)
        elif comp.kind is ComponentKind.CAPACITOR:
            # 直流开路：什么都不贡献。
            continue
        elif comp.kind is ComponentKind.INDUCTOR:
            # 直流短路：0V 电压源支路。盖章约定 j 流入第一参数端，
            # 而电感支路电流 j 定义为流入 p，故支路行要写成 V(n)-V(p)=0，
            # 即按 (n, p) 顺序盖章。
            builder.stamp_voltage_branch(comp.n, comp.p, comp.name, 0.0)
        elif comp.kind is ComponentKind.VOLTAGE_SOURCE:
            builder.stamp_voltage_branch(comp.p, comp.n, comp.name, comp.value)
        elif comp.kind is ComponentKind.CURRENT_SOURCE:
            builder.stamp_current_injection(comp.p, comp.n, comp.value)

    system = builder.build()
    x = solve_linear(system)

    # 节点电压（地钉死为 0）。
    voltages: dict[str, float] = {name: 0.0 for name in system.node_names}
    for name, idx in system.node_index.items():
        voltages[name] = float(x[idx])

    # 支路电流。MNA 中 j 的正方向为“流入元件 p 端”（SPICE 约定），
    # 电源向外供电时 j 为负。电压源电流直接报告 j；电感要报告的是
    # p->n 方向的物理电流（与初流 ic 同约定），它等于 -j，故取负号。
    vs_currents: dict[str, float] = {}
    inductor_currents: dict[str, float] = {}
    kind_by_name = {c.name: c.kind for c in circuit.components}
    for name, idx in system.branch_index.items():
        value = float(x[idx])
        if kind_by_name[name] is ComponentKind.INDUCTOR:
            inductor_currents[name] = -value
        else:
            vs_currents[name] = value

    return DCOperatingPoint(
        node_voltages=voltages,
        voltage_source_currents=vs_currents,
        inductor_currents=inductor_currents,
        success=True,
    )
