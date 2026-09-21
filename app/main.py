"""FastAPI 应用入口：挂载路由、统一错误响应格式。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import router
from .circuit import CircuitError, ErrorCode
from .schemas import ErrorOut

app = FastAPI(
    title="电路直流工作点与瞬态仿真服务",
    version="1.0.0",
    description=(
        "接收文本式网表，在服务端完成修正节点分析与后向欧拉瞬态积分。\n\n"
        "- POST /dc：直流工作点\n"
        "- POST /transient：定步长瞬态波形\n\n"
        "所有网表非法、矩阵奇异、参数越界都返回统一的错误码 + 说明。"
    ),
)

app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(CircuitError)
async def circuit_error_handler(request: Request, exc: CircuitError) -> JSONResponse:
    """领域错误：网表非法、矩阵奇异、参数越界等，统一 422。"""
    _ = request
    body = ErrorOut(error_code=exc.code, message=exc.message).model_dump()
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """请求体本身不符合契约（缺字段、类型错）时，也包装成同一套错误格式。"""
    _ = request
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        detail = first.get("msg", "请求参数不合法")
        message = f"请求体校验失败（{loc}）：{detail}" if loc else f"请求体校验失败：{detail}"
    else:
        message = "请求体校验失败"
    body = ErrorOut(error_code=ErrorCode.INVALID_VALUE, message=message).model_dump()
    return JSONResponse(status_code=422, content=body)
