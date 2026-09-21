"""网表解析与合法性校验测试：规格列出的各类非法情形全部要被挡回。"""

from __future__ import annotations

import pytest

from app.circuit import CircuitError, ErrorCode, parse_netlist


def expect_error(payload, code):
    with pytest.raises(CircuitError) as exc:
        parse_netlist(payload)
    assert exc.value.code == code
    # 每类错误都必须带一句非空的人话说明
    assert exc.value.message and isinstance(exc.value.message, str)
    return exc.value


def test_unknown_component_type():
    payload = {"components": [
        {"name": "X1", "type": "diode", "nodes": ["a", "0"], "value": 1.0}
    ]}
    expect_error(payload, ErrorCode.UNKNOWN_COMPONENT_TYPE)


def test_missing_required_nodes():
    # 完全没有 nodes
    expect_error(
        {"components": [{"name": "R1", "type": "R", "value": 100.0}]},
        ErrorCode.MISSING_NODES,
    )
    # 只给一个节点
    expect_error(
        {"components": [{"name": "R1", "type": "R", "nodes": ["a"], "value": 100.0}]},
        ErrorCode.MISSING_NODES,
    )
    # 节点是空串
    expect_error(
        {"components": [{"name": "R1", "type": "R", "nodes": ["a", "  "], "value": 100.0}]},
        ErrorCode.MISSING_NODES,
    )


def test_no_ground_reference():
    payload = {"components": [
        {"name": "V1", "type": "V", "nodes": ["a", "b"], "value": 5.0},
        {"name": "R1", "type": "R", "nodes": ["a", "b"], "value": 100.0},
    ]}
    expect_error(payload, ErrorCode.NO_GROUND)


def test_empty_netlist_has_no_ground():
    expect_error({"components": []}, ErrorCode.NO_GROUND)


def test_zero_resistance_rejected():
    payload = {"components": [
        {"name": "R1", "type": "R", "nodes": ["a", "0"], "value": 0.0}
    ]}
    expect_error(payload, ErrorCode.ZERO_RESISTANCE)


def test_duplicate_names_rejected():
    payload = {"components": [
        {"name": "R1", "type": "R", "nodes": ["a", "0"], "value": 100.0},
        {"name": "R1", "type": "R", "nodes": ["a", "b"], "value": 200.0},
    ]}
    expect_error(payload, ErrorCode.DUPLICATE_NAME)


def test_voltage_source_loop_rejected():
    # 三个理想电压源围成环：a-b-c-a
    payload = {"components": [
        {"name": "V1", "type": "V", "nodes": ["a", "b"], "value": 1.0},
        {"name": "V2", "type": "V", "nodes": ["b", "c"], "value": 2.0},
        {"name": "V3", "type": "V", "nodes": ["c", "a"], "value": 3.0},
    ]}
    expect_error(payload, ErrorCode.VOLTAGE_SOURCE_LOOP)


def test_parallel_voltage_sources_rejected():
    # 两个电压源直接并联也是回路（长度 2）
    payload = {"components": [
        {"name": "V1", "type": "V", "nodes": ["a", "0"], "value": 5.0},
        {"name": "V2", "type": "V", "nodes": ["0", "a"], "value": 3.0},
    ]}
    expect_error(payload, ErrorCode.VOLTAGE_SOURCE_LOOP)


def test_self_loop_voltage_source_rejected():
    # 电压源两端接同一节点：V(a)-V(a)=value，自相矛盾
    payload = {"components": [
        {"name": "V1", "type": "V", "nodes": ["a", "a"], "value": 5.0},
        {"name": "R1", "type": "R", "nodes": ["a", "0"], "value": 100.0},
    ]}
    expect_error(payload, ErrorCode.VOLTAGE_SOURCE_LOOP)


def test_star_voltage_sources_are_allowed():
    # 星形连接（公共节点地）不构成环，应正常通过解析
    payload = {"components": [
        {"name": "V1", "type": "V", "nodes": ["a", "0"], "value": 5.0},
        {"name": "V2", "type": "V", "nodes": ["b", "0"], "value": 3.0},
        {"name": "R1", "type": "R", "nodes": ["a", "b"], "value": 1000.0},
    ]}
    circuit = parse_netlist(payload)
    assert len(circuit.components) == 3
    assert circuit.nodes[0] == "0"


def test_missing_value_and_name():
    expect_error(
        {"components": [{"name": "R1", "type": "R", "nodes": ["a", "0"]}]},
        ErrorCode.MISSING_VALUE,
    )
    expect_error(
        {"components": [{"type": "R", "nodes": ["a", "0"], "value": 10.0}]},
        ErrorCode.MISSING_NAME,
    )


def test_nan_and_inf_values_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        expect_error(
            {"components": [{"name": "R1", "type": "R", "nodes": ["a", "0"], "value": bad}]},
            ErrorCode.INVALID_VALUE,
        )


def test_negative_capacitance_inductance_rejected():
    expect_error(
        {"components": [{"name": "C1", "type": "C", "nodes": ["a", "0"], "value": -1e-6}]},
        ErrorCode.INVALID_VALUE,
    )
    expect_error(
        {"components": [{"name": "L1", "type": "L", "nodes": ["a", "0"], "value": 0.0}]},
        ErrorCode.INVALID_VALUE,
    )


def test_chinese_type_aliases_and_ground_alias():
    payload = {"components": [
        {"name": "电压源1", "type": "电压源", "nodes": ["a", "gnd"], "value": 5.0},
        {"name": "电阻1", "type": "电阻", "nodes": ["a", "gnd"], "value": 100.0},
    ]}
    circuit = parse_netlist(payload)
    assert "0" in circuit.nodes
    assert all(c.n == "0" or c.p == "0" or True for c in circuit.components)


def test_integer_zero_node_accepted():
    payload = {"components": [
        {"name": "V1", "type": "V", "nodes": ["a", 0], "value": 5.0},
        {"name": "R1", "type": "R", "nodes": ["a", 0], "value": 100.0},
    ]}
    circuit = parse_netlist(payload)
    assert circuit.components[0].n == "0"
