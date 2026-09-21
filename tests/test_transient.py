"""瞬态分析测试：RC 充电末态、时间常数、电容初值自洽、非法参数。"""

from __future__ import annotations

import math

import pytest

from app.circuit import (
    CircuitError,
    ErrorCode,
    parse_netlist,
    transient_analysis,
)


def rc_circuit(v_source: float = 5.0, r: float = 1000.0, c: float = 1e-6,
               ic: float | None = None):
    return {
        "components": [
            {"name": "V1", "type": "V", "nodes": ["vdd", "0"], "value": v_source},
            {"name": "R1", "type": "R", "nodes": ["vdd", "cap"], "value": r},
            {"name": "C1", "type": "C", "nodes": ["cap", "0"], "value": c,
             **({"ic": ic} if ic is not None else {})},
        ]
    }


def test_rc_end_voltage_approaches_source():
    tau = 1000.0 * 1e-6            # 1 ms
    result = transient_analysis(parse_netlist(rc_circuit()), dt=0.05e-3, tstop=5e-3)

    assert result.success is True
    assert result.method == "backward_euler"
    assert result.steps == 100
    assert len(result.times) == 101
    assert result.times[0] == 0.0
    assert result.node_voltages["cap"][0] == pytest.approx(0.0, abs=1e-12)

    v_end = result.node_voltages["cap"][-1]
    # 5 个时间常数后，精确解 5*(1-e^-5) ≈ 4.9663V，约为电源的 99.3%
    expected = 5.0 * (1.0 - math.exp(-5.0))
    assert v_end == pytest.approx(expected, rel=2e-3)
    assert v_end / 5.0 == pytest.approx(0.993, abs=5e-3)
    assert v_end < 5.0            # 隐式 BE 只能从下方逼近，不会超过电源


def test_rc_time_constant_matches_rc():
    tau = 1000.0 * 1e-6
    dt = 0.01e-3
    result = transient_analysis(parse_netlist(rc_circuit()), dt=dt, tstop=5e-3)
    times = result.times
    vcap = result.node_voltages["cap"]

    # 精确解在 t = tau 时达到电源的 (1 - 1/e) ≈ 0.6321。
    target = 5.0 * (1.0 - 1.0 / math.e)
    crossing = next(t for t, v in zip(times, vcap) if v >= target)

    # BE 的等效“爬升”比精确指数稍慢，穿越时刻不应早于 tau，
    # 在细步长下应紧贴 tau（允许两个步长的离散误差）。
    assert tau <= crossing <= tau + 2 * dt

    # 整条曲线都必须在精确指数曲线下方（BE 的数值阻尼特性），
    # 且在 tau 附近的相对误差由 dt/tau 控制。
    for t, v in zip(times[1:], vcap[1:]):
        exact = 5.0 * (1.0 - math.exp(-t / tau))
        assert v <= exact + 1e-10
        if t >= 0.5e-3:
            assert v == pytest.approx(exact, rel=0.03)


def test_capacitor_initial_voltage_is_self_consistent():
    # 非零初压 1V：t=0 节点电压必须等于初值，第一个时间点不能突跳，
    # 且严格满足后向欧拉一步递推式。
    ic = 1.0
    r, c, dt = 1000.0, 1e-6, 0.05e-3
    result = transient_analysis(parse_netlist(rc_circuit(ic=ic)), dt=dt, tstop=5e-3)

    v = result.node_voltages["cap"]
    assert v[0] == pytest.approx(ic, abs=1e-12)          # 初值精确衔接

    g = c / dt
    # 一步 BE：(1/R + g) V1 = Vs/R + g*ic
    v1_exact = (5.0 / r + g * ic) / (1.0 / r + g)
    assert v[1] == pytest.approx(v1_exact, abs=1e-12)
    assert abs(v[1] - v[0]) == pytest.approx(abs(v1_exact - ic), abs=1e-12)

    # 充电方向：从 1V 单调向 5V 走
    assert v[0] < v[1] < 5.0


def test_zero_initial_by_default():
    # 不给 ic 时按零算
    result = transient_analysis(parse_netlist(rc_circuit()), dt=1e-4, tstop=1e-3)
    assert result.node_voltages["cap"][0] == 0.0


def test_invalid_dt_and_tstop():
    circuit = parse_netlist(rc_circuit())

    with pytest.raises(CircuitError) as e1:
        transient_analysis(circuit, dt=0.0, tstop=1e-3)
    assert e1.value.code == ErrorCode.INVALID_DT

    with pytest.raises(CircuitError) as e2:
        transient_analysis(circuit, dt=-1e-5, tstop=1e-3)
    assert e2.value.code == ErrorCode.INVALID_DT

    with pytest.raises(CircuitError) as e3:
        transient_analysis(circuit, dt=1e-3, tstop=0.5e-3)
    assert e3.value.code == ErrorCode.INVALID_TSTOP


def test_too_many_steps_rejected():
    circuit = parse_netlist(rc_circuit())
    # 20001 步，超过两万上限
    with pytest.raises(CircuitError) as exc:
        transient_analysis(circuit, dt=1e-6, tstop=0.020001)
    assert exc.value.code == ErrorCode.TOO_MANY_STEPS

    # 恰好两万步应被接受
    result = transient_analysis(circuit, dt=1e-6, tstop=0.02)
    assert result.steps == 20000


def test_rl_turn_on_with_zero_initial_current():
    # RL 接通：5V -> 1kΩ -> L(1mH) -> gnd，i(0)=0，按 i = V/R (1-e^{-tR/L}) 上升
    r, L = 1000.0, 1e-3
    tau = L / r                          # 1 µs
    netlist = {
        "components": [
            {"name": "V1", "type": "V", "nodes": ["n1", "0"], "value": 5.0},
            {"name": "R1", "type": "R", "nodes": ["n1", "n2"], "value": r},
            {"name": "L1", "type": "L", "nodes": ["n2", "0"], "value": L, "ic": 0.0},
        ]
    }
    dt = 0.05e-6
    result = transient_analysis(parse_netlist(netlist), dt=dt, tstop=5 * tau)

    # i_L = -i_R 方向关系；直接由节点电压推电流：i_R = (5 - V(n2))/R
    vn2 = result.node_voltages["n2"]
    assert vn2[0] == pytest.approx(5.0, abs=1e-9)   # i(0)=0 => 电阻无压降

    i_end = (5.0 - vn2[-1]) / r
    expected = (5.0 / r) * (1.0 - math.exp(-5.0))
    assert i_end == pytest.approx(expected, rel=2e-3)

    # 时间常数：V(n2) 在 t=tau 处约为 5/e
    target_v = 5.0 / math.e
    crossing = next(t for t, v in zip(result.times, vn2) if v <= target_v)
    assert tau - 2 * dt <= crossing <= tau + 2 * dt
