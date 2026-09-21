"""直流工作点测试：分压比与手算一致、电流源约定、电感直流短路。"""

from __future__ import annotations

import math

import pytest

from app.circuit import (
    CircuitError,
    ErrorCode,
    dc_operating_point,
    parse_netlist,
)


def test_voltage_divider_dc_matches_hand_calculation():
    # 5V 经两个 1kΩ 电阻分压，中间节点手算 = 5 * 1000/(1000+1000) = 2.5V
    netlist = {
        "components": [
            {"name": "V1", "type": "V", "nodes": ["vdd", "0"], "value": 5.0},
            {"name": "R1", "type": "R", "nodes": ["vdd", "out"], "value": 1000.0},
            {"name": "R2", "type": "R", "nodes": ["out", "0"], "value": 1000.0},
        ]
    }
    op = dc_operating_point(parse_netlist(netlist))

    assert op.success is True
    assert op.node_voltages["0"] == 0.0
    assert op.node_voltages["vdd"] == pytest.approx(5.0, abs=1e-10)

    # 分压比：V(out) / V(vdd) 必须等于 R2/(R1+R2)
    ratio = op.node_voltages["out"] / op.node_voltages["vdd"]
    assert ratio == pytest.approx(1000.0 / 2000.0, rel=1e-10)
    assert op.node_voltages["out"] == pytest.approx(2.5, abs=1e-10)

    # 电压源支路电流以“流入 p 端”为正（SPICE 约定）；电源向外供电时为负，
    # 故 -5V/2kΩ = -2.5mA
    assert op.voltage_source_currents["V1"] == pytest.approx(-0.0025, rel=1e-10)


def test_unequal_divider_ratio():
    # 非均分：V(out) = 5 * 3k/(2k+3k) = 3V
    netlist = {
        "components": [
            {"name": "V1", "type": "V", "nodes": ["n1", "gnd"], "value": 5.0},
            {"name": "R1", "type": "R", "nodes": ["n1", "n2"], "value": 2000.0},
            {"name": "R2", "type": "R", "nodes": ["n2", "gnd"], "value": 3000.0},
        ]
    }
    op = dc_operating_point(parse_netlist(netlist))
    assert op.node_voltages["n2"] == pytest.approx(3.0, abs=1e-10)
    # gnd 与 0 是同一个参考节点
    assert "0" in op.node_voltages and "gnd" not in op.node_voltages


def test_current_source_convention():
    # 1mA 电流源向 n1 注入，经 1kΩ 入地 => V(n1) = 1mA*1kΩ = 1V
    netlist = {
        "components": [
            {"name": "I1", "type": "I", "nodes": ["n1", "0"], "value": 0.001},
            {"name": "R1", "type": "R", "nodes": ["n1", "0"], "value": 1000.0},
        ]
    }
    op = dc_operating_point(parse_netlist(netlist))
    assert op.node_voltages["n1"] == pytest.approx(1.0, abs=1e-10)

    # 反向：从 n1 抽走电流 => -1V
    netlist_rev = {
        "components": [
            {"name": "I1", "type": "I", "nodes": ["0", "n1"], "value": 0.001},
            {"name": "R1", "type": "R", "nodes": ["n1", "0"], "value": 1000.0},
        ]
    }
    op_rev = dc_operating_point(parse_netlist(netlist_rev))
    assert op_rev.node_voltages["n1"] == pytest.approx(-1.0, abs=1e-10)


def test_floating_node_is_singular():
    # n3 只通过一个电容与电路相连：直流下电容开路，n3 没有任何导纳通路，
    # 其 KCL 行为 0 = 0，矩阵奇异。
    netlist = {
        "components": [
            {"name": "V1", "type": "V", "nodes": ["n1", "0"], "value": 5.0},
            {"name": "R1", "type": "R", "nodes": ["n1", "n2"], "value": 1000.0},
            {"name": "R2", "type": "R", "nodes": ["n2", "0"], "value": 2000.0},
            {"name": "C1", "type": "C", "nodes": ["n2", "n3"], "value": 1e-6},
        ]
    }
    with pytest.raises(CircuitError) as exc:
        dc_operating_point(parse_netlist(netlist))
    assert exc.value.code == ErrorCode.SINGULAR_MATRIX


def test_resistor_dangling_end_is_valid_zero_current_branch():
    # 经电阻悬空的末端不是奇异：该支路电流为零，两端等电位。
    netlist = {
        "components": [
            {"name": "V1", "type": "V", "nodes": ["n1", "0"], "value": 5.0},
            {"name": "R1", "type": "R", "nodes": ["n1", "n2"], "value": 1000.0},
            {"name": "R2", "type": "R", "nodes": ["n2", "0"], "value": 2000.0},
            {"name": "R3", "type": "R", "nodes": ["n2", "n3"], "value": 50.0},
        ]
    }
    op = dc_operating_point(parse_netlist(netlist))
    assert op.node_voltages["n3"] == pytest.approx(op.node_voltages["n2"], abs=1e-10)


def test_inductor_is_short_at_dc():
    # 5V -> L -> 1kΩ -> gnd：电感直流短路，电流 = 5mA
    netlist = {
        "components": [
            {"name": "V1", "type": "V", "nodes": ["n1", "0"], "value": 5.0},
            {"name": "L1", "type": "L", "nodes": ["n1", "n2"], "value": 1e-3, "ic": 0.0},
            {"name": "R1", "type": "R", "nodes": ["n2", "0"], "value": 1000.0},
        ]
    }
    op = dc_operating_point(parse_netlist(netlist))
    assert op.node_voltages["n2"] == pytest.approx(5.0, abs=1e-10)
    assert op.inductor_currents["L1"] == pytest.approx(0.005, rel=1e-10)
    assert op.voltage_source_currents["V1"] == pytest.approx(-0.005, rel=1e-10)
    assert math.isfinite(op.node_voltages["n1"])
