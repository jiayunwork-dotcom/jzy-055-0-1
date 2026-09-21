"""网表解析与合法性校验。

输入是一组元件描述（dict），每个元件形如：
    {"name": "R1", "type": "R", "nodes": ["n1", "0"], "value": 1000}
电容/电感可额外给 "ic"（电容初压 / 电感初流），不给按零算。

本模块只负责把文本式输入变成严格校验过的 Circuit 对象；
不做任何矩阵组装或数值计算。所有非法情况都抛 CircuitError，
绝不吞掉元件继续往下算。
"""

from __future__ import annotations

import math
from typing import Any

from .errors import ErrorCode
from .exceptions import CircuitError
from .model import (
    GROUND,
    GROUND_ALIASES,
    TYPE_ALIASES,
    Circuit,
    Component,
    ComponentKind,
)


def _err(code: str, message: str) -> CircuitError:
    return CircuitError(code, message)


def _normalize_node(raw: Any) -> str:
    """把节点名规范化：数字 0 / 字符串 0、gnd 一律归一到 "0"。"""
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise _err(
            ErrorCode.INVALID_VALUE,
            f"节点名必须是字符串或整数，收到 {raw!r}",
        )
    text = str(raw).strip()
    if not text:
        raise _err(ErrorCode.MISSING_NODES, "存在空的节点名")
    if text in GROUND_ALIASES:
        return GROUND
    return text


