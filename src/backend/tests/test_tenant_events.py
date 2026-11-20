"""B0 ORM 钩子兜底验收：契约验收第 5 组。

裸 ORM select＋joinedload/selectinload 预加载被 do_orm_execute 钩子兜底过滤；
上下文不存在时不注入（平台/后台合法）；ORM UPDATE/DELETE 同样叠加租户条件。
text() 裸 SQL 不在兜底范围（见 tenant_events 模块边界说明）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from tenant_probe_helpers import (
    ProbeCRUD,
    TenantProbeChildModel,
    TenantProbeModel,
    _ensure_probe_tables,  # noqa: F401  (pytest autouse fixture)
    _isolate_tenant_context,  # noqa: F401  (pytest autouse fixture)
    make_enterprise,
    seed_probe,
    set_ctx,
)

from app.core.base_schema import AuthSchema
from app.core.database import async_db_session
from app.core.tenant_context import TenantRequestContext


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """测试专用会话：退出即回滚，不向共享测试库留数据。"""
    async with async_db_session() as session:
        try:
            yield session
        finally:
            await session.rollback()


class TestTenantOrmGuard:
    async def test_raw_select_filtered_by_context(self, db) -> None:
        ent_a = await make_enterprise(db, "兜底-A")
        ent_b = await make_enterprise(db, "兜底-B")
        a1 = await seed_probe(db, ent_a.id, "a1")
        b1 = await seed_probe(db, ent_b.id, "b1")

        set_ctx(ent_a.id)
        rows = (await db.execute(select(TenantProbeModel))).scalars().all()
        assert {row.id for row in rows} == {a1.id}

        # 无上下文不注入：平台/后台合法全量
        TenantRequestContext.clear()
        rows = (await db.execute(select(TenantProbeModel))).scalars().all()
        assert {row.id for row in rows} == {a1.id, b1.id}

    async def test_selectinload_target_filtered(self, db) -> None:
        ent_a = await make_enterprise(db, "预载-A")
        ent_b = await make_enterprise(db, "预载-B")
        crud = ProbeCRUD(AuthSchema(), db)
        set_ctx(ent_a.id)
        parent = await crud.create({"label": "parent"})
        child_a = TenantProbeChildModel(tenant_id=ent_a.id, probe_id=parent.id, note="own")
        child_cross = TenantProbeChildModel(tenant_id=ent_b.id, probe_id=parent.id, note="cross")
        db.add_all([child_a, child_cross])
        await db.flush()

        set_ctx(ent_a.id)
        rows = (
            await db.execute(select(TenantProbeModel).options(selectinload(TenantProbeModel.children)))
        ).scalars().all()
        loaded = next(row for row in rows if row.id == parent.id)
        assert {child.id for child in loaded.children} == {child_a.id}

    async def test_joinedload_target_filtered(self, db) -> None:
        ent_a = await make_enterprise(db, "联载-A")
        ent_b = await make_enterprise(db, "联载-B")
        crud = ProbeCRUD(AuthSchema(), db)
        set_ctx(ent_a.id)
        parent_a = await crud.create({"label": "parent-a"})
        set_ctx(ent_b.id)
        parent_b = await crud.create({"label": "parent-b"})

        # 同租户父可见；跨租户父被过滤为 None
        child_own = TenantProbeChildModel(tenant_id=ent_b.id, probe_id=parent_b.id, note="own")
        child_cross = TenantProbeChildModel(tenant_id=ent_b.id, probe_id=parent_a.id, note="cross")
        db.add_all([child_own, child_cross])
        await db.flush()

        set_ctx(ent_b.id)
        rows = (
            await db.execute(select(TenantProbeChildModel).options(joinedload(TenantProbeChildModel.parent)))
        ).scalars().all()
        by_id = {row.id: row for row in rows}
        assert by_id[child_own.id].parent is not None
        assert by_id[child_own.id].parent.id == parent_b.id
        assert by_id[child_cross.id].parent is None

    async def test_dml_guard_update_delete(self, db) -> None:
        ent_a = await make_enterprise(db, "DML-A")
        ent_b = await make_enterprise(db, "DML-B")
        a1 = await seed_probe(db, ent_a.id, "a1")
        b1 = await seed_probe(db, ent_b.id, "b1-original")

        # 裸 ORM UPDATE 不带租户条件 → 钩子兜底只改本租户
        set_ctx(ent_a.id)
        await db.execute(update(TenantProbeModel).where(TenantProbeModel.id.in_([a1.id, b1.id])).values(label="bulk"))
        await db.flush()
        TenantRequestContext.clear()
        assert (await db.execute(select(TenantProbeModel.label).where(TenantProbeModel.id == a1.id))).scalar() == "bulk"
        assert (await db.execute(select(TenantProbeModel.label).where(TenantProbeModel.id == b1.id))).scalar() == "b1-original"

        # 裸 ORM DELETE 同理
        set_ctx(ent_a.id)
        await db.execute(delete(TenantProbeModel).where(TenantProbeModel.id.in_([a1.id, b1.id])))
        await db.flush()
        TenantRequestContext.clear()
        remaining = {row.id for row in (await db.execute(select(TenantProbeModel))).scalars().all()}
        assert a1.id not in remaining
        assert b1.id in remaining
