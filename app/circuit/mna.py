"""修正节点分析法（Modified Nodal Analysis）。

矩阵分块形式：

        [ G   B ] [ v ]   [ i ]
        [ B^T D ] [ j ] = [ e ]

    * v：非地节点电压未知量。
    * j：额外支路电流未知量（目前用于理想电压源；直流下的电感也用它表示）。
    * G：节点导纳块，电阻贡献电导，C/L 的伴随模型也贡献在这里。
    * i：注入节点的电流（独立电流源 + 伴随模型的历史电流项）。
    * e：电压源类支路的约束电压。

组装只认“盖章（stamp）”动作：直流分析和瞬态伴随模型往同一个
Builder 上盖章，保证两种分析共用一套元件语义，不会各写一份方程。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import ErrorCode
from .exceptions import CircuitError
from .model import Circuit, GROUND


@dataclass
class MNASystem:
    """组装完成、随时可解的线性系统 A x = z。"""

    A: np.ndarray
    z: np.ndarray
    node_index: dict[str, int]      # 节点名 -> 电压未知量编号（地不在其中）
    branch_index: dict[str, int]    # 支路名 -> 电流未知量编号
    node_names: list[str]           # 全部节点（含地），与电压解的展示顺序一致
    branch_names: list[str]         # 支路顺序

    @property
    def n_nodes(self) -> int:
        return len(self.node_names)

    @property
    def n_branches(self) -> int:
        return len(self.branch_names)

    @property
    def size(self) -> int:
        return self.A.shape[0]


class MNABuilder:
    """逐元件盖章组装 A 和 z。

    支路电流方向约定：j 以“从支路 p 端流入元件”为正（SPICE 约定，
    电源向电路供电时 j 为负值）。KCL 行形式为 G v + j = i，
    支路行形式为 V(p)-V(n) = E。
    """

    def __init__(self, circuit: Circuit, branch_names: list[str]) -> None:
        self.circuit = circuit
        self.node_names = list(circuit.nodes)          # 第一个是地 "0"
        self.branch_names = list(branch_names)

        # 地节点只占展示位、不占矩阵行；非地节点按展示顺序映射到 0 起始的行号。
        non_ground = [name for name in self.node_names if name != GROUND]
        self.node_index = {name: k for k, name in enumerate(non_ground)}
        # 电压未知量排在前面（地占一个展示位但不占矩阵行），
        # 支路未知量接在后面。
        n_v = len(self.node_names) - 1
        n_b = len(branch_names)
        self.branch_index = {name: n_v + b for b, name in enumerate(branch_names)}

        self.A = np.zeros((n_v + n_b, n_v + n_b), dtype=np.float64)
        self.z = np.zeros(n_v + n_b, dtype=np.float64)

    # ---- 基础盖章动作 -------------------------------------------------

    def stamp_conductance(self, p: str, n: str, g: float) -> None:
        """在 p、n 之间盖一个电导 g（自导纳 +g，互导纳 -g）。"""
        ip = self.node_index.get(p)
        in_ = self.node_index.get(n)
        if ip is not None:
            self.A[ip, ip] += g
        if in_ is not None:
            self.A[in_, in_] += g
        if ip is not None and in_ is not None:
            self.A[ip, in_] -= g
            self.A[in_, ip] -= g

    def stamp_current_injection(self, p: str, n: str, current: float) -> None:
        """向 p 注入 current、从 n 抽走 current（RHS）。"""
        ip = self.node_index.get(p)
        in_ = self.node_index.get(n)
        if ip is not None:
            self.z[ip] += current
        if in_ is not None:
            self.z[in_] -= current

    def stamp_voltage_branch(self, p: str, n: str, branch: str, voltage: float) -> None:
        """盖一个理想电压源支路：V(p)-V(n) = voltage，引入支路电流未知量。

        支路电流 j 以“从 p 端流入元件”为正（SPICE 约定）。
        节点 p 的 KCL 中 j 是流入（符号为 +），节点 n 中 j 是流出（符号为 -）。
        """
        ip = self.node_index.get(p)
        in_ = self.node_index.get(n)
        ib = self.branch_index[branch]

        if ip is not None:
            self.A[ip, ib] += 1.0
            self.A[ib, ip] += 1.0
        if in_ is not None:
            self.A[in_, ib] -= 1.0
            self.A[ib, in_] -= 1.0
        self.z[ib] += voltage

    def build(self) -> MNASystem:
        return MNASystem(
            A=self.A,
            z=self.z,
            node_index=dict(self.node_index),
            branch_index=dict(self.branch_index),
            node_names=list(self.node_names),
            branch_names=list(self.branch_names),
        )


def check_nonsingular(A: np.ndarray) -> None:
    """用奇异值判定 A 是否非奇异；奇异时抛 CircuitError。"""
    if not np.all(np.isfinite(A)):
        raise CircuitError(
            ErrorCode.SINGULAR_MATRIX,
            "系数矩阵含有 NaN/Inf，无法求解",
        )
    if A.size == 0:
        return

    try:
        singular_values = np.linalg.svd(A, compute_uv=False)
    except np.linalg.LinAlgError as exc:
        raise CircuitError(
            ErrorCode.SINGULAR_MATRIX,
            f"SVD 分解失败，系数矩阵无法求解：{exc}",
        ) from exc

    smax = float(singular_values[0])
    rank_tol = 1e-10 * smax if smax > 0.0 else 0.0
    if smax == 0.0 or float(singular_values[-1]) <= rank_tol:
        raise CircuitError(
            ErrorCode.SINGULAR_MATRIX,
            "修正节点方程的系数矩阵奇异：电路中可能存在悬浮节点"
            "（不接任何元件）、纯电压源回路，或缺少直流通路",
        )


def solve_linear(system: MNASystem) -> np.ndarray:
    """解 A x = z；矩阵奇异时干净地报错，绝不返回 NaN/Inf。"""
    A = system.A
    z = system.z

    if A.size == 0:
        # 全网只有地节点、没有任何未知量，这是空解，不算错误。
        return np.zeros(0, dtype=np.float64)

    if not np.all(np.isfinite(z)):
        raise CircuitError(
            ErrorCode.SINGULAR_MATRIX,
            "右端向量含有 NaN/Inf，无法求解",
        )

    check_nonsingular(A)

    # SVD 已判非奇异，这里求解再兜底一次。
    try:
        x = np.linalg.solve(A, z)
    except np.linalg.LinAlgError as exc:
        raise CircuitError(
            ErrorCode.SINGULAR_MATRIX,
            f"线性方程组求解失败：{exc}",
        ) from exc

    if not np.all(np.isfinite(x)):
        raise CircuitError(
            ErrorCode.SINGULAR_MATRIX,
            "求解结果中出现 NaN 或无穷大，矩阵实际为奇异",
        )
    return x