def _finite_float(raw: Any, field: str, comp_label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _err(
            ErrorCode.INVALID_VALUE,
            f"元件 {comp_label} 的 {field} 必须是数值，收到 {raw!r}",
        )
    value = float(raw)
    if not math.isfinite(value):
        raise _err(
            ErrorCode.INVALID_VALUE,
            f"元件 {comp_label} 的 {field} 不能是 NaN 或无穷大",
        )
    return value


def _parse_component(raw: Any, index: int) -> Component:
    if not isinstance(raw, dict):
        raise _err(
            ErrorCode.INVALID_VALUE,
            f"第 {index} 个元件必须是对象，收到 {type(raw).__name__}",
        )

    # 名称
    name_raw = raw.get("name")
    if name_raw is None or (isinstance(name_raw, str) and not name_raw.strip()):
        raise _err(ErrorCode.MISSING_NAME, f"第 {index} 个元件缺少名称 name")
    if not isinstance(name_raw, str):
        raise _err(ErrorCode.INVALID_VALUE, f"元件名称必须是字符串，收到 {name_raw!r}")
    name = name_raw.strip()

    # 类型
    type_raw = raw.get("type")
    if type_raw is None:
        raise _err(
            ErrorCode.UNKNOWN_COMPONENT_TYPE,
            f"元件 {name} 缺少 type 字段",
        )
    if not isinstance(type_raw, str):
        raise _err(
            ErrorCode.UNKNOWN_COMPONENT_TYPE,
            f"元件 {name} 的类型必须是字符串，收到 {type_raw!r}",
        )
    kind = TYPE_ALIASES.get(type_raw.strip().lower())
    if kind is None:
        raise _err(
            ErrorCode.UNKNOWN_COMPONENT_TYPE,
            f"元件 {name} 的类型 {type_raw!r} 不被支持"
            "（只支持 R / C / L / V / I）",
        )

    # 节点：恰好两个，都不能缺
    nodes_raw = raw.get("nodes")
    if nodes_raw is None:
        raise _err(
            ErrorCode.MISSING_NODES,
            f"元件 {name} 缺少必需的节点 nodes（需要两个节点）",
        )
    if not isinstance(nodes_raw, (list, tuple)):
        raise _err(
            ErrorCode.MISSING_NODES,
            f"元件 {name} 的 nodes 必须是含两个节点名的列表",
        )
    if len(nodes_raw) != 2:
        raise _err(
            ErrorCode.MISSING_NODES,
            f"元件 {name} 必须恰好连接两个节点，收到 {len(nodes_raw)} 个",
        )
    p = _normalize_node(nodes_raw[0])
    n = _normalize_node(nodes_raw[1])

    # 参数值
    if "value" not in raw or raw["value"] is None:
        raise _err(
            ErrorCode.MISSING_VALUE,
            f"元件 {name} 缺少参数值 value",
        )
    value = _finite_float(raw["value"], "value", name)

    if kind is ComponentKind.RESISTOR and value == 0.0:
        raise _err(
            ErrorCode.ZERO_RESISTANCE,
            f"电阻 {name} 的阻值为零；零欧电阻会让导纳无穷大，请改用理想电压源等模型",
        )
    if kind is ComponentKind.RESISTOR and value < 0.0:
        raise _err(
            ErrorCode.INVALID_VALUE,
            f"电阻 {name} 的阻值不能为负（收到 {value}）",
        )
    if kind in (ComponentKind.CAPACITOR, ComponentKind.INDUCTOR) and value <= 0.0:
        unit = "电容" if kind is ComponentKind.CAPACITOR else "电感"
        raise _err(
            ErrorCode.INVALID_VALUE,
            f"{unit} {name} 的取值必须为正（收到 {value}）",
        )

    # 初始条件（只对 C / L 有意义）
    ic = 0.0
    if "ic" in raw and raw["ic"] is not None:
        ic = _finite_float(raw["ic"], "ic", name)

    return Component(name=name, kind=kind, p=p, n=n, value=value, ic=ic)


class _DSU:
    """并查集：用来检测理想电压源是否首尾相连围出回路。"""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        root = x
        while self._parent.setdefault(root, root) != root:
            root = self._parent[root]
        # 路径压缩
        while self._parent[x] != x:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> bool:
        """把 a、b 合并；若它们已在同一集合则返回 True（出现回路）。"""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        self._parent[rb] = ra
        return False


def parse_netlist(data: Any) -> Circuit:
    """解析并整体校验一张网表。

    Returns:
        Circuit：组件元组固定、节点集合确定的不可变网表。
    Raises:
        CircuitError: 任何非法情况，携带错误码与人话说明。
    """
    if not isinstance(data, dict):
        raise _err(
            ErrorCode.INVALID_VALUE,
            "网表必须是对象，形如 {\"components\": [...]}",
        )
    raw_components = data.get("components")
    if raw_components is None:
        raise _err(
            ErrorCode.INVALID_VALUE,
            "网表缺少 components 字段",
        )
    if not isinstance(raw_components, list):
        raise _err(
            ErrorCode.INVALID_VALUE,
            "components 必须是元件对象的列表",
        )

    components: list[Component] = []
    seen_names: set[str] = set()
    node_set: set[str] = set()

    for index, raw in enumerate(raw_components):
        comp = _parse_component(raw, index)

        if comp.name in seen_names:
            raise _err(
                ErrorCode.DUPLICATE_NAME,
                f"元件名称 {comp.name} 出现了多次；每个元件必须有唯一名称",
            )
        seen_names.add(comp.name)

        components.append(comp)
        node_set.add(comp.p)
        node_set.add(comp.n)

    # 理想电压源围成回路 => 方程组先验奇异，解析阶段直接挡回。
    # 这个检查不依赖地节点是否存在：哪怕同时缺地，回路本身也是硬错误。
    # 注意：电感虽然在直流下相当于短路，但它在瞬态中是储能元件，
    # 不参与这里的“纯理想电压源回路”判定。
    dsu = _DSU()
    for comp in components:
        if comp.kind is ComponentKind.VOLTAGE_SOURCE:
            if dsu.union(comp.p, comp.n):
                raise _err(
                    ErrorCode.VOLTAGE_SOURCE_LOOP,
                    f"理想电压源 {comp.name} 与其他电压源首尾相连围成了回路"
                    "（含并联），约束方程相互冲突，方程组奇异",
                )

    # 必须恰好有一个接地参考节点（0 / gnd 已在解析时归一为同一个 "0"）
    if GROUND not in node_set:
        raise _err(
            ErrorCode.NO_GROUND,
            "整张网表找不到接地参考节点；必须有一个名为 0 或 gnd 的节点",
        )

    # 节点顺序：地永远在第一位，其余按名字排序，保证输出稳定可复现。
    other_nodes = sorted(node_set - {GROUND})
    nodes = (GROUND, *other_nodes)

    return Circuit(components=tuple(components), nodes=nodes)
