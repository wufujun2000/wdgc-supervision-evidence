"""项目及项目级任命模型（ADR-001）。

项目角色只能按项目任命：同一成员可在不同项目担任何职；
SP（专监）必须绑定危大类别集合，SZ（总监）覆盖项目全部危大，SA（监理员）以本人任务为范围。
任命停用保留历史，不改写历史证据中的当时角色与归属。
"""

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import TenantModelMixin, UserMixin
from app.modules.tenant.member.model import BizTenantMemberModel


class BizProjectModel(TenantModelMixin, UserMixin):
    """租户项目主体（一期只含身份字段，业务字段随新契约后续扩展）。"""

    __tablename__: str = "biz_project"
    __table_args__ = (
        UniqueConstraint("tenant_id", "project_code", name="uq_biz_project_tenant_code"),
        {"comment": "租户项目表"},
    )

    project_code: Mapped[str] = mapped_column(String(32), index=True, nullable=False, comment="项目编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="项目名称")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="项目状态(0:正常 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="项目描述")


class BizProjectMemberModel(TenantModelMixin, UserMixin):
    """项目成员任命（SZ 总监 / SP 专监 / SA 监理员，每成员每项目一条有效任命）。"""

    __tablename__: str = "biz_project_member"
    __table_args__ = (
        UniqueConstraint("project_id", "member_id", name="uq_biz_project_member_project_member"),
        {"comment": "项目成员任命表"},
    )

    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("biz_project.id", ondelete="RESTRICT"), index=True, nullable=False, comment="项目ID"
    )
    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("biz_tenant_member.id", ondelete="RESTRICT"), index=True, nullable=False, comment="租户成员ID"
    )
    role_code: Mapped[str] = mapped_column(String(8), nullable=False, comment="项目角色(SZ:总监 SP:专监 SA:监理员)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="任命状态(0:在任 1:卸任)")

    project: Mapped[BizProjectModel] = relationship(foreign_keys=[project_id])
    member: Mapped[BizTenantMemberModel] = relationship(foreign_keys=[member_id])


class BizProjectMemberHazardModel(TenantModelMixin):
    """专监在指定项目内负责的危大类别集合（01~12）。"""

    __tablename__: str = "biz_project_member_hazard"
    __table_args__ = (
        UniqueConstraint("project_member_id", "hazard_code", name="uq_biz_project_member_hazard"),
        {"comment": "专监危大类别负责范围表"},
    )

    project_member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("biz_project_member.id", ondelete="CASCADE"), index=True, nullable=False, comment="项目成员任命ID"
    )
    hazard_code: Mapped[str] = mapped_column(String(2), nullable=False, comment="危大类别编码(01~12)")
