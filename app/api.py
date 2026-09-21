"""HTTP 接口层：只做请求转发与结果封装，不含任何解析/组装/步进逻辑。"""

from __future__ import annotations

from fastapi import APIRouter

from .circuit import dc_operating_point, parse_netlist, transient_analysis
from .schemas import (
    DCOperatingPointOut,
    NetlistIn,
    TransientIn,
    TransientOut,
)

router = APIRouter()


def _to_plain(payload) -> dict:
    """把 Pydantic 网表模型转成解析内核吃的普通 dict。"""
    return {"components": [comp.model_dump() for comp in payload.components]}


@router.post("/dc", response_model=DCOperatingPointOut, tags=["analysis"])
def run_dc(payload: NetlistIn) -> DCOperatingPointOut:
    """喂一份网表，吐直流工作点（节点电位、电压源支路电流）。"""
    circuit = parse_netlist(_to_plain(payload))
    op = dc_operating_point(circuit)
    return DCOperatingPointOut(
        node_voltages=op.node_voltages,
        voltage_source_currents=op.voltage_source_currents,
        inductor_currents=op.inductor_currents,
    )


@router.post("/transient", response_model=TransientOut, tags=["analysis"])
def run_transient(payload: TransientIn) -> TransientOut:
    """喂一份网表加 dt/tstop，吐沿时间轴的节点电压序列。"""
    circuit = parse_netlist(_to_plain(payload))
    result = transient_analysis(circuit, payload.dt, payload.tstop)
    return TransientOut(
        method=result.method,
        dt=result.dt,
        tstop=result.tstop,
        steps=result.steps,
        times=result.times,
        node_voltages=result.node_voltages,
    )
