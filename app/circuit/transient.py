"""瞬态分析：隐式定步长后向欧拉（Backward Euler）。

集成方法固定为后向欧拉一种，全程不变更：

    电容伴随模型（端压 v_C = V(p)-V(n)，支路电流 p->n 为正）：
        i_C^{n+1} = C (v_C^{n+1} - v_C^n) / dt
                  = (C/dt) v_C^{n+1}  -  (C/dt) v_C^n
        => 等效电导 G_C = C/dt，并联历史电流源 (C/dt) v_C^n（注入 p）。

    电感伴随模型（电流 i_L 方向 p->n 为正，满足 v_L = L di/dt = V(p)-V(n)）：
        i_L^{n+1} = i_L^n + (dt/L)(V(p)-V(n))^{n+1}
        代入 p 节点 KCL（电导电流 + i_L = 注入）：
            ... + g_L(V(p)-V(n)) = 注入 - i_L^n
        => 等效电导 G_L = dt/L，并联历史电流源 i_L^n（从 p 抽走、向 n 注入）。

初始时刻 t=0 的状态由初始条件确定：电容换成值为 ic 的电压源、
电感换成值为 ic 的电流源，与其余元件一起解一次 MNA，得到与初值
自洽衔接的节点电压（不会在第一步突跳）。

每一步都复用同一个矩阵 A（线性网络 + 定步长，A 不变），只更新 RHS。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .errors import ErrorCode
from .exceptions import CircuitError
from .mna import MNABuilder, check_nonsingular, solve_linear
from .model import GROUND, Circuit, ComponentKind

# 步数硬上限，防止参数失控把服务拖死。
MAX_STEPS = 20_000
METHOD = "backward_euler"


@dataclass(frozen=True)
class TransientResult:
    method: str
    dt: float
    tstop: float
    times: list[float]
    node_voltages: dict[str, list[float]]   # 节点名 -> 与 times 对齐的电压序列
    steps: int
    success: bool


def _validate_time_params(dt: float, tstop: float) -> int:
    if not isinstance(dt, (int, float)) or isinstance(dt, bool) or not math.isfinite(dt):
        raise CircuitError(ErrorCode.INVALID_DT, f"时间步长 dt 必须是有限正数，收到 {dt!r}")
    if dt <= 0.0:
        raise CircuitError(ErrorCode.INVALID_DT, f"时间步长 dt 必须为正，收到 {dt}")
    if not isinstance(tstop, (int, float)) or isinstance(tstop, bool) or not math.isfinite(tstop):
        raise CircuitError(ErrorCode.INVALID_TSTOP, f"终止时间 tstop 必须是有限数，收到 {tstop!r}")
    if tstop < dt:
        raise CircuitError(
            ErrorCode.INVALID_TSTOP,
            f"终止时间 tstop（{tstop}）不能小于一个时间步长 dt（{dt}）",
        )
    # n = round(tstop / dt)，容忍浮点误差；至少走 1 步。
    n_steps = int(round(tstop / dt))
    if n_steps < 1:
        raise CircuitError(
            ErrorCode.INVALID_TSTOP,
            f"终止时间 tstop（{tstop}）至少要覆盖一个 dt（{dt}）",
        )
    if n_steps > MAX_STEPS:
        raise CircuitError(
            ErrorCode.TOO_MANY_STEPS,
            f"总步数 {n_steps} 超过上限 {MAX_STEPS}（dt={dt}, tstop={tstop}）；"
            "请加大 dt 或减小 tstop",
        )
    return n_steps


def _initial_state(circuit: Circuit) -> tuple[dict[str, float], dict[str, float]]:
    """用初始条件求 t=0 时刻的节点电压与储能元件内部状态。

    电容 -> 值为 ic 的电压源（保证其端压恰好等于初压）；
    电感 -> 值为 ic 的电流源（保证其支路电流恰好等于初流）。
    返回 (节点电压, 元件名 -> 该元件在 t=0 的状态量)。
    """
    branch_names = [
        c.name
        for c in circuit.components
        if c.kind in (ComponentKind.VOLTAGE_SOURCE, ComponentKind.CAPACITOR)
    ]
    builder = MNABuilder(circuit, branch_names)

    cap_v: dict[str, float] = {}
    ind_i: dict[str, float] = {}

    for comp in circuit.components:
        if comp.kind is ComponentKind.RESISTOR:
            builder.stamp_conductance(comp.p, comp.n, 1.0 / comp.value)
        elif comp.kind is ComponentKind.CAPACITOR:
            builder.stamp_voltage_branch(comp.p, comp.n, comp.name, comp.ic)
            cap_v[comp.name] = float(comp.ic)
        elif comp.kind is ComponentKind.INDUCTOR:
            # i_L 方向为 p->n（离开 p），用独立电流源表示时要从 p 抽走，
            # 即按“向 p 注入 -ic”盖章。
            builder.stamp_current_injection(comp.p, comp.n, -comp.ic)
            ind_i[comp.name] = float(comp.ic)
        elif comp.kind is ComponentKind.VOLTAGE_SOURCE:
            builder.stamp_voltage_branch(comp.p, comp.n, comp.name, comp.value)
        elif comp.kind is ComponentKind.CURRENT_SOURCE:
            builder.stamp_current_injection(comp.p, comp.n, comp.value)

    system = builder.build()
    x = solve_linear(system)

    voltages = {name: 0.0 for name in system.node_names}
    for name, idx in system.node_index.items():
        voltages[name] = float(x[idx])

    # 若某个电容初压没被显式用上（理论上都会），用节点电压兜底自洽。
    return voltages, {**cap_v, **ind_i}


def transient_analysis(circuit: Circuit, dt: float, tstop: float) -> TransientResult:
    """从初始条件出发，用后向欧拉把电路推到 tstop。"""
    n_steps = _validate_time_params(dt, tstop)
    dt = float(dt)
    tstop = n_steps * dt  # 规整掉浮点尾巴，保证时间轴自洽

    node_order = list(circuit.nodes)

    # ---- t = 0：初始条件状态 --------------------------------------
    v0, state0 = _initial_state(circuit)

    # ---- 组装步进矩阵（所有时间步不变）----------------------------
    # 支路未知量：电压源；电感在 BE 伴随模型里是“电导+电流源”，不占支路。
    branch_names = [c.name for c in circuit.components
                    if c.kind is ComponentKind.VOLTAGE_SOURCE]
    builder = MNABuilder(circuit, branch_names)

    caps: list[tuple[str, str, str, float]] = []   # (name, p, n, Gc)
    inds: list[tuple[str, str, str, float]] = []   # (name, p, n, Gl)

    for comp in circuit.components:
        if comp.kind is ComponentKind.RESISTOR:
            builder.stamp_conductance(comp.p, comp.n, 1.0 / comp.value)
        elif comp.kind is ComponentKind.CAPACITOR:
            gc = comp.value / dt
            builder.stamp_conductance(comp.p, comp.n, gc)
            caps.append((comp.name, comp.p, comp.n, gc))
        elif comp.kind is ComponentKind.INDUCTOR:
            gl = dt / comp.value
            builder.stamp_conductance(comp.p, comp.n, gl)
            inds.append((comp.name, comp.p, comp.n, gl))
        elif comp.kind is ComponentKind.VOLTAGE_SOURCE:
            builder.stamp_voltage_branch(comp.p, comp.n, comp.name, comp.value)
        elif comp.kind is ComponentKind.CURRENT_SOURCE:
            builder.stamp_current_injection(comp.p, comp.n, comp.value)

    system = builder.build()
    # A 不随时间变化，预先做一次奇异性判定；每步只换右端向量重解。
    check_nonsingular(system.A)

    # ---- 时间步进 --------------------------------------------------
    times = [0.0]
    voltages_out: dict[str, list[float]] = {name: [v0[name]] for name in node_order}

    # 电容历史端压、电感历史电流（t=0 取自初始条件）。
    cap_state: dict[str, float] = {
        c.name: state0[c.name] for c in circuit.components
        if c.kind is ComponentKind.CAPACITOR
    }
    ind_state: dict[str, float] = {
        c.name: state0[c.name] for c in circuit.components
        if c.kind is ComponentKind.INDUCTOR
    }

    def node_v(name: str) -> float:
        return 0.0 if name == GROUND else float(x[system.node_index[name]])

    base_z = system.z.copy()

    for step in range(1, n_steps + 1):
        z = base_z.copy()

        # 历史电流源：向 p 注入历史量，从 n 抽走。
        for name, p, n, gc in caps:
            hist = gc * cap_state[name]
            ip = system.node_index.get(p)
            in_ = system.node_index.get(n)
            if ip is not None:
                z[ip] += hist
            if in_ is not None:
                z[in_] -= hist

        for name, p, n, gl in inds:
            # 电感历史电流 i_L^n 方向 p->n：从 p 抽走、向 n 注入。
            hist = ind_state[name]
            ip = system.node_index.get(p)
            in_ = system.node_index.get(n)
            if ip is not None:
                z[ip] -= hist
            if in_ is not None:
                z[in_] += hist

        system.z = z
        x = solve_linear(system)

        # 更新历史状态量。
        for name, p, n, _gc in caps:
            cap_state[name] = node_v(p) - node_v(n)
        for name, p, n, _gl in inds:
            # i_L^{n+1} = i_L^n + Gl (V(p)-V(n))
            ind_state[name] = ind_state[name] + _gl * (node_v(p) - node_v(n))

        times.append(round(step * dt, 12))
        for name in node_order:
            voltages_out[name].append(node_v(name))

    return TransientResult(
        method=METHOD,
        dt=dt,
        tstop=tstop,
        times=times,
        node_voltages=voltages_out,
        steps=n_steps,
        success=True,
    )
