"""租户成员与企业拥有者/管理员模型（ADR-001）。

- biz_tenant_member：账号在某企业中的成员身份，(tenant_id, user_id) 唯一（替代 B0 的 user_id 单列唯一）；
- biz_tenant_owner：每租户恰好一条有效所有权记录（tenant_id 唯一＋version 乐观锁），
  只能经开通初始化或专门移交变更，不出现在普通授权列表；
- biz_tenant_admin / biz_tenant_admin_permission：企业管理员及其独立可委托权限授予。
严禁把租户角色或项目角色写入平台原生 sys_user_roles。
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import TenantModelMixin, UserMixin

if TYPE_CHECKING:
    from app.modules.system.user.model import UserModel


class BizTenantMemberModel(TenantModelMixin, UserMixin):
    """租户成员表（统一账号 sys_user 在某企业中的成员身份）。"""

    __tablename__: str = "biz_tenant_member"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_biz_tenant_member_tenant_user"),
        {"comment": "租户成员表"},
    )

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sys_user.id", ondelete="CASCADE"), index=True, nullable=False, comment="登录账号ID"
    )
    emp_no: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, comment="企业内工号")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="成员状态(0:正常 1:停用)")

    user: Mapped["UserModel"] = relationship(foreign_keys=[user_id])


class BizTenantOwnerModel(TenantModelMixin, UserMixin):
    """企业拥有者单持有人记录：tenant_id 唯一＋version 并发控制。

    所有权身份由该记录派生，不在普通角色表中保存可产生多条 Owner 的记录。
    """

    __tablename__: str = "biz_tenant_owner"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_biz_tenant_owner_tenant"),
        {"comment": "企业拥有者单持有人记录表"},
    )

    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("biz_tenant_member.id", ondelete="RESTRICT"), nullable=False, comment="当前企业拥有者成员ID"
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="所有权版本(乐观锁)")

    member: Mapped[BizTenantMemberModel] = relationship(foreign_keys=[member_id])


class BizTenantAdminModel(TenantModelMixin, UserMixin):
    """企业管理员（0~N 名，权限单独授予；当前 Owner 不得作为目标）。"""

    __tablename__: str = "biz_tenant_admin"
    __table_args__ = (
        UniqueConstraint("tenant_id", "member_id", name="uq_biz_tenant_admin_tenant_member"),
        {"comment": "租户企业管理员表"},
    )

    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("biz_tenant_member.id", ondelete="RESTRICT"), index=True, nullable=False, comment="租户成员ID"
    )

    member: Mapped[BizTenantMemberModel] = relationship(foreign_keys=[member_id])


class BizTenantAdminPermissionModel(TenantModelMixin):
    """企业管理员权限授予（仅 delegable 权限；owner_only 永不入此表）。"""

    __tablename__: str = "biz_tenant_admin_permission"
    __table_args__ = (
        UniqueConstraint("admin_id", "permission_code", name="uq_biz_tenant_admin_permission"),
        {"comment": "企业管理员权限授予表"},
    )

    admin_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("biz_tenant_admin.id", ondelete="CASCADE"), index=True, nullable=False, comment="企业管理员ID"
    )
    permission_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="权限标识")
