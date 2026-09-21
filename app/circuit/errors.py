"""网表解析、修正节点分析与瞬态积分用到的错误码。"""

from __future__ import annotations


class ErrorCode:
    UNKNOWN_COMPONENT_TYPE = "UNKNOWN_COMPONENT_TYPE"   # 不认识的元件类型
    MISSING_NODES = "MISSING_NODES"                     # 元件缺少必需的节点
    NO_GROUND = "NO_GROUND"                             # 整张网找不到接地参考
    ZERO_RESISTANCE = "ZERO_RESISTANCE"                 # 电阻取值为零
    DUPLICATE_NAME = "DUPLICATE_NAME"                   # 两个元件重名
    VOLTAGE_SOURCE_LOOP = "VOLTAGE_SOURCE_LOOP"         # 理想电压源围成回路
    INVALID_VALUE = "INVALID_VALUE"                     # 参数值非法（非数值/非正/NaN/Inf）
    MISSING_NAME = "MISSING_NAME"                       # 元件没有名称
    MISSING_VALUE = "MISSING_VALUE"                     # 元件缺少参数值
    SINGULAR_MATRIX = "SINGULAR_MATRIX"                 # 系数矩阵奇异，无法求解
    INVALID_DT = "INVALID_DT"                           # dt 不为正
    INVALID_TSTOP = "INVALID_TSTOP"                     # tstop < dt
    TOO_MANY_STEPS = "TOO_MANY_STEPS"                   # 步数超过上限
