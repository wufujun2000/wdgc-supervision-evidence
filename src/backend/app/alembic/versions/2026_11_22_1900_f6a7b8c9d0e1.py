"""ADR-001 移交所有权/所有权审计菜单按钮数据迁移

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-22 19:00:00

与 sql/sys_menu.json 种子一致（双轨）：在「平台管理/租户开通」下追加两个按钮权限。
幂等插入、按 permission 精确回滚，父菜单经 route_name=PlatformEnterprise 回查。
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
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

_BUTTONS: list[tuple[str, str, str]] = [
    ("移交所有权", "module_platform:enterprise:transfer", "移交所有权权限"),
    ("所有权审计", "module_platform:enterprise:audit", "所有权审计权限"),
]
_NOW = datetime(2026, 11, 22, tzinfo=UTC)


def _uuid(key: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"wdgc:sys_menu:{key}").hex


def upgrade() -> None:
    bind = op.get_bind()
    menu_id = bind.execute(sa.select(_MENU.c.id).where(_MENU.c.route_name == "PlatformEnterprise")).scalar_one()
    for order, (name, permission, description) in enumerate(_BUTTONS, start=8):
        exists = bind.execute(sa.select(_MENU.c.id).where(_MENU.c.permission == permission)).first()
        if exists:
            continue
        bind.execute(
            _MENU.insert().values(
                name=name, type=3, order=order, icon=None, permission=permission,
                route_name=None, route_path=None, component_path=None, redirect=None,
                title=name, description=description, parent_id=menu_id,
                hidden=False, keep_alive=True, always_show=False, affix=False,
                is_iframe=False, is_hide_tab=False, show_badge=False,
                status=0, scope="web", is_deleted=False,
                created_time=_NOW, updated_time=_NOW, uuid=_uuid(permission),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(_MENU.delete().where(_MENU.c.permission.in_([permission for _, permission, _ in _BUTTONS])))
