"""租户用户绑定（biz_tenant_user）：开通租户的最小绑定。"""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import TenantModelMixin, UserMixin

if TYPE_CHECKING:
    from app.modules.system.user.model import UserModel


class BizTenantUserModel(TenantModelMixin, UserMixin):
    """租户用户绑定表（开通租户的最小绑定，不做租户侧组织/员工业务）。

    - user_id 唯一索引：一人一租户；
    - 禁止绑定 is_superuser 账号（超管走平台域，后续代管穿透）；
    - 平台侧管理用 CRUDBase＋显式 tenant_id（开通动作本身是平台域），
      租户上下文内的读写走 TenantCRUDBase（TenantUserIsolatedCRUD）。
    """

    __tablename__: str = "biz_tenant_user"
    __table_args__: dict[str, str] = {"comment": "租户用户绑定表"}

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sys_user.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
        comment="用户ID(一人一租户)",
    )
    is_enterprise_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否企业管理员")
    emp_no: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="工号")

    user: Mapped["UserModel"] = relationship(foreign_keys=[user_id])
