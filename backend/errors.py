"""后端异常。前端只需捕获 BackendError 就能拿到可直接展示给用户的消息。"""

from __future__ import annotations


class BackendError(Exception):
    """所有可预期的业务错误的基类，message 直接面向用户。"""


class ValidationError(BackendError):
    """入参不合法，比如设备名为空、U 数为 0。"""


class ConflictError(BackendError):
    """U 位重叠、编号重复这类冲突。"""


class NotFoundError(BackendError):
    """引用的机房 / 机柜 / 设备不存在。"""
