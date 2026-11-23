"""ADR-001 主迁移的存量映射、回滚安全性与跨方言渲染回归测试。"""

import importlib.util
import io
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import mysql, postgresql, sqlite

_MIGRATION_PATH = Path(__file__).parent.parent / "app/alembic/versions/2026_11_22_1800_e5f6a7b8c9d0.py"
_NOW = datetime(2026, 11, 22, tzinfo=UTC)
_TENANT_INDEX_TABLES = (
    "biz_tenant_owner",
    "biz_tenant_admin",
    "biz_tenant_admin_permission",
    "biz_project",
    "biz_project_member",
    "biz_project_member_hazard",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("adr001_migration_under_test", _MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION = _load_migration()


def _legacy_row(row_id: int, tenant_id: int, user_id: int, *, admin: bool = False, deleted: bool = False) -> dict:
    return {
        "id": row_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "is_enterprise_admin": admin,
        "emp_no": f"E{row_id}",
        "uuid": f"legacy-{row_id}",
        "is_deleted": deleted,
        "created_time": _NOW,
        "updated_time": _NOW,
        "deleted_time": _NOW if deleted else None,
        "created_id": user_id,
        "updated_id": user_id,
        "deleted_id": user_id if deleted else None,
    }


def _create_legacy_schema(engine: sa.Engine, rows: list[dict]) -> None:
    metadata = sa.MetaData()
    enterprise = sa.Table("plat_enterprise", metadata, sa.Column("id", sa.Integer, primary_key=True))
    user = sa.Table("sys_user", metadata, sa.Column("id", sa.Integer, primary_key=True))
    legacy = sa.Table(
        "biz_tenant_user",
        metadata,
        sa.Column("user_id", sa.Integer, sa.ForeignKey("sys_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_enterprise_admin", sa.Boolean, nullable=False),
        sa.Column("emp_no", sa.String(32)),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("plat_enterprise.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(64), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False),
        sa.Column("created_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_time", sa.DateTime(timezone=True)),
        sa.Column("created_id", sa.Integer),
        sa.Column("updated_id", sa.Integer),
        sa.Column("deleted_id", sa.Integer),
        sa.Index("ix_biz_tenant_user_user_id", "user_id", unique=True),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(enterprise.insert(), [{"id": tenant_id} for tenant_id in sorted({row["tenant_id"] for row in rows} | {1, 2, 3, 4, 5})])
        conn.execute(user.insert(), [{"id": user_id} for user_id in sorted({row["user_id"] for row in rows} | {141, 142})])
        if rows:
            conn.execute(legacy.insert(), rows)


def _upgrade(conn: sa.Connection) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        _MIGRATION.upgrade()


def _downgrade(conn: sa.Connection) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        _MIGRATION.downgrade()


def _insert_member_without_id(conn: sa.Connection, *, tenant_id: int, user_id: int, uuid: str) -> int:
    conn.execute(
        sa.text(
            "INSERT INTO biz_tenant_member (user_id, emp_no, status, tenant_id, uuid, is_deleted, created_time, updated_time)"
            " VALUES (:user_id, NULL, 0, :tenant_id, :uuid, FALSE, :now, :now)"
        ),
        {"user_id": user_id, "tenant_id": tenant_id, "uuid": uuid, "now": _NOW},
    )
    return conn.execute(sa.text("SELECT id FROM biz_tenant_member WHERE uuid = :uuid"), {"uuid": uuid}).scalar_one()


def test_owner_and_admin_mapping_covers_legacy_member_shapes(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path}/owner_mapping.db")
    try:
        rows = [
            # tenant=1：无成员。
            # tenant=2：只有非 admin，最早有效成员必须补为 Owner。
            _legacy_row(20, 2, 120),
            _legacy_row(21, 2, 121),
            # tenant=3：多 admin，最早者为 Owner，且不得同时成为普通 Admin。
            _legacy_row(30, 3, 130, admin=True),
            _legacy_row(31, 3, 131, admin=True),
            # tenant=4：只有软删 admin，没有有效成员，保持无 Owner/Admin。
            _legacy_row(40, 4, 140, admin=True, deleted=True),
            # tenant=5：软删 admin 不参与选择，回退到有效非 admin 成员。
            _legacy_row(50, 5, 150, admin=True, deleted=True),
            _legacy_row(51, 5, 151),
        ]
        _create_legacy_schema(engine, rows)
        with engine.begin() as conn:
            _upgrade(conn)
            owners = conn.execute(sa.text("SELECT tenant_id, member_id FROM biz_tenant_owner ORDER BY tenant_id")).mappings().all()
            assert [(row["tenant_id"], row["member_id"]) for row in owners] == [(2, 20), (3, 30), (5, 51)]

            admins = conn.execute(sa.text("SELECT tenant_id, member_id FROM biz_tenant_admin ORDER BY tenant_id, member_id")).mappings().all()
            assert [(row["tenant_id"], row["member_id"]) for row in admins] == [(3, 31)]
            permissions = conn.execute(
                sa.text(
                    "SELECT permission_code FROM biz_tenant_admin_permission"
                    " WHERE admin_id IN (SELECT id FROM biz_tenant_admin WHERE member_id = 31) ORDER BY permission_code"
                )
            ).scalars().all()
            assert set(permissions) == set(_MIGRATION._DELEGABLE)
            assert conn.execute(sa.text("SELECT is_deleted FROM biz_tenant_member WHERE id = 40")).scalar_one() == 1
            assert conn.execute(sa.text("SELECT is_deleted FROM biz_tenant_member WHERE id = 50")).scalar_one() == 1
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_restore_all_declared_indexes(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path}/indexes.db")
    try:
        _create_legacy_schema(engine, [_legacy_row(10, 1, 110, admin=True)])
        with engine.begin() as conn:
            _upgrade(conn)
            inspector = sa.inspect(conn)
            for table in _TENANT_INDEX_TABLES:
                index_names = {index["name"] for index in inspector.get_indexes(table)}
                assert f"ix_{table}_tenant_id" in index_names

            _downgrade(conn)
            inspector = sa.inspect(conn)
            legacy_indexes = {index["name"] for index in inspector.get_indexes("biz_tenant_user")}
            assert {
                "ix_biz_tenant_user_created_id",
                "ix_biz_tenant_user_updated_id",
                "ix_biz_tenant_user_deleted_id",
                "ix_biz_tenant_user_tenant_id",
                "ix_biz_tenant_user_user_id",
            } <= legacy_indexes
            assert "biz_tenant_member" not in inspector.get_table_names()
    finally:
        engine.dispose()


def test_downgrade_rejects_multi_tenant_user_before_any_ddl(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path}/downgrade_conflict.db")
    try:
        _create_legacy_schema(engine, [_legacy_row(10, 1, 160), _legacy_row(11, 2, 161)])
        with engine.begin() as conn:
            _upgrade(conn)
            _insert_member_without_id(conn, tenant_id=2, user_id=160, uuid="cross-tenant-duplicate")
            assert conn.execute(sa.text("SELECT COUNT(*) FROM biz_tenant_member WHERE user_id = 160")).scalar_one() == 2

            with pytest.raises(RuntimeError, match=r"downgrade 不可逆.*user_id=160"):
                _downgrade(conn)

            inspector = sa.inspect(conn)
            assert "biz_tenant_user" not in inspector.get_table_names()
            assert "biz_tenant_member" in inspector.get_table_names()
            assert conn.execute(sa.text("SELECT COUNT(*) FROM biz_tenant_member")).scalar_one() == 3
    finally:
        engine.dispose()


def test_roundtrip_maps_disabled_to_soft_delete_and_new_ids_advance(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path}/roundtrip.db")
    try:
        _create_legacy_schema(engine, [_legacy_row(40, 1, 140)])
        with engine.begin() as conn:
            _upgrade(conn)
            conn.execute(sa.text("UPDATE biz_tenant_member SET status = 1 WHERE id = 40"))
            # SQLite 的 rowid 路径验证显式 id 搬迁后新增一行不会撞既有主键。
            assert _insert_member_without_id(conn, tenant_id=1, user_id=141, uuid="after-upgrade") == 41
            _downgrade(conn)

            restored = conn.execute(
                sa.text("SELECT id, is_deleted FROM biz_tenant_user ORDER BY id")
            ).mappings().all()
            assert [(row["id"], row["is_deleted"]) for row in restored] == [(40, 1), (41, 0)]

            conn.execute(
                sa.text(
                    "INSERT INTO biz_tenant_user (user_id, is_enterprise_admin, emp_no, tenant_id, uuid, is_deleted, created_time, updated_time)"
                    " VALUES (142, FALSE, NULL, 1, 'after-downgrade', FALSE, :now, :now)"
                ),
                {"now": _NOW},
            )
            new_id = conn.execute(sa.text("SELECT id FROM biz_tenant_user WHERE uuid = 'after-downgrade'")).scalar_one()
            assert new_id == 42
    finally:
        engine.dispose()


class _Result:
    def __init__(self, rows: list[dict] | None = None, scalar: int | None = None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self) -> list[dict]:
        return self._rows

    def first(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> int | None:
        return self._scalar


class _DataSqlBind:
    """执行主迁移的数据分支并记录 SQL，不需要真实 PostgreSQL 服务。"""

    dialect = postgresql.dialect()

    def __init__(self) -> None:
        self.statements: list[sa.TextClause] = []

    def execute(self, statement: sa.TextClause, _parameters: dict | None = None) -> _Result:
        self.statements.append(statement)
        sql = str(statement)
        if sql.startswith("SELECT tenant_id, MIN(id)"):
            return _Result(rows=[{"tenant_id": 1, "member_id": 10}])
        if sql.startswith("SELECT id, tenant_id FROM biz_tenant_user"):
            return _Result(rows=[{"id": 10, "tenant_id": 1}, {"id": 11, "tenant_id": 1}])
        if sql.startswith("INSERT INTO biz_tenant_admin "):
            return _Result(scalar=99)
        return _Result()


def test_data_sql_uses_boolean_literals_and_compiles_on_all_dialects(monkeypatch) -> None:
    bind = _DataSqlBind()
    monkeypatch.setattr(_MIGRATION.op, "get_bind", lambda: bind)
    for helper in ("_create_member", "_create_owner_admin", "_create_project", "_create_audit", "_create_legacy_binding"):
        monkeypatch.setattr(_MIGRATION, helper, lambda: None)
    monkeypatch.setattr(_MIGRATION.op, "drop_table", lambda _table: None)

    _MIGRATION.upgrade()
    _MIGRATION.downgrade()
    sql = "\n".join(str(statement) for statement in bind.statements)
    assert "WHERE is_deleted = FALSE" in sql
    assert "is_enterprise_admin = TRUE AND is_deleted = FALSE" in sql
    assert "VALUES (:mid, 1, :tid, :uuid, FALSE, :now, :now)" in sql
    assert "VALUES (:mid, :tid, :uuid, FALSE, :now, :now)" in sql
    assert "THEN TRUE ELSE FALSE END" in sql
    assert "CASE WHEN biz_tenant_member.status = 1 THEN TRUE ELSE biz_tenant_member.is_deleted END" in sql
    assert "is_enterprise_admin = 1" not in sql
    assert "is_deleted = 0" not in sql
    assert "THEN 1 ELSE 0" not in sql
    assert ":uuid, 0," not in sql

    for statement in bind.statements:
        for dialect in (sqlite.dialect(), mysql.dialect(), postgresql.dialect()):
            assert str(statement.compile(dialect=dialect))


@pytest.mark.parametrize("dialect_name", ["sqlite", "mysql", "postgresql"])
def test_table_ddl_renders_offline(dialect_name: str) -> None:
    output = io.StringIO()
    urls = {"sqlite": "sqlite://", "mysql": "mysql+pymysql://", "postgresql": "postgresql+psycopg://"}

    def render(statement, *_args, **_kwargs) -> None:
        compiled = statement.compile(dialect=engine.dialect) if hasattr(statement, "compile") else statement
        output.write(f"{compiled};\n")

    engine = sa.create_mock_engine(urls[dialect_name], render)
    context = MigrationContext.configure(engine)
    with Operations.context(context):
        _MIGRATION._create_member()
        _MIGRATION._create_owner_admin()
        _MIGRATION._create_project()
        _MIGRATION._create_audit()
        _MIGRATION._create_legacy_binding()

    ddl = output.getvalue()
    assert "CREATE TABLE biz_tenant_member" in ddl
    assert "CREATE TABLE biz_tenant_owner" in ddl
    assert "CREATE TABLE biz_tenant_user" in ddl
    for table in _TENANT_INDEX_TABLES:
        assert f"ix_{table}_tenant_id" in ddl
    assert "ix_biz_tenant_user_updated_id" in ddl


def test_postgresql_sequence_sync_handles_nonempty_and_empty_tables() -> None:
    for table in ("biz_tenant_member", "biz_tenant_user"):
        bind = Mock()
        bind.dialect.name = "postgresql"
        _MIGRATION._sync_postgresql_sequence(bind, table)
        statement = bind.execute.call_args.args[0]
        rendered = str(statement.compile(dialect=postgresql.dialect()))
        assert f"pg_get_serial_sequence('{table}', 'id')" in rendered
        assert f"COALESCE((SELECT MAX(id) FROM {table}), 1)" in rendered
        # 第三参数 false（空表）使序列不推进，下一次 nextval 仍返回 1。
        assert f"EXISTS (SELECT 1 FROM {table})" in rendered
