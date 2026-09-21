# 电路直流工作点与瞬态仿真服务

一个纯 HTTP 的电路仿真内核：喂一份文本式网表，返回**直流工作点**或**后向欧拉瞬态波形**。
没有画布、没有拖拽，所有电学计算在服务端完成，结果可被独立复算检验。

- 运行时：Python 3.12 + FastAPI + NumPy
- 线性求解：修正节点分析法（MNA）
- 瞬态积分：隐式定步长**后向欧拉（Backward Euler）**，全程只用这一种方法

## 目录结构

```
app/
  circuit/
    errors.py        # 全部机器可读错误码
    exceptions.py    # CircuitError（错误码 + 人话说明）
    model.py         # 元件/网表数据模型与方向约定
    parser.py        # 网表解析与合法性校验（含电压源回路的并查集检测）
    mna.py           # MNA 矩阵盖章、组装与非奇异性检验、线性求解
    dc.py            # 直流工作点（电容开路、电感短路）
    transient.py     # 后向欧拉时间步进 + C/L 伴随模型
  schemas.py         # HTTP 请求/响应的 Pydantic 契约
  api.py             # 接口层：只转发、封装，不含计算
  main.py            # FastAPI 入口与统一错误处理
tests/               # pytest：分压比、RC 时间常数、初值自洽、各类非法网表
examples/            # 两个可手工核对的算例
```

直流与瞬态共用 `model.py` 里同一套元件方向与初始条件定义，
瞬态的电容/电感伴随模型与直流处理都往同一个 `MNABuilder` 上盖章，
不存在两套互相打架的元件方程。

## 网表格式

```json
{
  "components": [
    {"name": "R1", "type": "R", "nodes": ["vdd", "out"], "value": 1000.0},
    {"name": "C1", "type": "C", "nodes": ["out", "0"],   "value": 1e-6, "ic": 0.0}
  ]
}
```

| type | 元件 | value 单位 | 初始条件 `ic` |
|------|------|-----------|---------------|
| `R` | 电阻 | 欧姆（必须为正，零欧直接报错） | — |
| `C` | 电容 | 法拉（必须为正） | 电容初压（伏特），缺省 0 |
| `L` | 电感 | 亨利（必须为正） | 电感初流（安培），缺省 0 |
| `V` | 独立电压源 | 伏特 | — |
| `I` | 独立电流源 | 安培 | — |

类型也接受中文/全称（`电阻`、`capacitor`、`电压源` 等）。

**方向约定（p = nodes[0]，n = nodes[1]）**

- 电压源：`value = V(p) - V(n)`；支路电流以**流入 p 端为正**（SPICE 约定，电源向电路供电时为负）。
- 电流源：正的 `value` 表示向 p 节点注入电流、从 n 节点抽走。
- 电容：端压 `v_C = V(p) - V(n)`，`ic = v_C(0)`。
- 电感：电流 p → n 方向为正，`ic = i_L(0)`。

接地参考节点必须恰好存在一个，名为 `0` 或 `gnd`（两者等价，输出统一为 `0`），电位钉死为零。

## 接口

### `POST /dc` — 直流工作点

请求体就是上面的网表。响应：

```json
{
  "success": true,
  "node_voltages": {"0": 0.0, "out": 2.5, "vdd": 5.0},
  "voltage_source_currents": {"V1": -0.0025},
  "inductor_currents": {}
}
```

直流下电容开路、电感短路（0V 电压源支路）。`ic` 是瞬态初始条件，不改变直流稳态。

### `POST /transient` — 瞬态波形

网表之外再加 `dt`（秒，必须为正）与 `tstop`（秒，至少一个 dt）：

```json
{
  "components": [ ... ],
  "dt": 0.00005,
  "tstop": 0.005
}
```

响应给出与时间轴对齐的各节点电压序列（够在别处画曲线）：

```json
{
  "success": true,
  "method": "backward_euler",
  "dt": 5e-05, "tstop": 0.005, "steps": 100,
  "times": [0.0, 5e-05, ...],
  "node_voltages": {"0": [0.0, ...], "cap": [0.0, 0.238, ...]}
}
```

