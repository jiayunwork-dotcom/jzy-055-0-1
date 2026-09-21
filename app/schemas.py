"""HTTP 接口层的数据契约（Pydantic 模型）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ComponentIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="元件唯一名称，如 R1")
    type: str = Field(..., description="元件类型：R / C / L / V / I")
    nodes: list[str | int] = Field(..., description="连接的两个节点名 [p, n]")
    value: float = Field(..., description="R:欧姆 C:法拉 L:亨利 V:伏特 I:安培")
    ic: float | None = Field(
        None, description="初始条件：电容初压(伏特)/电感初流(安培)，缺省为零"
    )


class NetlistIn(BaseModel):
    components: list[ComponentIn] = Field(..., description="组成网表的元件列表")


class TransientIn(NetlistIn):
    dt: float = Field(..., description="时间步长（秒），必须为正")
    tstop: float = Field(..., description="终止时间（秒），至少为一个 dt")


class DCOperatingPointOut(BaseModel):
    success: Literal[True] = True
    node_voltages: dict[str, float]
    voltage_source_currents: dict[str, float]
    inductor_currents: dict[str, float]


class TransientOut(BaseModel):
    success: Literal[True] = True
    method: str
    dt: float
    tstop: float
    steps: int
    times: list[float]
    node_voltages: dict[str, list[float]]


class ErrorOut(BaseModel):
    success: Literal[False] = False
    error_code: str
    message: str
