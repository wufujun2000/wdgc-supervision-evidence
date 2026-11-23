"""ADR-001 身份权限体系：租户成员/单持有人 Owner/Admin 授权/项目任命

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-22 18:00:00

- biz_tenant_user → biz_tenant_member（改名重建保留存量；(tenant_id,user_id) 唯一，加 status）
- 新增 biz_tenant_owner（单持有人＋version）、biz_tenant_admin(+permission)、
  biz_project、biz_project_member(+hazard)、plat_owner_transfer_audit
- 存量映射：is_enterprise_admin=True → Admin＋全部 delegable 权限；每租户最早有效成员 → 初始 Owner，
  初始 Owner 不重复写 Admin；无有效成员的租户保持无 Owner，由平台补设
- 全部按 ModelMixin/NAMING_CONVENTION 命名，跨 SQLite/MySQL/PG 可渲染；
  单账号单成员状态支持 downgrade，多租户成员冲突在任何 DDL 前明确拒绝
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = datetime(2026, 11, 22, tzinfo=UTC)
_DELEGABLE = ("tenant_member_manage", "tenant_admin_manage", "project_manage", "project_member_assign")


def _uuid(key: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"wdgc:adr001:{key}").hex


def _mixin_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("uuid", sa.String(length=64), nullable=False, comment="UUID全局唯一标识"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, comment="是否已删除(0:未删除 1:已删除)"),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False, comment="创建时间"),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False, comment="更新时间"),
        sa.Column("deleted_time", sa.DateTime(timezone=True), nullable=True, comment="删除时间"),
    ]


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_id", sa.Integer(), nullable=True, comment="创建人ID"),
        sa.Column("updated_id", sa.Integer(), nullable=True, comment="更新人ID"),
        sa.Column("deleted_id", sa.Integer(), nullable=True, comment="删除人ID"),
    ]


def _std_indexes(table: str, audit: bool = False) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(f"ix_{table}_id"), ["id"], unique=False)
        batch_op.create_index(batch_op.f(f"ix_{table}_uuid"), ["uuid"], unique=True)
        batch_op.create_index(batch_op.f(f"ix_{table}_is_deleted"), ["is_deleted"], unique=False)
        batch_op.create_index(batch_op.f(f"ix_{table}_created_time"), ["created_time"], unique=False)
        if audit:
            # UserMixin 审计列索引（与基线 biz_tenant_user 先例一致）
            batch_op.create_index(batch_op.f(f"ix_{table}_created_id"), ["created_id"], unique=False)
            batch_op.create_index(batch_op.f(f"ix_{table}_updated_id"), ["updated_id"], unique=False)
            batch_op.create_index(batch_op.f(f"ix_{table}_deleted_id"), ["deleted_id"], unique=False)


def _sync_postgresql_sequence(bind: sa.Connection, table: str) -> None:
    """显式搬迁 id 后推进 PG 序列；空表重置为 1 且下一次仍返回 1。"""
    if bind.dialect.name != "postgresql":
        return
    # table 仅由本迁移中的两个字面量调用，不能作为参数绑定进 FROM/标识符位置。
    bind.execute(
        sa.text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"
            f" COALESCE((SELECT MAX(id) FROM {table}), 1),"
            f" EXISTS (SELECT 1 FROM {table}))"
        )
    )


def _create_member() -> None:
    op.create_table(
        "biz_tenant_member",
        sa.Column("user_id", sa.Integer(), nullable=False, comment="登录账号ID"),
        sa.Column("emp_no", sa.String(length=32), nullable=True, comment="企业内工号"),
        sa.Column("status", sa.Integer(), nullable=False, comment="成员状态(0:正常 1:停用)"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_tenant_member")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_tenant_member_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"], name=op.f("fk_biz_tenant_member_user_id_sys_user"), ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_biz_tenant_member_tenant_user"),
        comment="租户成员表",
    )
    _std_indexes("biz_tenant_member", audit=True)
    with op.batch_alter_table("biz_tenant_member", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_tenant_member_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_member_tenant_id"), ["tenant_id"], unique=False)


def _create_owner_admin() -> None:
    op.create_table(
        "biz_tenant_owner",
        sa.Column("member_id", sa.Integer(), nullable=False, comment="当前企业拥有者成员ID"),
        sa.Column("version", sa.Integer(), nullable=False, comment="所有权版本(乐观锁)"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_tenant_owner")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_tenant_owner_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["biz_tenant_member.id"], name=op.f("fk_biz_tenant_owner_member_id_biz_tenant_member"), ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", name="uq_biz_tenant_owner_tenant"),
        comment="企业拥有者单持有人记录表",
    )
    _std_indexes("biz_tenant_owner", audit=True)
    with op.batch_alter_table("biz_tenant_owner", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_tenant_owner_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "biz_tenant_admin",
        sa.Column("member_id", sa.Integer(), nullable=False, comment="租户成员ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_tenant_admin")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_tenant_admin_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["biz_tenant_member.id"], name=op.f("fk_biz_tenant_admin_member_id_biz_tenant_member"), ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "member_id", name="uq_biz_tenant_admin_tenant_member"),
        comment="租户企业管理员表",
    )
    _std_indexes("biz_tenant_admin", audit=True)
    with op.batch_alter_table("biz_tenant_admin", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_tenant_admin_member_id"), ["member_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_admin_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "biz_tenant_admin_permission",
        sa.Column("admin_id", sa.Integer(), nullable=False, comment="企业管理员ID"),
        sa.Column("permission_code", sa.String(length=64), nullable=False, comment="权限标识"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_tenant_admin_permission")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_tenant_admin_permission_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["admin_id"], ["biz_tenant_admin.id"], name=op.f("fk_biz_tenant_admin_permission_admin_id_biz_tenant_admin"), ondelete="CASCADE"),
        sa.UniqueConstraint("admin_id", "permission_code", name="uq_biz_tenant_admin_permission"),
        comment="企业管理员权限授予表",
    )
    _std_indexes("biz_tenant_admin_permission")
    with op.batch_alter_table("biz_tenant_admin_permission", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_tenant_admin_permission_admin_id"), ["admin_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_tenant_admin_permission_tenant_id"), ["tenant_id"], unique=False)


def _create_project() -> None:
    op.create_table(
        "biz_project",
        sa.Column("project_code", sa.String(length=32), nullable=False, comment="项目编码"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="项目名称"),
        sa.Column("status", sa.Integer(), nullable=False, comment="项目状态(0:正常 1:停用)"),
        sa.Column("description", sa.Text(), nullable=True, comment="项目描述"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_project")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_project_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "project_code", name="uq_biz_project_tenant_code"),
        comment="租户项目表",
    )
    _std_indexes("biz_project", audit=True)
    with op.batch_alter_table("biz_project", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_project_project_code"), ["project_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_project_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "biz_project_member",
        sa.Column("project_id", sa.Integer(), nullable=False, comment="项目ID"),
        sa.Column("member_id", sa.Integer(), nullable=False, comment="租户成员ID"),
        sa.Column("role_code", sa.String(length=8), nullable=False, comment="项目角色(SZ:总监 SP:专监 SA:监理员)"),
        sa.Column("status", sa.Integer(), nullable=False, comment="任命状态(0:在任 1:卸任)"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_project_member")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_project_member_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["biz_project.id"], name=op.f("fk_biz_project_member_project_id_biz_project"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["biz_tenant_member.id"], name=op.f("fk_biz_project_member_member_id_biz_tenant_member"), ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "member_id", name="uq_biz_project_member_project_member"),
        comment="项目成员任命表",
    )
    _std_indexes("biz_project_member", audit=True)
    with op.batch_alter_table("biz_project_member", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_project_member_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_project_member_member_id"), ["member_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_project_member_tenant_id"), ["tenant_id"], unique=False)

    op.create_table(
        "biz_project_member_hazard",
        sa.Column("project_member_id", sa.Integer(), nullable=False, comment="项目成员任命ID"),
        sa.Column("hazard_code", sa.String(length=2), nullable=False, comment="危大类别编码(01~12)"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_project_member_hazard")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_project_member_hazard_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_member_id"], ["biz_project_member.id"], name=op.f("fk_biz_project_member_hazard_project_member_id_biz_project_member"), ondelete="CASCADE"),
        sa.UniqueConstraint("project_member_id", "hazard_code", name="uq_biz_project_member_hazard"),
        comment="专监危大类别负责范围表",
    )
    _std_indexes("biz_project_member_hazard")
    with op.batch_alter_table("biz_project_member_hazard", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_project_member_hazard_project_member_id"), ["project_member_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_biz_project_member_hazard_tenant_id"), ["tenant_id"], unique=False)


def _create_audit() -> None:
    op.create_table(
        "plat_owner_transfer_audit",
        sa.Column("source", sa.String(length=16), nullable=False, comment="发起来源(platform:平台 tenant:租户)"),
        sa.Column("operator_user_id", sa.Integer(), nullable=True, comment="操作人账号ID"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="目标租户ID"),
        sa.Column("from_member_id", sa.Integer(), nullable=True, comment="原企业拥有者成员ID(初始化/补设为空)"),
        sa.Column("to_member_id", sa.Integer(), nullable=False, comment="新企业拥有者成员ID"),
        sa.Column("reason", sa.Text(), nullable=False, comment="移交/初始化原因"),
        sa.Column("result", sa.String(length=16), nullable=False, comment="结果(success/failed)"),
        *_mixin_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plat_owner_transfer_audit")),
        comment="企业拥有者移交审计表",
    )
    _std_indexes("plat_owner_transfer_audit")
    with op.batch_alter_table("plat_owner_transfer_audit", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_plat_owner_transfer_audit_operator_user_id"), ["operator_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_plat_owner_transfer_audit_tenant_id"), ["tenant_id"], unique=False)


def _create_legacy_binding() -> None:
    """downgrade 用：还原 B0 biz_tenant_user 结构（user_id 单列唯一）。"""
    op.create_table(
        "biz_tenant_user",
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID(一人一租户)"),
        sa.Column("is_enterprise_admin", sa.Boolean(), nullable=False, comment="是否企业管理员"),
        sa.Column("emp_no", sa.String(length=32), nullable=True, comment="工号"),
        sa.Column("tenant_id", sa.Integer(), nullable=False, comment="所属监理企业租户ID"),
        *_mixin_columns(),
        *_audit_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_biz_tenant_user")),
        sa.ForeignKeyConstraint(["tenant_id"], ["plat_enterprise.id"], name=op.f("fk_biz_tenant_user_tenant_id_plat_enterprise"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"], name=op.f("fk_biz_tenant_user_user_id_sys_user"), ondelete="CASCADE"),
        comment="租户用户绑定表",
    )
    _std_indexes("biz_tenant_user", audit=True)
    with op.batch_alter_table("biz_tenant_user", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_user_id"), ["user_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_biz_tenant_user_tenant_id"), ["tenant_id"], unique=False)


def upgrade() -> None:
    _create_member()
    _create_owner_admin()
    _create_project()
    _create_audit()

    bind = op.get_bind()
    # 1. 存量成员整体搬迁（含软删历史行）
    bind.execute(
        sa.text(
            "INSERT INTO biz_tenant_member (user_id, emp_no, status, tenant_id, id, uuid, is_deleted,"
            " created_time, updated_time, deleted_time, created_id, updated_id, deleted_id)"
            " SELECT user_id, emp_no, 0, tenant_id, id, uuid, is_deleted,"
            " created_time, updated_time, deleted_time, created_id, updated_id, deleted_id FROM biz_tenant_user"
        )
    )
    _sync_postgresql_sequence(bind, "biz_tenant_member")

    # 2. 每租户最早有效成员 → 初始 Owner（version=1）；没有有效成员的租户留给平台补设。
    owner_rows = bind.execute(
        sa.text(
            "SELECT tenant_id, MIN(id) AS member_id FROM biz_tenant_user"
            " WHERE is_deleted = FALSE GROUP BY tenant_id"
        )
    ).mappings().all()
    owner_member_ids = {row["member_id"] for row in owner_rows}
    for row in owner_rows:
        bind.execute(
            sa.text(
                "INSERT INTO biz_tenant_owner (member_id, version, tenant_id, uuid, is_deleted,"
                " created_time, updated_time) VALUES (:mid, 1, :tid, :uuid, FALSE, :now, :now)"
            ),
            {"mid": row["member_id"], "tid": row["tenant_id"], "uuid": _uuid(f"owner:{row['tenant_id']}"), "now": _NOW},
        )

    # 3. 有效 admin 成员 → Admin＋全部 delegable 权限；初始 Owner 不进入普通授权列表。
    admin_rows = bind.execute(
        sa.text(
            "SELECT id, tenant_id FROM biz_tenant_user"
            " WHERE is_enterprise_admin = TRUE AND is_deleted = FALSE ORDER BY tenant_id, id"
        )
    ).mappings().all()
    for row in admin_rows:
        if row["id"] in owner_member_ids:
            continue
        result = bind.execute(
            sa.text(
                "INSERT INTO biz_tenant_admin (member_id, tenant_id, uuid, is_deleted, created_time, updated_time)"
                " VALUES (:mid, :tid, :uuid, FALSE, :now, :now) RETURNING id"
            )
            if bind.dialect.name == "postgresql"
            else sa.text(
                "INSERT INTO biz_tenant_admin (member_id, tenant_id, uuid, is_deleted, created_time, updated_time)"
                " VALUES (:mid, :tid, :uuid, FALSE, :now, :now)"
            ),
            {"mid": row["id"], "tid": row["tenant_id"], "uuid": _uuid(f"admin:{row['tenant_id']}:{row['id']}"), "now": _NOW},
        )
        if bind.dialect.name == "postgresql":
            admin_pk = result.scalar_one()
        else:
            admin_pk = bind.execute(sa.text("SELECT id FROM biz_tenant_admin WHERE member_id = :mid"), {"mid": row["id"]}).scalar_one()
        for code in _DELEGABLE:
            bind.execute(
                sa.text(
                    "INSERT INTO biz_tenant_admin_permission (admin_id, permission_code, tenant_id, uuid, is_deleted,"
                    " created_time, updated_time) VALUES (:aid, :code, :tid, :uuid, FALSE, :now, :now)"
                ),
                {"aid": admin_pk, "code": code, "tid": row["tenant_id"], "uuid": _uuid(f"adminperm:{admin_pk}:{code}"), "now": _NOW},
            )

    bind.execute(sa.text("DROP TABLE biz_tenant_user"))


def downgrade() -> None:
    bind = op.get_bind()
    # 旧表 user_id 单列唯一；在任何 DDL 前拒绝会静默丢成员或半回滚的多租户状态。
    duplicate = bind.execute(
        sa.text(
            "SELECT user_id, COUNT(*) AS membership_count FROM biz_tenant_member"
            " GROUP BY user_id HAVING COUNT(*) > 1 ORDER BY user_id"
        )
    ).mappings().first()
    if duplicate:
        raise RuntimeError(
            "ADR-001 downgrade 不可逆："
            f"user_id={duplicate['user_id']} 在 biz_tenant_member 中有 {duplicate['membership_count']} 条成员记录，"
            "legacy biz_tenant_user 的 user_id 单列唯一约束无法无损还原。"
            "请保留当前版本；如必须回滚，请先备份数据库，并将每个冲突账号的额外租户成员归档到独立存储后重试。"
        )

    _create_legacy_binding()
    # 还原成员；停用成员必须成为 legacy 软删记录，避免回滚后恢复为有效绑定。
    bind.execute(
        sa.text(
            "INSERT INTO biz_tenant_user (user_id, is_enterprise_admin, emp_no, tenant_id, id, uuid, is_deleted,"
            " created_time, updated_time, deleted_time, created_id, updated_id, deleted_id)"
            " SELECT user_id,"
            " CASE WHEN EXISTS (SELECT 1 FROM biz_tenant_admin a WHERE a.member_id = biz_tenant_member.id)"
            "      OR EXISTS (SELECT 1 FROM biz_tenant_owner o WHERE o.member_id = biz_tenant_member.id)"
            " THEN TRUE ELSE FALSE END,"
            " emp_no, tenant_id, id, uuid,"
            " CASE WHEN biz_tenant_member.status = 1 THEN TRUE ELSE biz_tenant_member.is_deleted END,"
            " created_time, updated_time, deleted_time,"
            " created_id, updated_id, deleted_id FROM biz_tenant_member"
        )
    )
    _sync_postgresql_sequence(bind, "biz_tenant_user")
    for table in (
        "plat_owner_transfer_audit",
        "biz_project_member_hazard",
        "biz_project_member",
        "biz_project",
        "biz_tenant_admin_permission",
        "biz_tenant_admin",
        "biz_tenant_owner",
        "biz_tenant_member",
    ):
        op.drop_table(table)
