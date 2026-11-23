"""真实 MySQL 行锁回归：可控交错，不以 gather 的偶然调度证明互斥。

默认跳过；设置 TEST_MYSQL_URL=mysql+aiomysql://... 后运行。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.base_schema import AuthSchema, BatchSetAvailable, CoreUserSchema
from app.core.exceptions import CustomException
from app.core.tenant_context import TenantRequestContext
from app.modules.platform.enterprise.model import EnterpriseModel
from app.modules.platform.member.service import MemberService, execute_owner_transfer
from app.modules.system.user.model import UserModel
from app.modules.system.user.service import UserService
from app.modules.tenant.member.model import BizTenantMemberModel, BizTenantOwnerModel
from app.modules.tenant.member.schema import AdminGrantSchema
from app.modules.tenant.member.service import TenantMemberService

pytestmark = pytest.mark.skipif(not os.getenv("TEST_MYSQL_URL"), reason="需要 TEST_MYSQL_URL 真实 MySQL")


class _PauseBeforeWrite:
    def __init__(self, session, kind: str, ready: asyncio.Event, resume: asyncio.Event):
        self.session = session
        self.kind = kind
        self.ready = ready
        self.resume = resume

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement).lower()
        marker = {
            "platform": "update biz_tenant_member set status = 1",
            "tenant": "update biz_tenant_member set status = 1",
            "native": "update sys_user",
            "admin": "insert into biz_tenant_admin",
        }[self.kind]
        if marker in sql and not self.ready.is_set():
            self.ready.set()
            await self.resume.wait()
        return await self.session.execute(statement, *args, **kwargs)

    async def flush(self, *args, **kwargs):
        if self.kind == "admin" and not self.ready.is_set():
            self.ready.set()
            await self.resume.wait()
        return await self.session.flush(*args, **kwargs)


class _SignalTransferLockAttempt:
    def __init__(self, session, attempted: asyncio.Event):
        self.session = session
        self.attempted = attempted

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def execute(self, statement, *args, **kwargs):
        if "update biz_tenant_member set status = status" in str(statement).lower():
            self.attempted.set()
        return await self.session.execute(statement, *args, **kwargs)


async def _run_interleave(kind: str) -> None:
    engine = create_async_engine(
        os.environ["TEST_MYSQL_URL"], execution_options={"isolation_level": "READ COMMITTED"}, pool_size=3, max_overflow=1
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:10]
    enterprise_code = f"R2LOCK-{suffix}"
    names = [f"r2lock_{suffix}_a", f"r2lock_{suffix}_b"]
    ready, resume, transfer_attempt = asyncio.Event(), asyncio.Event(), asyncio.Event()
    redis = AsyncMock()
    redis.keys = AsyncMock(return_value=[])
    tenant_id = owner_member_id = target_member_id = owner_uid = target_uid = None
    disable_task = transfer_task = None
    try:
        async with sessions() as db:
            assert (await db.execute(sa.text("SELECT @@transaction_isolation"))).scalar_one() == "READ-COMMITTED"
            ent = EnterpriseModel(enterprise_code=enterprise_code, name=f"R2锁-{suffix}", status=1)
            ua = UserModel(username=names[0], password="x", name=names[0], status=0)
            ub = UserModel(username=names[1], password="x", name=names[1], status=0)
            db.add_all([ent, ua, ub])
            await db.flush()
            tenant_id, owner_uid, target_uid = ent.id, ua.id, ub.id
            owner = BizTenantMemberModel(tenant_id=tenant_id, user_id=owner_uid, status=0)
            target = BizTenantMemberModel(tenant_id=tenant_id, user_id=target_uid, status=0)
            db.add_all([owner, target])
            await db.flush()
            owner_member_id, target_member_id = owner.id, target.id
            db.add(BizTenantOwnerModel(tenant_id=tenant_id, member_id=owner_member_id, version=1))
            await db.commit()

        async def writer():
            async with sessions() as db:
                paused = _PauseBeforeWrite(db, kind, ready, resume)
                try:
                    if kind == "platform":
                        auth = AuthSchema(user=CoreUserSchema(id=0, is_superuser=True))
                        await MemberService(auth, paused).disable(target_member_id, redis)
                    elif kind == "tenant":
                        TenantRequestContext.set(TenantRequestContext(tenant_id=tenant_id, member_id=owner_member_id))
                        auth = AuthSchema(user=CoreUserSchema(id=owner_uid, is_superuser=False))
                        await TenantMemberService(auth, paused).disable_member(target_member_id, redis)
                    elif kind == "native":
                        TenantRequestContext.clear()
                        auth = AuthSchema(user=CoreUserSchema(id=0, is_superuser=True))
                        await UserService(auth, paused).set_available(BatchSetAvailable(ids=[target_uid], status=1))
                        await db.commit()
                    else:
                        TenantRequestContext.set(TenantRequestContext(tenant_id=tenant_id, member_id=owner_member_id))
                        auth = AuthSchema(user=CoreUserSchema(id=owner_uid, is_superuser=False))
                        await TenantMemberService(auth, paused).set_admin(
                            AdminGrantSchema(member_id=target_member_id, permissions=["tenant_member_manage"])
                        )
                    return "committed"
                except BaseException as exc:
                    await db.rollback()
                    return f"{type(exc).__name__}: {exc}"
                finally:
                    TenantRequestContext.clear()

        async def transfer():
            async with sessions() as db:
                TenantRequestContext.clear()
                signaled = _SignalTransferLockAttempt(db, transfer_attempt)
                try:
                    await execute_owner_transfer(
                        signaled,
                        redis,
                        tenant_id=tenant_id,
                        target_member_id=target_member_id,
                        operator_user_id=None,
                        source="platform",
                        reason=f"R2锁-{kind}-{suffix}",
                    )
                    await db.commit()
                    return "committed"
                except CustomException as exc:
                    await db.rollback()
                    return f"CustomException:{exc.code}"

        disable_task = asyncio.create_task(writer())
        ready_waiter = asyncio.create_task(ready.wait())
        done, _ = await asyncio.wait({ready_waiter, disable_task}, timeout=20, return_when=asyncio.FIRST_COMPLETED)
        if disable_task in done and not ready_waiter.done():
            raise AssertionError(f"writer exited before controlled pause: {disable_task.result()}")
        await asyncio.wait_for(ready_waiter, 20)
        transfer_task = asyncio.create_task(transfer())
        await asyncio.wait_for(transfer_attempt.wait(), 20)
        # D 已持成员锁；T 必须正在等待同一行。放行 D 后，T 只能在锁后看到其提交结果。
        resume.set()
        writer_result = await asyncio.wait_for(disable_task, 20)
        transfer_result = await asyncio.wait_for(transfer_task, 20)
        assert writer_result == "committed", (kind, writer_result)

        async with sessions() as db:
            final = dict(
                (
                    await db.execute(
                        sa.text(
                            "SELECT o.member_id AS owner_member_id, m.status AS member_status, u.status AS user_status "
                            "FROM biz_tenant_owner o JOIN biz_tenant_member m ON m.id = :member_id "
                            "JOIN sys_user u ON u.id = m.user_id WHERE o.tenant_id = :tenant_id"
                        ),
                        {"member_id": target_member_id, "tenant_id": tenant_id},
                    )
                ).mappings().one()
            )
            admin_count = (
                await db.execute(sa.text("SELECT COUNT(*) FROM biz_tenant_admin WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            ).scalar_one()

        if kind == "admin":
            assert transfer_result == "committed", transfer_result
            assert final["owner_member_id"] == target_member_id
            assert admin_count == 0, "移交必须清理等待期间先提交的 Admin，Owner+Admin 不得共存"
        else:
            assert transfer_result == "CustomException:403", (kind, transfer_result)
            assert final["owner_member_id"] == owner_member_id
            if kind == "native":
                assert final["user_status"] == 1 and final["member_status"] == 0
            else:
                assert final["member_status"] == 1
    finally:
        resume.set()
        for task in (disable_task, transfer_task):
            if task is not None and not task.done():
                task.cancel()
        TenantRequestContext.clear()
        if tenant_id is not None:
            async with sessions() as db:
                await db.execute(sa.text("DELETE FROM biz_tenant_admin_permission WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_admin WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM plat_owner_transfer_audit WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_owner WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_member WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM plat_enterprise WHERE id = :tid"), {"tid": tenant_id})
                if owner_uid is not None:
                    await db.execute(sa.text("DELETE FROM sys_user WHERE id = :uid"), {"uid": owner_uid})
                if target_uid is not None:
                    await db.execute(sa.text("DELETE FROM sys_user WHERE id = :uid"), {"uid": target_uid})
                await db.commit()
        await engine.dispose()


@pytest.mark.parametrize("kind", ["platform", "tenant", "native"])
async def test_mysql_transfer_and_disable_controlled_interleave(test_client, kind: str) -> None:
    await _run_interleave(kind)


async def test_mysql_transfer_and_admin_controlled_interleave(test_client) -> None:
    await _run_interleave("admin")


class _PauseOwnerUpdate:
    def __init__(self, session, ready: asyncio.Event, resume: asyncio.Event):
        self.session = session
        self.ready = ready
        self.resume = resume
        self.paused = False

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def execute(self, statement, *args, **kwargs):
        if "update biz_tenant_owner set" in str(statement).lower() and not self.paused:
            self.paused = True
            self.ready.set()
            await self.resume.wait()
        return await self.session.execute(statement, *args, **kwargs)


async def test_mysql_cross_target_transfers_share_version_and_single_winner(test_client) -> None:
    """两个目标均先读 version=1 后放行 UPDATE，必须一成功一 409。"""
    engine = create_async_engine(
        os.environ["TEST_MYSQL_URL"], execution_options={"isolation_level": "READ COMMITTED"}, pool_size=3, max_overflow=1
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:10]
    code = f"R2VERSION-{suffix}"
    names = [f"r2version_{suffix}_{part}" for part in ("a", "b", "c")]
    resume = asyncio.Event()
    redis = AsyncMock()
    redis.keys = AsyncMock(return_value=[])
    tenant_id = owner_uid = target_uid = other_uid = None
    try:
        async with sessions() as db:
            ent = EnterpriseModel(enterprise_code=code, name=f"R2版本-{suffix}", status=1)
            users = [UserModel(username=name, password="x", name=name, status=0) for name in names]
            db.add_all([ent, *users])
            await db.flush()
            tenant_id = ent.id
            owner_uid, target_uid, other_uid = (user.id for user in users)
            members = [BizTenantMemberModel(tenant_id=tenant_id, user_id=user.id, status=0) for user in users]
            db.add_all(members)
            await db.flush()
            owner_member_id, target_member_id, other_member_id = (member.id for member in members)
            db.add(BizTenantOwnerModel(tenant_id=tenant_id, member_id=owner_member_id, version=1))
            await db.commit()

        async def transfer(target_id: int, ready: asyncio.Event):
            async with sessions() as db:
                paused = _PauseOwnerUpdate(db, ready, resume)
                try:
                    await execute_owner_transfer(
                        paused,
                        redis,
                        tenant_id=tenant_id,
                        target_member_id=target_id,
                        operator_user_id=None,
                        source="platform",
                        reason=f"R2版本-{suffix}",
                    )
                    await db.commit()
                    return "committed"
                except CustomException as exc:
                    await db.rollback()
                    return f"CustomException:{exc.code}"

        ready_a, ready_b = asyncio.Event(), asyncio.Event()
        task_a = asyncio.create_task(transfer(target_member_id, ready_a))
        task_b = asyncio.create_task(transfer(other_member_id, ready_b))
        await asyncio.wait_for(ready_a.wait(), 20)
        await asyncio.wait_for(ready_b.wait(), 20)
        resume.set()
        outcomes = await asyncio.gather(task_a, task_b)
        assert outcomes.count("committed") == 1, outcomes
        assert outcomes.count("CustomException:409") == 1, outcomes
        async with sessions() as db:
            owner_row = dict(
                (
                    await db.execute(
                        sa.text("SELECT member_id, version FROM biz_tenant_owner WHERE tenant_id = :tid"), {"tid": tenant_id}
                    )
                ).mappings().one()
            )
            assert owner_row["member_id"] in (target_member_id, other_member_id)
            assert owner_row["version"] == 2
    finally:
        resume.set()
        TenantRequestContext.clear()
        if tenant_id is not None:
            async with sessions() as db:
                await db.execute(sa.text("DELETE FROM plat_owner_transfer_audit WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_owner WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_member WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM plat_enterprise WHERE id = :tid"), {"tid": tenant_id})
                for uid in (owner_uid, target_uid, other_uid):
                    if uid is not None:
                        await db.execute(sa.text("DELETE FROM sys_user WHERE id = :uid"), {"uid": uid})
                await db.commit()
        await engine.dispose()


class _PauseFirstMemberLock:
    def __init__(self, session, ready: asyncio.Event, resume: asyncio.Event):
        self.session = session
        self.ready = ready
        self.resume = resume

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def execute(self, statement, *args, **kwargs):
        if "update biz_tenant_member set status = status" in str(statement).lower() and not self.ready.is_set():
            self.ready.set()
            await self.resume.wait()
        return await self.session.execute(statement, *args, **kwargs)


async def test_mysql_old_owner_grant_scope_recomputed_after_transfer(test_client) -> None:
    engine = create_async_engine(
        os.environ["TEST_MYSQL_URL"], execution_options={"isolation_level": "READ COMMITTED"}, pool_size=3, max_overflow=1
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:10]
    code = f"R2OLDGRANT-{suffix}"
    names = [f"r2oldgrant_{suffix}_a", f"r2oldgrant_{suffix}_b"]
    ready, resume = asyncio.Event(), asyncio.Event()
    redis = AsyncMock()
    redis.keys = AsyncMock(return_value=[])
    tenant_id = owner_uid = target_uid = None
    grant_task = None
    try:
        async with sessions() as db:
            ent = EnterpriseModel(enterprise_code=code, name=f"R2旧Owner授权-{suffix}", status=1)
            ua = UserModel(username=names[0], password="x", name=names[0], status=0)
            ub = UserModel(username=names[1], password="x", name=names[1], status=0)
            db.add_all([ent, ua, ub])
            await db.flush()
            tenant_id, owner_uid, target_uid = ent.id, ua.id, ub.id
            owner = BizTenantMemberModel(tenant_id=tenant_id, user_id=owner_uid, status=0)
            target = BizTenantMemberModel(tenant_id=tenant_id, user_id=target_uid, status=0)
            db.add_all([owner, target])
            await db.flush()
            owner_member_id, target_member_id = owner.id, target.id
            db.add(BizTenantOwnerModel(tenant_id=tenant_id, member_id=owner_member_id, version=1))
            await db.commit()

        async def grant():
            async with sessions() as db:
                TenantRequestContext.set(TenantRequestContext(tenant_id=tenant_id, member_id=owner_member_id))
                paused = _PauseFirstMemberLock(db, ready, resume)
                try:
                    auth = AuthSchema(user=CoreUserSchema(id=owner_uid, is_superuser=False))
                    await TenantMemberService(auth, paused).set_admin(
                        AdminGrantSchema(member_id=owner_member_id, permissions=["tenant_admin_manage"])
                    )
                    return "committed"
                except CustomException as exc:
                    await db.rollback()
                    return f"CustomException:{exc.code}"
                finally:
                    TenantRequestContext.clear()

        grant_task = asyncio.create_task(grant())
        await asyncio.wait_for(ready.wait(), 20)
        async with sessions() as db:
            TenantRequestContext.clear()
            await execute_owner_transfer(
                db,
                redis,
                tenant_id=tenant_id,
                target_member_id=target_member_id,
                operator_user_id=None,
                source="platform",
                reason=f"R2旧Owner授权-{suffix}",
            )
            await db.commit()
        resume.set()
        outcome = await asyncio.wait_for(grant_task, 20)
        assert outcome == "CustomException:403", outcome
        async with sessions() as db:
            owner_id = (
                await db.execute(sa.text("SELECT member_id FROM biz_tenant_owner WHERE tenant_id = :tid"), {"tid": tenant_id})
            ).scalar_one()
            admin_count = (
                await db.execute(sa.text("SELECT COUNT(*) FROM biz_tenant_admin WHERE tenant_id = :tid"), {"tid": tenant_id})
            ).scalar_one()
            assert owner_id == target_member_id and admin_count == 0
    finally:
        resume.set()
        if grant_task is not None and not grant_task.done():
            grant_task.cancel()
        TenantRequestContext.clear()
        if tenant_id is not None:
            async with sessions() as db:
                await db.execute(sa.text("DELETE FROM biz_tenant_admin_permission WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_admin WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM plat_owner_transfer_audit WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_owner WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_member WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM plat_enterprise WHERE id = :tid"), {"tid": tenant_id})
                for uid in (owner_uid, target_uid):
                    if uid is not None:
                        await db.execute(sa.text("DELETE FROM sys_user WHERE id = :uid"), {"uid": uid})
                await db.commit()
        await engine.dispose()


async def test_mysql_native_write_rechecks_first_owner_creation(test_client) -> None:
    engine = create_async_engine(
        os.environ["TEST_MYSQL_URL"], execution_options={"isolation_level": "READ COMMITTED"}, pool_size=3, max_overflow=1
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:10]
    code = f"R2FIRSTOWNER-{suffix}"
    username = f"r2firstowner_{suffix}"
    ready, resume = asyncio.Event(), asyncio.Event()
    redis = AsyncMock()
    redis.keys = AsyncMock(return_value=[])
    tenant_id = user_id = None
    disable_task = None
    try:
        async with sessions() as db:
            ent = EnterpriseModel(enterprise_code=code, name=f"R2首Owner-{suffix}", status=1)
            user = UserModel(username=username, password="x", name=username, status=0)
            db.add_all([ent, user])
            await db.flush()
            tenant_id, user_id = ent.id, user.id
            await db.commit()

        async def disable():
            async with sessions() as db:
                paused = _PauseBeforeWrite(db, "native", ready, resume)
                try:
                    auth = AuthSchema(user=CoreUserSchema(id=0, is_superuser=True))
                    await UserService(auth, paused).set_available(BatchSetAvailable(ids=[user_id], status=1))
                    await db.commit()
                    return "committed"
                except CustomException as exc:
                    await db.rollback()
                    return f"CustomException:{exc.code}"

        disable_task = asyncio.create_task(disable())
        await asyncio.wait_for(ready.wait(), 20)
        async with sessions() as db:
            member = BizTenantMemberModel(tenant_id=tenant_id, user_id=user_id, status=0)
            db.add(member)
            await db.flush()
            await execute_owner_transfer(
                db,
                redis,
                tenant_id=tenant_id,
                target_member_id=member.id,
                operator_user_id=None,
                source="platform",
                reason=f"R2首Owner-{suffix}",
            )
            await db.commit()
        resume.set()
        outcome = await asyncio.wait_for(disable_task, 20)
        assert outcome == "CustomException:403", outcome
        async with sessions() as db:
            status = (await db.execute(sa.text("SELECT status FROM sys_user WHERE id = :uid"), {"uid": user_id})).scalar_one()
            owner_count = (
                await db.execute(sa.text("SELECT COUNT(*) FROM biz_tenant_owner WHERE tenant_id = :tid"), {"tid": tenant_id})
            ).scalar_one()
            assert status == 0 and owner_count == 1
    finally:
        resume.set()
        if disable_task is not None and not disable_task.done():
            disable_task.cancel()
        if tenant_id is not None:
            async with sessions() as db:
                await db.execute(sa.text("DELETE FROM plat_owner_transfer_audit WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_owner WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM biz_tenant_member WHERE tenant_id = :tid"), {"tid": tenant_id})
                await db.execute(sa.text("DELETE FROM plat_enterprise WHERE id = :tid"), {"tid": tenant_id})
                if user_id is not None:
                    await db.execute(sa.text("DELETE FROM sys_user WHERE id = :uid"), {"uid": user_id})
                await db.commit()
        await engine.dispose()
