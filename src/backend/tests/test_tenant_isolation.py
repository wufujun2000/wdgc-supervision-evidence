"""B0 跨租户隔离验收（CRUD 层）：契约验收 1/2/3/4/6 组。

1. 两租户数据互不可见（get/get_list/page/count/exists，含显式跨租户 id）；
2. create 自动注入 tenant_id；payload 伪造他租户 tenant_id → 403；
3. update/delete/set/clear 跨租户越权无效（H-01），软删除语义不回归；
4. 无上下文 fail-closed；
6. read_only 上下文写操作 403。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from tenant_probe_helpers import (
    ProbeCreateSchema,
    ProbeCRUD,
    ProbeUpdateSchema,
    TenantProbeModel,
    _ensure_probe_tables,  # noqa: F401  (pytest autouse fixture)
    _isolate_tenant_context,  # noqa: F401  (pytest autouse fixture)
    make_enterprise,
    make_user,
    seed_probe,
    set_ctx,
)

from app.common.enums import RET
from app.core.base_schema import AuthSchema, CoreUserSchema, JWTPayloadSchema
from app.core.database import async_db_session
from app.core.dependencies import db_getter
from app.core.exceptions import CustomException
from app.core.security import create_access_token
from app.core.tenant_context import TenantRequestContext
from app.modules.platform.tenant_user.crud import TenantUserCRUD, TenantUserIsolatedCRUD
from app.modules.platform.tenant_user.model import BizTenantUserModel
from app.modules.system.auth.service import LoginService
from app.modules.system.user.crud import UserCRUD


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """测试专用会话：退出即回滚，不向共享测试库留数据。"""
    async with async_db_session() as session:
        try:
            yield session
        finally:
            await session.rollback()


class TestTenantVisibility:
    """验收 1：两租户数据互不可见。"""

    async def test_two_tenants_invisible(self, db) -> None:
        ent_a = await make_enterprise(db, "隔离-A")
        ent_b = await make_enterprise(db, "隔离-B")
        crud = ProbeCRUD(AuthSchema(), db)
        a1 = await seed_probe(db, ent_a.id, "a1")
        a2 = await seed_probe(db, ent_a.id, "a2")
        b1 = await seed_probe(db, ent_b.id, "b1")

        set_ctx(ent_a.id)
        assert (await crud.get(id=a1.id)).label == "a1"
        assert await crud.get(id=b1.id) is None  # 显式跨租户 id
        with pytest.raises(CustomException) as exc_info:
            await crud.get_or_404(id=b1.id)
        assert exc_info.value.code == RET.NOT_FOUND.code

        listed = await crud.get_list()
        assert {obj.id for obj in listed} == {a1.id, a2.id}
        # search 显式携带跨租户 id 亦被铁律过滤
        mixed = await crud.get_list(search={"id": ("in", [a1.id, b1.id])})
        assert {obj.id for obj in mixed} == {a1.id}

        page = await crud.page(offset=0, limit=10, order_by=[{"id": "asc"}])
        assert page.total == 2
        assert {obj.id for obj in page.items} == {a1.id, a2.id}
        assert await crud.count() == 2
        assert await crud.exists(id=a1.id) is True
        assert await crud.exists(id=b1.id) is False

        set_ctx(ent_b.id)
        assert {obj.id for obj in await crud.get_list()} == {b1.id}
        assert await crud.get(id=a1.id) is None
        assert await crud.count() == 1


class TestTenantCreate:
    """验收 2：create 注入与伪造拒绝。"""

    async def test_create_injects_context_tenant(self, db) -> None:
        ent_a = await make_enterprise(db, "注入-A")
        crud = ProbeCRUD(AuthSchema(), db)
        set_ctx(ent_a.id)
        obj = await crud.create(ProbeCreateSchema(label="inject"))
        assert obj.tenant_id == ent_a.id
        # payload 携带一致 tenant_id 也以上下文为准
        same = await crud.create(ProbeCreateSchema(label="same", tenant_id=ent_a.id))
        assert same.tenant_id == ent_a.id
        # dict 载荷同样注入
        via_dict = await crud.create({"label": "dict"})
        assert via_dict.tenant_id == ent_a.id

    async def test_create_forged_tenant_rejected(self, db) -> None:
        ent_a = await make_enterprise(db, "伪造-A")
        ent_b = await make_enterprise(db, "伪造-B")
        crud = ProbeCRUD(AuthSchema(), db)
        set_ctx(ent_a.id)

        with pytest.raises(CustomException) as exc_info:
            await crud.create(ProbeCreateSchema(label="forge", tenant_id=ent_b.id))
        assert exc_info.value.code == RET.FORBIDDEN.code
        assert exc_info.value.status_code == 403
        with pytest.raises(CustomException) as exc_dict:
            await crud.create({"label": "forge-dict", "tenant_id": ent_b.id})
        assert exc_dict.value.code == RET.FORBIDDEN.code

        # 伪造被拒后不得有任何行落入他租户（无上下文裸查验证）
        TenantRequestContext.clear()
        leaked = (
            await db.execute(select(func.count()).select_from(TenantProbeModel).where(TenantProbeModel.tenant_id == ent_b.id))
        ).scalar()
        assert leaked == 0


class TestTenantWritePaths:
    """验收 3：H-01 写路径跨租户越权无效 + 软删除语义不回归。"""

    async def test_cross_tenant_writes_are_noop(self, db) -> None:
        ent_a = await make_enterprise(db, "写-A")
        ent_b = await make_enterprise(db, "写-B")
        crud = ProbeCRUD(AuthSchema(), db)
        a1 = await seed_probe(db, ent_a.id, "a1")
        b1 = await seed_probe(db, ent_b.id, "b1-original")

        set_ctx(ent_a.id)
        # update 跨租户 → 经 get 隔离，对象不存在
        with pytest.raises(CustomException, match="更新对象不存在"):
            await crud.update(b1.id, ProbeUpdateSchema(label="hacked"))
        # delete/set 跨租户 → 批量 SQL 合并租户条件，0 行受影响
        await crud.delete([b1.id])
        await crud.set([b1.id], label="hacked", status=1)

        set_ctx(ent_b.id)
        intact = await crud.get(id=b1.id)
        assert intact is not None
        assert intact.label == "b1-original"
        assert intact.is_deleted is False
        assert intact.status == 0

        # update 伪造 tenant_id 迁移租户 → 403
        set_ctx(ent_a.id)
        with pytest.raises(CustomException) as exc_info:
            await crud.update(a1.id, ProbeUpdateSchema(tenant_id=ent_b.id))
        assert exc_info.value.code == RET.FORBIDDEN.code
        with pytest.raises(CustomException) as exc_dict:
            await crud.update(a1.id, {"tenant_id": ent_b.id})
        assert exc_dict.value.code == RET.FORBIDDEN.code
        set_ctx(ent_b.id)
        assert (await crud.get(id=b1.id)).label == "b1-original"

    async def test_soft_delete_semantics_no_regression(self, db) -> None:
        ent_a = await make_enterprise(db, "软删-A")
        ent_b = await make_enterprise(db, "软删-B")
        crud = ProbeCRUD(AuthSchema(), db)
        a_active = await seed_probe(db, ent_a.id, "a-active")
        a_deleted = await seed_probe(db, ent_a.id, "a-deleted")
        b_active = await seed_probe(db, ent_b.id, "b-active")
        b_deleted = await seed_probe(db, ent_b.id, "b-deleted")

        # 本租户软删除：默认查询不可见，include_deleted 可见
        set_ctx(ent_a.id)
        await crud.delete([a_deleted.id])
        assert await crud.get(id=a_deleted.id) is None
        assert (await crud.get(id=a_deleted.id, include_deleted=True)).is_deleted is True
        set_ctx(ent_b.id)
        await crud.delete([b_deleted.id])
        b_deleted_time = (await crud.get(id=b_deleted.id, include_deleted=True)).deleted_time

        # clear 只清本租户已软删记录（原生语义：刷新删除审计，不物理删除），他租户回收站不受影响
        set_ctx(ent_a.id)
        await crud.clear()
        assert (await crud.get(id=a_active.id)).label == "a-active"
        assert (await crud.get(id=a_deleted.id, include_deleted=True)).is_deleted is True

        set_ctx(ent_b.id)
        assert (await crud.get(id=b_active.id)).label == "b-active"
        b_recycled = await crud.get(id=b_deleted.id, include_deleted=True)
        assert b_recycled.is_deleted is True
        assert b_recycled.deleted_time == b_deleted_time

        # set 默认跳过已软删记录（include_deleted=False 语义不回归）
        await crud.set([b_deleted.id, b_active.id], label="bulk-set")
        assert (await crud.get(id=b_active.id)).label == "bulk-set"
        assert (await crud.get(id=b_deleted.id, include_deleted=True)).label == "b-deleted"


class TestTenantFailClosed:
    """验收 4：无租户上下文读写一律 fail-closed。"""

    async def test_no_context_fail_closed(self, db) -> None:
        ent_a = await make_enterprise(db, "闭锁-A")
        await seed_probe(db, ent_a.id, "seeded")
        TenantRequestContext.clear()
        crud = ProbeCRUD(AuthSchema(), db)

        async def _read_get():
            return await crud.get(id=1)

        async def _read_list():
            return await crud.get_list()

        async def _read_page():
            return await crud.page(offset=0, limit=10, order_by=[{"id": "asc"}])

        async def _read_count():
            return await crud.count()

        async def _read_exists():
            return await crud.exists(id=1)

        async def _write_create():
            return await crud.create(ProbeCreateSchema(label="x"))

        async def _write_update():
            return await crud.update(1, ProbeUpdateSchema(label="x"))

        async def _write_delete():
            return await crud.delete([1])

        async def _write_set():
            return await crud.set([1], label="x")

        async def _write_clear():
            return await crud.clear()

        for operation in (
            _read_get, _read_list, _read_page, _read_count, _read_exists,
            _write_create, _write_update, _write_delete, _write_set, _write_clear,
        ):
            with pytest.raises(CustomException) as exc_info:
                await operation()
            assert exc_info.value.code == RET.FORBIDDEN.code, operation.__name__

        # 平台域 CRUDBase 无上下文不受影响（对照）
        assert await TenantUserCRUD(AuthSchema(), db).count() >= 0

    async def test_context_without_tenant_fail_closed(self, db) -> None:
        set_ctx(None)
        crud = ProbeCRUD(AuthSchema(), db)
        with pytest.raises(CustomException) as exc_info:
            await crud.get_list()
        assert exc_info.value.code == RET.FORBIDDEN.code


class TestTenantReadOnly:
    """验收 6：read_only（代管态预留）写操作一律 403，读正常。"""

    async def test_read_only_blocks_writes(self, db) -> None:
        ent_a = await make_enterprise(db, "只读-A")
        crud = ProbeCRUD(AuthSchema(), db)
        obj = await seed_probe(db, ent_a.id, "ro")

        set_ctx(ent_a.id, read_only=True)
        assert (await crud.get(id=obj.id)).label == "ro"
        assert await crud.count() == 1

        async def _create():
            return await crud.create(ProbeCreateSchema(label="x"))

        async def _update():
            return await crud.update(obj.id, ProbeUpdateSchema(label="x"))

        async def _delete():
            return await crud.delete([obj.id])

        async def _set():
            return await crud.set([obj.id], label="x")

        async def _clear():
            return await crud.clear()

        for operation in (_create, _update, _delete, _set, _clear):
            with pytest.raises(CustomException) as exc_info:
                await operation()
            assert exc_info.value.code == RET.FORBIDDEN.code, operation.__name__
            assert exc_info.value.status_code == 403, operation.__name__

        # 只读态未改动任何数据
        assert (await crud.get(id=obj.id)).label == "ro"


class TestBindingIsolation:
    """biz_tenant_user 本身作为具体租户模型的隔离（平台侧显式 tenant_id vs 租户上下文铁律）。"""

    async def test_binding_crud_isolation(self, db) -> None:
        ent_a = await make_enterprise(db, "绑定-A")
        ent_b = await make_enterprise(db, "绑定-B")
        user_a1 = await make_user(db, "bind_a1")
        user_a2 = await make_user(db, "bind_a2")
        user_b1 = await make_user(db, "bind_b1")

        # 平台侧：无上下文，CRUDBase＋显式 tenant_id 建绑定
        platform_crud = TenantUserCRUD(AuthSchema(), db)
        bind_a1 = await platform_crud.create({"tenant_id": ent_a.id, "user_id": user_a1.id, "is_enterprise_admin": True})
        bind_a2 = await platform_crud.create({"tenant_id": ent_a.id, "user_id": user_a2.id, "is_enterprise_admin": False})
        bind_b1 = await platform_crud.create({"tenant_id": ent_b.id, "user_id": user_b1.id, "is_enterprise_admin": False})

        isolated = TenantUserIsolatedCRUD(AuthSchema(), db)
        set_ctx(ent_a.id)
        assert {b.id for b in await isolated.get_list()} == {bind_a1.id, bind_a2.id}
        assert await isolated.get(id=bind_b1.id) is None
        assert await isolated.count() == 2

        # 租户上下文内 create 自动注入；伪造他租户 → 403
        user_a3 = await make_user(db, "bind_a3")
        created = await isolated.create({"user_id": user_a3.id, "is_enterprise_admin": False})
        assert created.tenant_id == ent_a.id
        user_a4 = await make_user(db, "bind_a4")
        with pytest.raises(CustomException) as exc_info:
            await isolated.create({"user_id": user_a4.id, "tenant_id": ent_b.id})
        assert exc_info.value.code == RET.FORBIDDEN.code

        # 跨租户 delete 无效
        await isolated.delete([bind_b1.id])
        set_ctx(ent_b.id)
        assert await isolated.get(id=bind_b1.id) is not None
        assert await isolated.count() == 1

        # 无上下文 fail-closed
        TenantRequestContext.clear()
        with pytest.raises(CustomException):
            await isolated.get_list()
        # 平台侧无上下文仍正常
        assert await platform_crud.count() == 4
        assert (await platform_crud.get(id=bind_b1.id)).tenant_id == ent_b.id
        assert isinstance(bind_b1, BizTenantUserModel)


def _tenant_auth(user_id: int, tenant_id: int) -> AuthSchema:
    """真实租户用户认证（非超管、有用户ID）——Permission 不再短路，验证租户模型跳过平台数据权限。"""
    return AuthSchema(user=CoreUserSchema(id=user_id, is_superuser=False, tenant_id=tenant_id))


class TestRealAuthIsolation:
    """评审 Major-2：真实 AuthSchema 下租户模型不受平台域 Permission（created_id/dept）过滤。"""

    async def test_same_tenant_cross_user_visibility(self, db) -> None:
        ent = await make_enterprise(db, "真权-A")
        u1 = await make_user(db, "real_a1")
        u2 = await make_user(db, "real_a2")
        set_ctx(ent.id)
        # A1 创建（created_id=u1），A2 同租户互查必须可见
        created = await ProbeCRUD(_tenant_auth(u1.id, ent.id), db).create(ProbeCreateSchema(label="by-a1"))
        assert created.created_id == u1.id
        crud_a2 = ProbeCRUD(_tenant_auth(u2.id, ent.id), db)
        assert (await crud_a2.get(id=created.id)).label == "by-a1"
        assert {obj.id for obj in await crud_a2.get_list()} == {created.id}
        assert await crud_a2.count() == 1

    async def test_tenant_user_finds_own_binding(self, db) -> None:
        ent = await make_enterprise(db, "真权-绑定")
        admin = await make_user(db, "real_admin")
        admin.is_superuser = True
        await db.flush()
        member = await make_user(db, "real_member")
        # 绑定由超管开通创建（created_id=超管），租户用户本人必须查得到自身绑定
        binding = await TenantUserCRUD(AuthSchema(user=CoreUserSchema(id=admin.id, is_superuser=True)), db).create(
            {"tenant_id": ent.id, "user_id": member.id, "is_enterprise_admin": False}
        )
        assert binding.created_id == admin.id
        set_ctx(ent.id)
        isolated = TenantUserIsolatedCRUD(_tenant_auth(member.id, ent.id), db)
        found = await isolated.get(user_id=member.id)
        assert found is not None
        assert found.id == binding.id
        assert found.tenant_id == ent.id

    async def test_cross_tenant_still_invisible_with_real_auth(self, db) -> None:
        ent_a = await make_enterprise(db, "真权-甲")
        ent_b = await make_enterprise(db, "真权-乙")
        u1 = await make_user(db, "real_x1")
        u2 = await make_user(db, "real_x2")
        set_ctx(ent_a.id)
        obj = await ProbeCRUD(_tenant_auth(u1.id, ent_a.id), db).create(ProbeCreateSchema(label="secret"))
        # 铁律不回归：他租户真实用户仍不可见
        set_ctx(ent_b.id)
        crud_b = ProbeCRUD(_tenant_auth(u2.id, ent_b.id), db)
        assert await crud_b.get(id=obj.id) is None
        assert await crud_b.get_list() == []
        assert await crud_b.count() == 0


class TestSetTenantForgery:
    """评审 Minor-1：批量 SET 禁止篡改租户归属。"""

    async def test_set_tenant_id_forgery_rejected(self, db) -> None:
        ent_a = await make_enterprise(db, "SET-A")
        ent_b = await make_enterprise(db, "SET-B")
        crud = ProbeCRUD(AuthSchema(), db)
        obj = await seed_probe(db, ent_a.id, "set-target")

        set_ctx(ent_a.id)
        with pytest.raises(CustomException) as exc_info:
            await crud.set([obj.id], tenant_id=ent_b.id, label="hacked")
        assert exc_info.value.code == RET.FORBIDDEN.code
        assert exc_info.value.status_code == 403
        # 裸查验证归属与内容均未变
        TenantRequestContext.clear()
        row = (await db.execute(select(TenantProbeModel).where(TenantProbeModel.id == obj.id))).scalar_one()
        assert row.tenant_id == ent_a.id
        assert row.label == "set-target"
        # 携带一致 tenant_id 也剔除（以上下文为准），正常 SET 不受影响
        set_ctx(ent_a.id)
        await crud.set([obj.id], tenant_id=ent_a.id, label="ok")
        assert (await crud.get(id=obj.id)).label == "ok"
        assert (await crud.get(id=obj.id)).tenant_id == ent_a.id


class _TokenRedisCURD:
    """create_token 测试用 RedisCURD 替身：dict 存储。"""

    def __init__(self, redis: dict) -> None:
        self.redis = redis

    async def set(self, key, value, expire=None) -> bool:
        self.redis[key] = value
        return True

    async def get(self, key):
        return self.redis.get(key)

    async def expire(self, key, expire) -> bool:
        return True

    async def delete(self, *keys) -> bool:
        for key in keys:
            self.redis.pop(key, None)
        return True


class _FakeRedis:
    """_authenticate 测试用 redis 替身（get/set/delete/ttl/expire）。"""

    def __init__(self, store: dict[str, str]) -> None:
        self.store = store

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False) -> bool:
        self.store[key] = value
        return True

    async def delete(self, *keys) -> int:
        for key in keys:
            self.store.pop(key, None)
        return len(keys)

    async def ttl(self, key) -> int:
        return 3600 if key in self.store else -2

    async def expire(self, key, time) -> bool:
        return key in self.store


class TestContextLifecycle:
    """评审 Minor-2：请求结束清理上下文；登录绑定解析不受残留上下文误过滤。"""

    async def test_db_getter_clears_context_on_exit(self) -> None:
        set_ctx(999)
        gen = db_getter()
        await gen.__anext__()
        assert TenantRequestContext.get() is not None  # 请求期间上下文仍在
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert TenantRequestContext.get() is None  # 退出即清理

    async def test_platform_query_correct_after_lifecycle(self, db) -> None:
        ent_a = await make_enterprise(db, "生命周期-A")
        ent_b = await make_enterprise(db, "生命周期-B")
        user_b = await make_user(db, "lc_user_b")
        binding_b = await TenantUserCRUD(AuthSchema(), db).create(
            {"tenant_id": ent_b.id, "user_id": user_b.id, "is_enterprise_admin": False}
        )
        # 残留上下文（模拟上一请求未清理）→ 请求级生命周期退出即清理
        set_ctx(ent_a.id)
        gen = db_getter()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert TenantRequestContext.get() is None
        # 平台侧查询不再被误过滤：ent_b 用户的绑定正确返回
        found = await TenantUserCRUD(AuthSchema(), db).get(user_id=user_b.id)
        assert found is not None
        assert found.id == binding_b.id
        assert found.tenant_id == ent_b.id

    async def test_create_token_clears_residual_context(self, db, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.modules.system.auth.service as auth_mod

        ent_a = await make_enterprise(db, "登录残留-A")
        ent_b = await make_enterprise(db, "登录残留-B")
        user_b = await make_user(db, "login_user_b")
        await TenantUserCRUD(AuthSchema(), db).create({"tenant_id": ent_b.id, "user_id": user_b.id, "is_enterprise_admin": False})
        # roles 预加载：_collect_permissions 需要（异步懒加载会 MissingGreenlet）
        user = await UserCRUD(AuthSchema(), db).get(id=user_b.id, preload=["roles"])

        store: dict = {}
        monkeypatch.setattr(auth_mod, "RedisCURD", _TokenRedisCURD)
        monkeypatch.setattr(auth_mod, "create_access_token", lambda payload: "tok-refresh" if payload.is_refresh else "tok-access")
        monkeypatch.setattr(auth_mod, "get_client_ip", lambda request: "1.1.1.1")

        async def _loc(redis, ip):
            return "BJ"

        monkeypatch.setattr(auth_mod.IpLocalUtil, "resolve_location", staticmethod(_loc))

        # 残留 ent_a 上下文：create_token 解析绑定前显式 clear → ent_b 绑定不被误过滤
        set_ctx(ent_a.id)
        request = SimpleNamespace(headers={"user-agent": "ua"}, client=SimpleNamespace(host="1.1.1.1"))
        await LoginService.create_token(request=request, redis=store, user=user, login_type="pc", db=db)

        session_key = next(key for key in store if key.startswith("user_session:"))
        snapshot = json.loads(store[session_key])
        assert snapshot["tenant_id"] == ent_b.id  # 未误写 None
        assert TenantRequestContext.get() is None


class TestImpersonationReserved:
    """评审 Nit-1：代管预留——超管无绑定，租户来自快照且同样校验企业冻结。"""

    async def _authenticate_with_snapshot(self, db, snapshot: dict) -> tuple[AuthSchema, dict]:
        from app.core.dependencies import _authenticate

        session_id = snapshot["session_id"]
        store = {f"user_session:{session_id}": json.dumps(snapshot)}
        token = create_access_token(JWTPayloadSchema(sub=session_id, is_refresh=False, exp=datetime.now() + timedelta(hours=1)))
        return await _authenticate(token, db, _FakeRedis(store)), store

    async def test_impersonated_snapshot_injects_context(self, db) -> None:
        ent = await make_enterprise(db, "代管-A")
        admin = await make_user(db, "imp_admin")
        admin.is_superuser = True
        await db.flush()
        snapshot = {
            "session_id": "imp-sess-1",
            "user_id": admin.id,
            "user_name": admin.username,
            "user_status": 0,
            "is_impersonated": True,
            "impersonator_id": admin.id,
            "tenant_id": ent.id,
            "read_only": True,
            "scope": "read_only",
        }
        auth, _store = await self._authenticate_with_snapshot(db, snapshot)
        context = TenantRequestContext.get()
        assert context is not None
        assert context.tenant_id == ent.id
        assert context.is_impersonated is True
        assert context.impersonator_id == admin.id
        assert context.read_only is True
        assert auth.user.tenant_id == ent.id

    async def test_impersonated_frozen_enterprise_rejected(self, db) -> None:
        ent = await make_enterprise(db, "代管-冻结")
        ent.status = 0
        await db.flush()
        admin = await make_user(db, "imp_admin2")
        admin.is_superuser = True
        await db.flush()
        snapshot = {
            "session_id": "imp-sess-2",
            "user_id": admin.id,
            "user_name": admin.username,
            "user_status": 0,
            "is_impersonated": True,
            "impersonator_id": admin.id,
            "tenant_id": ent.id,
            "read_only": True,
        }
        with pytest.raises(CustomException) as exc_info:
            await self._authenticate_with_snapshot(db, snapshot)
        assert exc_info.value.code == RET.UNAUTHORIZED.code

    async def test_impersonated_frozen_purges_session(self, db) -> None:
        from app.core.dependencies import _authenticate

        ent = await make_enterprise(db, "代管-清退")
        ent.status = 0
        await db.flush()
        admin = await make_user(db, "imp_admin3")
        admin.is_superuser = True
        await db.flush()
        store = {
            "user_session:imp-sess-3": json.dumps(
                {
                    "session_id": "imp-sess-3",
                    "user_id": admin.id,
                    "user_name": admin.username,
                    "user_status": 0,
                    "is_impersonated": True,
                    "tenant_id": ent.id,
                    "read_only": True,
                }
            )
        }
        token = create_access_token(JWTPayloadSchema(sub="imp-sess-3", is_refresh=False, exp=datetime.now() + timedelta(hours=1)))
        with pytest.raises(CustomException):
            await _authenticate(token, db, _FakeRedis(store))
        assert "user_session:imp-sess-3" not in store
