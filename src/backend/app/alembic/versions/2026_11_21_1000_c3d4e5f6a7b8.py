"""B0 多租户底座：监理企业租户主表与租户用户绑定表

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-11-21 10:00:00

平台域「开通租户」最小表空间：
- ``plat_enterprise``：监理企业租户主表（平台域，无 tenant_id；status 1正常/0冻结，与 sys_user 相反）；
- ``biz_tenant_user``：租户用户绑定（TenantModelMixin，tenant_id 行级隔离；user_id 唯一 → 一人一租户）。
约束命名走 NAMING_CONVENTION/op.f，跨 SQLite/MySQL/PG 可渲染。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plat_enterprise",
        sa.Column("enterprise_code", sa.String(length=32), nullable=False, comment="企业编码(ENT-xxx)"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="企业名称"),
        sa.Column("credit_code", sa.String(length=64), nullable=True, comment="统一社会信用代码"),
        sa.Column("status", sa.Integer(), nullable=False, comment="状态(1:正常 0:冻结)"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plat_enterprise")),
        comment="监理企业租户表",
    )
    with op.batch_alter_table("plat_enterprise", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_plat_enterprise_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_plat_enterprise_credit_code"), ["credit_code"], unique=True)
        batch_op.create_index(batch_op.f("ix_plat_enterprise_enterprise_code"), ["enterprise_code"], unique=True)
        batch_op.create_index(batch_op.f("ix_plat_enterprise_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_plat_enterprise_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_plat_enterprise_uuid"), ["uuid"], unique=True)

    op.create_table(
        "biz_tenant_user",
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID(一人一租户)"),
        sa.Column("is_enterprise_admin", sa.Boolean(), nullable=False, comment="是否企业管理员"),
        sa.Column("emp_no", sa.String(length=32), nullable=True, comment="工号"),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False, comment="所属监理企业租户ID"),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
        sa.Column("created_id", sa.Integer(), nullable=True, comment="创建人ID"),
        sa.Column("updated_id", sa.Integer(), nullable=True, comment="更新人ID"),
        sa.Column("deleted_id", sa.Integer(), nullable=True, comment="删除人ID"),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_tenant_user_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"], name=op.f("fk_biz_tenant_user_user_id_sys_user"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_tenant_user")),
        comment="租户用户绑定表",
    )
    with op.batch_alter_table("biz_tenant_user", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_created_id"), ["created_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_created_time"), ["created_time"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_deleted_id"), ["deleted_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_tenant_id"), ["tenant_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_updated_id"), ["updated_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_user_id"), ["user_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_uuid"), ["uuid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("biz_tenant_user", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_uuid"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_user_id"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_updated_id"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_tenant_id"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_id"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_deleted_id"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_created_time"))
        batch_op.drop_index(batch_op.f("ix_biz_tenant_user_created_id"))
    op.drop_table("biz_tenant_user")
    with op.batch_alter_table("plat_enterprise", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plat_enterprise_uuid"))
        batch_op.drop_index(batch_op.f("ix_plat_enterprise_is_deleted"))
        batch_op.drop_index(batch_op.f("ix_plat_enterprise_id"))
        batch_op.drop_index(batch_op.f("ix_plat_enterprise_enterprise_code"))
        batch_op.drop_index(batch_op.f("ix_plat_enterprise_credit_code"))
        batch_op.drop_index(batch_op.f("ix_plat_enterprise_created_time"))
    op.drop_table("plat_enterprise")
