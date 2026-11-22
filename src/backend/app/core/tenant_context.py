"""请求级租户上下文（B0 多租户底座）。

contextvars 实现：每个请求/任务独立副本，防止 TestClient 复用线程与后台任务串号。
``_authenticate`` 每次请求开头必须先 ``clear()``，认证末尾再 ``set()``。

边界说明：
- 平台域请求（无租户绑定）``tenant_id=None``：TenantCRUDBase 读写一律 fail-closed 拒绝，
  平台域 CRUDBase 与 ORM 兜底钩子均不受影响。
- ``is_impersonated`` / ``impersonator_id`` / ``read_only`` 为平台二期受控代管穿透
  （P-PC-03）预留：本期只落地上下文透传与 TenantCRUDBase 的 read_only 强制，
  签发/核销 API 与审计表不在 B0 范围。
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import ClassVar

from app.common.enums import RET
from app.core.exceptions import CustomException


@dataclass(frozen=True, slots=True)
class TenantRequestContext:
    """当前请求的租户上下文（不可变值对象，认证末尾一次性注入）。"""

    tenant_id: int | None = None
    member_id: int | None = None
    is_impersonated: bool = False
    impersonator_id: int | None = None
    read_only: bool = False

    _current: ClassVar[ContextVar["TenantRequestContext | None"]] = ContextVar("tenant_request_context", default=None)

    @classmethod
    def set(cls, context: "TenantRequestContext") -> None:
        """注入当前请求上下文（仅认证链路调用）。"""
        cls._current.set(context)

    @classmethod
    def clear(cls) -> None:
        """清空上下文（每次认证开头调用，防复用任务串号）。"""
        cls._current.set(None)

    @classmethod
    def get(cls) -> "TenantRequestContext | None":
        """读取当前上下文；未注入返回 None（平台/后台合法场景）。"""
        return cls._current.get()

    @classmethod
    def require_tenant_id(cls) -> int:
        """铁律入口：未设置租户上下文一律抛异常（fail-closed），绝不退化为全表。"""
        context = cls._current.get()
        if context is None or context.tenant_id is None:
            raise CustomException(msg="缺少租户上下文，禁止访问租户数据", code=RET.FORBIDDEN.code)
        return context.tenant_id
