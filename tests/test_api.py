"""端到端 HTTP 接口测试：成功响应结构、错误码与状态码、两个内置算例。"""

from __future__ import annotations

import json
import math
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "examples")


def load_example(filename: str) -> dict:
    with open(os.path.join(EXAMPLES_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dc_endpoint_voltage_divider_example():
    payload = load_example("voltage_divider.json")
    resp = client.post("/dc", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["node_voltages"]["0"] == 0.0
    assert body["node_voltages"]["out"] == pytest.approx(2.5, abs=1e-9)
    assert body["node_voltages"]["vdd"] == pytest.approx(5.0, abs=1e-9)
    assert body["voltage_source_currents"]["V1"] == pytest.approx(-0.0025, rel=1e-9)


def test_transient_endpoint_rc_example():
    payload = load_example("rc_charge.json")
    resp = client.post("/transient", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["method"] == "backward_euler"
    assert body["steps"] == 100
    assert len(body["times"]) == len(body["node_voltages"]["cap"]) == 101
    assert body["times"][0] == 0.0

    v_end = body["node_voltages"]["cap"][-1]
    assert v_end / 5.0 == pytest.approx(1.0 - math.exp(-5.0), rel=2e-3)


def test_unknown_type_error_response():
    resp = client.post("/dc", json={"components": [
        {"name": "D1", "type": "diode", "nodes": ["a", "0"], "value": 1.0}
    ]})
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error_code"] == "UNKNOWN_COMPONENT_TYPE"
    assert body["message"]


def test_zero_resistance_error_response():
    resp = client.post("/dc", json={"components": [
        {"name": "R1", "type": "R", "nodes": ["a", "0"], "value": 0.0}
    ]})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "ZERO_RESISTANCE"


def test_no_ground_error_response():
    resp = client.post("/dc", json={"components": [
        {"name": "R1", "type": "R", "nodes": ["a", "b"], "value": 10.0}
    ]})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "NO_GROUND"


def test_duplicate_name_error_response():
    resp = client.post("/dc", json={"components": [
        {"name": "R1", "type": "R", "nodes": ["a", "0"], "value": 10.0},
        {"name": "R1", "type": "R", "nodes": ["a", "b"], "value": 20.0},
    ]})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "DUPLICATE_NAME"


def test_voltage_loop_error_response():
    resp = client.post("/dc", json={"components": [
        {"name": "V1", "type": "V", "nodes": ["a", "b"], "value": 1.0},
        {"name": "V2", "type": "V", "nodes": ["b", "c"], "value": 2.0},
        {"name": "V3", "type": "V", "nodes": ["c", "a"], "value": 3.0},
    ]})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "VOLTAGE_SOURCE_LOOP"


def test_singular_matrix_error_response():
    # 节点 n3 只经电容（直流开路）挂出 => 悬浮 => 奇异
    resp = client.post("/dc", json={"components": [
        {"name": "V1", "type": "V", "nodes": ["n1", "0"], "value": 5.0},
        {"name": "R1", "type": "R", "nodes": ["n1", "n2"], "value": 1000.0},
        {"name": "R2", "type": "R", "nodes": ["n2", "0"], "value": 2000.0},
        {"name": "C1", "type": "C", "nodes": ["n2", "n3"], "value": 1e-6},
    ]})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "SINGULAR_MATRIX"
    assert body["message"]


def test_transient_invalid_params_via_http():
    payload = load_example("rc_charge.json")
    payload["dt"] = -1e-6
    resp = client.post("/transient", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_DT"

    payload = load_example("rc_charge.json")
    payload["tstop"] = payload["dt"] / 2
    resp = client.post("/transient", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_TSTOP"

    payload = load_example("rc_charge.json")
    payload["dt"] = 1e-9
    payload["tstop"] = 0.1
    resp = client.post("/transient", json=payload)
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "TOO_MANY_STEPS"


def test_malformed_json_body_returns_unified_error():
    resp = client.post("/dc", json={"components": [{"name": "R1"}]})
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert "error_code" in body and body["message"]


def test_ic_self_consistency_via_http():
    payload = load_example("rc_charge.json")
    payload["components"][-1]["ic"] = 2.0
    resp = client.post("/transient", json=payload)
    assert resp.status_code == 200, resp.text
    v = resp.json()["node_voltages"]["cap"]
    assert v[0] == pytest.approx(2.0, abs=1e-12)
    assert v[0] != 0.0