**数值方法。** 定步长后向欧拉，每步把储能元件替换成伴随模型后重解一次 MNA：

- 电容：等效电导 `G_C = C/dt`，并联历史电流源 `(C/dt)·v_C^n`（向 p 注入）；
- 电感：等效电导 `G_L = dt/L`，并联历史电流源 `i_L^n`（从 p 抽走）。

矩阵 `A` 对线性定常网络不随时间变化，只组装一次并做一次奇异性检验，每步更新右端向量。

**初始时刻（t=0）。** 电容替换成值为 `ic` 的电压源、电感替换成值为 `ic` 的电流源，
与其余元件一起解一次 MNA，因此 t=0 的节点电压与给定初值严格自洽，第一步不会突跳。

参数限制：步数上限 `MAX_STEPS = 20000`。

### 错误响应

任何网表非法、矩阵奇异、参数越界都返回 HTTP 422：

```json
{"success": false, "error_code": "ZERO_RESISTANCE", "message": "电阻 R1 的阻值为零；……"}
```

| error_code | 触发情形 |
|---|---|
| `UNKNOWN_COMPONENT_TYPE` | 不认识的元件类型 |
| `MISSING_NODES` | 元件缺必需节点 / 节点数不是 2 / 空节点名 |
| `MISSING_NAME` / `MISSING_VALUE` | 元件缺名称或参数值 |
| `NO_GROUND` | 整张网找不到接地参考 |
| `ZERO_RESISTANCE` | 电阻取值为零 |
| `DUPLICATE_NAME` | 两个元件重名 |
| `VOLTAGE_SOURCE_LOOP` | 理想电压源首尾围成回路（含并联、自环） |
| `INVALID_VALUE` | 非数值 / NaN / Inf / 负电阻 / 非正的 C、L |
| `SINGULAR_MATRIX` | 系数矩阵奇异（悬浮节点、电压源回路、无直流通路等） |
| `INVALID_DT` | dt 不为正或不是有限数 |
| `INVALID_TSTOP` | tstop 小于一个 dt |
| `TOO_MANY_STEPS` | 总步数超过 20000 |

矩阵奇异用 SVD 检查最小奇异值相对量级判定，再以一次实际求解和结果有限性兜底，
不会返回 NaN 或无穷大。

## 手工核对算例

**1. 电阻串联分压**（`examples/voltage_divider.json`，打 `/dc`）

5V 串两个 1kΩ：`V(out) = 5 × 1000/(1000+1000) = 2.5V`，电源电流 `-2.5mA`。

**2. RC 充电**（`examples/rc_charge.json`，打 `/transient`）

5V → 1kΩ → 1µF：时间常数 `τ = RC = 1ms`，`dt=0.05ms` 推到 `tstop=5ms`。
末端 `V_C = 5(1-e^{-5}) ≈ 4.966V`（约电源 99.3%），穿越 `(1-1/e)` 比例的时刻与 τ 吻合。

```bash
curl -s localhost:8000/dc -H 'Content-Type: application/json' \
  --data @examples/voltage_divider.json
curl -s localhost:8000/transient -H 'Content-Type: application/json' \
  --data @examples/rc_charge.json
```

## 本地运行与测试

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000   # 服务
python -m pytest                            # 全部自动化测试
```

测试逐条钉死（不依赖肉眼看波形）：

- 分压网络节点电位比 == 手算分压比（相对误差 1e-10）；
- RC 末端逼近比例正确，且穿越 `(1-1/e)` 的时间 ∈ `[τ, τ+2dt]`，
  整条曲线位于精确指数曲线下方（BE 的数值阻尼特性）；
- 电容非零初压：`v(0) == ic`，第一步严格等于 BE 单步解析式，无突跳；
- 规格列出的每一类非法网表都返回对应错误码；
- dt / tstop 非法、步数超限、矩阵奇异都被挡回。

## Docker

```bash
docker build -t circuit-solver .
docker run --rm -p 8000:8000 circuit-solver
# 起来后：
curl -s localhost:8000/health
```

镜像固定基于 `python:3.12-slim`，容器启动即提供接口。
