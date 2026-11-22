"""平台域审计模型：企业拥有者移交审计（ADR-001，append-only）。"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import ModelMixin


class PlatOwnerTransferAuditModel(ModelMixin):
    """企业拥有者移交审计表（平台域，仅追加，不提供修改/删除）。

    覆盖三条所有权产生/变更路径：开通初始化、平台补设/移交、租户侧移交。
    """

    __tablename__: str = "plat_owner_transfer_audit"
    # 无 status 列：覆盖 ModelMixin 默认的 status 复合索引声明
    __table_args__: dict[str, str] = {"comment": "企业拥有者移交审计表"}

    source: Mapped[str] = mapped_column(String(16), nullable=False, comment="发起来源(platform:平台 tenant:租户)")
    operator_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True, comment="操作人账号ID")
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="目标租户ID")
    from_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="原企业拥有者成员ID(初始化/补设为空)")
    to_member_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="新企业拥有者成员ID")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="移交/初始化原因")
    result: Mapped[str] = mapped_column(String(16), default="success", nullable=False, comment="结果(success/failed)")
