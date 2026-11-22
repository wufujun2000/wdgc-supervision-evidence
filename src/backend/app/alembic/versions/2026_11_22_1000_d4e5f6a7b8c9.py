"""平台管理/租户开通菜单数据迁移

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-22 10:00:00

与 sql/sys_menu.json 种子内容一致（双轨）：
- 全新空库走 init_db「create_all＋种子＋stamp head」，不执行本迁移；
- 存量库经 upgrade head 补齐「平台管理/租户开通」目录、菜单与按钮权限。
只插入/删除 route_name、permission 唯一键标识的行，幂等且可精确回滚；
id 由数据库自增（不写死，避免 PG 序列与显式主键脱节），父子引用按 route_name 回查。
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MENU = sa.table(
    "sys_menu",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("type", sa.Integer),
    sa.column("order", sa.Integer),
    sa.column("permission", sa.String),
    sa.column("icon", sa.String),
    sa.column("route_name", sa.String),
    sa.column("route_path", sa.String),
    sa.column("component_path", sa.String),
    sa.column("redirect", sa.String),
    sa.column("title", sa.String),
    sa.column("description", sa.Text),
    sa.column("parent_id", sa.Integer),
    sa.column("hidden", sa.Boolean),
    sa.column("keep_alive", sa.Boolean),
    sa.column("always_show", sa.Boolean),
    sa.column("affix", sa.Boolean),
    sa.column("is_iframe", sa.Boolean),
    sa.column("is_hide_tab", sa.Boolean),
    sa.column("show_badge", sa.Boolean),
    sa.column("status", sa.Integer),
    sa.column("scope", sa.String),
    sa.column("uuid", sa.String),
    sa.column("is_deleted", sa.Boolean),
    sa.column("created_time", sa.DateTime),
    sa.column("updated_time", sa.DateTime),
)

# (按钮名称, 权限动作) —— 与种子 JSON 顺序一致
_BUTTONS: list[tuple[str, str]] = [
    ("开通租户", "create"),
    ("企业详情", "detail"),
    ("更新企业", "update"),
    ("冻结企业", "freeze"),
    ("解冻企业", "unfreeze"),
    ("绑定用户", "bind"),
    ("解绑用户", "unbind"),
]

_NOW = datetime(2026, 11, 22, tzinfo=UTC)


def _base_values() -> dict:
    """ModelMixin/MenuModel 无 server_default 的非空列统一显式给值（跨方言一致）。"""
    return {
        "hidden": False,
        "keep_alive": True,
        "always_show": False,
        "affix": False,
        "is_iframe": False,
        "is_hide_tab": False,
        "show_badge": False,
        "status": 0,
        "scope": "web",
        "is_deleted": False,
        "created_time": _NOW,
        "updated_time": _NOW,
    }


def _uuid(key: str) -> str:
    """确定性 UUID：同一种子键在各环境生成相同值，避免重复执行产生漂移。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"wdgc:sys_menu:{key}").hex


def upgrade() -> None:
    bind = op.get_bind()

    def exists(**filters) -> bool:
        stmt = sa.select(_MENU.c.id).where(*[getattr(_MENU.c, k) == v for k, v in filters.items()])
        return bind.execute(stmt).first() is not None

    def id_by_route(route_name: str) -> int:
        return bind.execute(sa.select(_MENU.c.id).where(_MENU.c.route_name == route_name)).scalar_one()

    if not exists(route_name="Platform"):
        bind.execute(
            _MENU.insert().values(
                **_base_values(),
                name="平台管理", type=1, order=8, icon="ri:building-4-line",
                permission=None, route_name="Platform", route_path="/platform",
                component_path=None, redirect="/platform/enterprise",
                title="平台管理", description="初始化数据", parent_id=None,
                uuid=_uuid("Platform"),
            )
        )
    dir_id = id_by_route("Platform")

    if not exists(route_name="PlatformEnterprise"):
        bind.execute(
            _MENU.insert().values(
                **_base_values(),
                name="租户开通", type=2, order=1, icon="ri:building-2-line",
                permission="module_platform:enterprise:query",
                route_name="PlatformEnterprise", route_path="enterprise",
                component_path="module_platform/enterprise/index", redirect=None,
                title="租户开通", description="初始化数据", parent_id=dir_id,
                uuid=_uuid("PlatformEnterprise"),
            )
        )
    menu_id = id_by_route("PlatformEnterprise")

    for order, (button_name, action) in enumerate(_BUTTONS, start=1):
        permission = f"module_platform:enterprise:{action}"
        if exists(permission=permission):
            continue
        bind.execute(
            _MENU.insert().values(
                **_base_values(),
                name=button_name, type=3, order=order, icon=None,
                permission=permission, route_name=None, route_path=None,
                component_path=None, redirect=None,
                title=button_name, description=f"{button_name}权限", parent_id=menu_id,
                uuid=_uuid(permission),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(_MENU.delete().where(_MENU.c.permission.in_([f"module_platform:enterprise:{action}" for _, action in _BUTTONS])))
    bind.execute(_MENU.delete().where(_MENU.c.route_name == "PlatformEnterprise"))
    bind.execute(_MENU.delete().where(_MENU.c.route_name == "Platform"))
