"""B0.1 菜单数据迁移验收：存量库 upgrade 路径（种子轨由 test_tenant_platform_api.TestPlatformMenuSeed 覆盖）。

独立临时 SQLite 库模拟「存量库」：create_all 后无菜单行 → upgrade 插入 → 重复 upgrade 幂等
→ downgrade 精确清除 → 重复 downgrade 安全。字段与 sql/sys_menu.json 种子逐项一致（双轨零漂移）。
"""

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient

from app.core.base_model import MappedBase

_BACKEND_DIR = Path(__file__).parent.parent
_MIGRATION_PATHS = [
    _BACKEND_DIR / "app/alembic/versions/2026_11_22_1000_d4e5f6a7b8c9.py",
    _BACKEND_DIR / "app/alembic/versions/2026_11_22_1900_f6a7b8c9d0e1.py",
]
_SEED_PATH = _BACKEND_DIR / "sql/sys_menu.json"
_BUTTON_ACTIONS = ["create", "detail", "update", "freeze", "unfreeze", "bind", "unbind", "transfer", "audit"]


def _load_migrations():
    modules = []
    for index, path in enumerate(_MIGRATION_PATHS):
        spec = importlib.util.spec_from_file_location(f"menu_migration_{index}", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def _seed_nodes() -> tuple[dict, dict, list[dict]]:
    seed = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    directory = next(n for n in seed if n.get("route_name") == "Platform")
    menu = next(c for c in directory["children"] if c["route_name"] == "PlatformEnterprise")
    return directory, menu, menu["children"]


def _counts(conn) -> tuple[int, int, int]:
    dirs = conn.execute(sa.text("SELECT COUNT(*) FROM sys_menu WHERE route_name='Platform'")).scalar_one()
    menus = conn.execute(sa.text("SELECT COUNT(*) FROM sys_menu WHERE route_name='PlatformEnterprise'")).scalar_one()
    buttons = conn.execute(sa.text("SELECT COUNT(*) FROM sys_menu WHERE permission LIKE 'module_platform:enterprise:%' AND type=3")).scalar_one()
    return dirs, menus, buttons


def test_menu_migration_roundtrip_and_idempotent(test_client: TestClient, tmp_path) -> None:
    # test_client 仅用于保证全部模型注册（metadata 完整）；验证在独立临时库上进行
    engine = sa.create_engine(f"sqlite:///{tmp_path}/menu_migration.db")
    try:
        MappedBase.metadata.create_all(engine)
        migrations = _load_migrations()
        seed_dir, seed_menu, seed_buttons = _seed_nodes()

        with engine.begin() as conn:
            assert _counts(conn) == (0, 0, 0)
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                for migration in migrations:
                    migration.upgrade()
                for migration in migrations:
                    migration.upgrade()  # 幂等：不产生重复行
            assert _counts(conn) == (1, 1, len(_BUTTON_ACTIONS))

            dir_row = conn.execute(sa.text("SELECT * FROM sys_menu WHERE route_name='Platform'")).mappings().one()
            menu_row = conn.execute(sa.text("SELECT * FROM sys_menu WHERE route_name='PlatformEnterprise'")).mappings().one()
            assert menu_row["parent_id"] == dir_row["id"]
            # 与种子一致：关键契约字段逐项比对
            for key in ("name", "type", "order", "route_path", "redirect", "title"):
                assert dir_row[key] == seed_dir[key], key
            for key in ("name", "type", "order", "route_path", "component_path", "permission", "title"):
                assert menu_row[key] == seed_menu[key], key

            button_rows = conn.execute(
                sa.text("SELECT name, permission, parent_id FROM sys_menu WHERE permission LIKE 'module_platform:enterprise:%' AND type=3 ORDER BY \"order\"")
            ).mappings().all()
            assert [b["permission"] for b in button_rows] == [f"module_platform:enterprise:{a}" for a in _BUTTON_ACTIONS]
            assert all(b["parent_id"] == menu_row["id"] for b in button_rows)
            assert {b["name"] for b in button_rows} == {b["name"] for b in seed_buttons}

            with Operations.context(ctx):
                for migration in reversed(migrations):
                    migration.downgrade()
                for migration in reversed(migrations):
                    migration.downgrade()  # 重复回滚安全
            assert _counts(conn) == (0, 0, 0)
    finally:
        engine.dispose()


def test_menu_conflict_survives_rejected_upgrade_and_downgrade(test_client: TestClient, tmp_path) -> None:
    """预存同 permission/异 UUID 必须冲突，部分 upgrade 后 downgrade 也不能删除该他人行。"""
    engine = sa.create_engine(f"sqlite:///{tmp_path}/menu_conflict.db")
    try:
        MappedBase.metadata.create_all(engine)
        d4_migration, menu_migration = _load_migrations()
        foreign_uuid = "preexisting-audit-uuid"
        conflict_permission = "module_platform:enterprise:audit"
        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                # 先创建父菜单及既有七个按钮，再注入一个不属于 f6 迁移的 audit 行。
                d4_migration.upgrade()
            template = conn.execute(
                sa.select(menu_migration._MENU).where(menu_migration._MENU.c.permission == "module_platform:enterprise:bind")
            ).mappings().one()
            values = {key: value for key, value in template.items() if key != "id"}
            values.update(name="预存审计", title="预存审计", permission=conflict_permission, uuid=foreign_uuid)
            conn.execute(menu_migration._MENU.insert().values(**values))

            with Operations.context(ctx):
                with pytest.raises(RuntimeError, match=r"module_platform:enterprise:audit.*其他 UUID"):
                    menu_migration.upgrade()
                # transfer 在 audit 前已插入；精确 downgrade 应只清掉这个本迁移 UUID 的行。
                menu_migration.downgrade()

            foreign_row = conn.execute(
                sa.select(menu_migration._MENU.c.id, menu_migration._MENU.c.uuid).where(
                    menu_migration._MENU.c.permission == conflict_permission
                )
            ).mappings().one()
            assert foreign_row["uuid"] == foreign_uuid
            assert conn.execute(
                sa.select(sa.func.count()).select_from(menu_migration._MENU).where(
                    menu_migration._MENU.c.permission == "module_platform:enterprise:transfer"
                )
            ).scalar_one() == 0
    finally:
        engine.dispose()
