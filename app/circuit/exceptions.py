"""自定义异常。任何解析或求解阶段的错误都抛 CircuitError，绝不让底层异常崩到接口层。"""

from __future__ import annotations

from .errors import ErrorCode


class CircuitError(Exception):
    """带机器可读错误码和人类可读说明的电路错误。

    Attributes:
        code: ErrorCode 中定义的错误码字符串。
        message: 一句人话说明。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


__all__ = ["CircuitError", "ErrorCode"]
