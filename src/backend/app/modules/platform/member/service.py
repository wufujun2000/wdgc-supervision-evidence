"""租户成员与所有权服务（ADR-001）。

execute_owner_transfer 为平台侧与租户侧共用的原子移交：
- 单持有人记录 version 乐观锁（rowcount≠1 → 409），任何时刻不产生零 Owner 或双 Owner 的已提交状态；
- 同事务写 plat_owner_transfer_audit（append-only）；
- 双方旧会话清退（三键），新权限立即生效；原 Owner 不自动保留 Admin，项目任命与历史归属不变。
"""

import json

from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET, RedisInitKeyConfig
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.core.redis_crud import RedisCURD
from app.modules.platform.enterprise.crud import EnterpriseCRUD
from app.modules.system.user.crud import UserCRUD
from app.modules.tenant.member.model import BizTenantAdminModel, BizTenantOwnerModel

from .crud import AuditCRUD, MemberCRUD
from .model import PlatOwnerTransferAuditModel
from .schema import MemberBindSchema, MemberOutSchema, OwnerTransferOutSchema


def for_update_suffix(db: AsyncSession) -> str:
    """MySQL/PostgreSQL 锁后当前读；SQLite 无行锁语法，由真实 MySQL 交错测试验证互斥。"""
    return " FOR UPDATE" if db.get_bind().dialect.name in {"mysql", "postgresql"} else ""


async def lock_member_for_update(db: AsyncSession, member_id: int, tenant_id: int | None = None):
    """按共同顺序先锁成员，再以当前读返回成员及统一账号状态。"""
    from sqlalchemy import text

    params = {"id": member_id}
    tenant_clause = ""
    if tenant_id is not None:
        tenant_clause = " AND tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id
    await db.execute(text(f"UPDATE biz_tenant_member SET status = status WHERE id = :id{tenant_clause}"), params)
    row = await db.execute(
        text(
            "SELECT m.id AS id, m.tenant_id AS tenant_id, m.user_id AS user_id, m.status AS status,"
            " m.is_deleted AS is_deleted, u.status AS user_status, u.is_deleted AS user_deleted,"
            " u.is_superuser AS user_superuser"
            " FROM biz_tenant_member m JOIN sys_user u ON u.id = m.user_id"
            f" WHERE m.id = :id{tenant_clause}{for_update_suffix(db)}"
        ),
        params,
    )
    return row.mappings().first()


async def get_current_owner_row(db: AsyncSession, tenant_id: int, *, for_update: bool = False):
    """目标租户 Owner 裸 SQL 查询，不受操作者租户上下文过滤。"""
    from sqlalchemy import text

    suffix = for_update_suffix(db) if for_update else ""
    return (
        await db.execute(
            text(
                "SELECT id, member_id, version, tenant_id FROM biz_tenant_owner"
                f" WHERE tenant_id = :tenant_id AND is_deleted = FALSE{suffix}"
            ),
            {"tenant_id": tenant_id},
        )
    ).mappings().first()


async def purge_user_sessions(redis: Redis, user_ids: set[int]) -> int:
    """清退指定账号的全部会话（USER_SESSION/ACCESS/REFRESH 三键）。"""
    if not user_ids:
        return 0
    crud = RedisCURD(redis)
    keys = await crud.get_keys(f"{RedisInitKeyConfig.USER_SESSION.key}:*")
    purged = 0
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else str(key)
        raw = await crud.get(key_str)
        if not raw:
            continue
        try:
            session_info = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(session_info, dict) or session_info.get("user_id") not in user_ids:
            continue
        session_id = key_str.rsplit(":", 1)[-1]
        await crud.delete(
            f"{RedisInitKeyConfig.USER_SESSION.key}:{session_id}",
            f"{RedisInitKeyConfig.ACCESS_TOKEN.key}:{session_id}",
            f"{RedisInitKeyConfig.REFRESH_TOKEN.key}:{session_id}",
        )
        purged += 1
    return purged


async def execute_owner_transfer(
    db: AsyncSession,
    redis: Redis,
    *,
    tenant_id: int,
    target_member_id: int,
    operator_user_id: int | None,
    source: str,
    reason: str,
) -> OwnerTransferOutSchema:
    """原子所有权移交（平台/租户共用；调用方负责发起方权限与冻结规则校验）。"""
    if source not in ("platform", "tenant"):
        raise CustomException(msg="非法移交来源", code=RET.ERROR.code)

    from sqlalchemy import text

    # 共同锁顺序：先锁目标成员，再读/改 Owner；锁后以当前读同时校验成员及统一账号状态。
    target = await lock_member_for_update(db, target_member_id)
    if not target or target["is_deleted"] or target["user_deleted"]:
        raise CustomException(msg="目标成员不存在", code=RET.NOT_FOUND.code)
    if target["user_superuser"]:
        raise CustomException(msg="超级管理员账号禁止成为企业拥有者", code=RET.FORBIDDEN.code)
    if target["tenant_id"] != tenant_id:
        raise CustomException(msg="目标必须是本租户的有效成员，禁止跨租户移交", code=RET.FORBIDDEN.code)
    if target["status"] != 0 or target["user_status"] != 0:
        raise CustomException(msg="目标成员或账号已停用，不能成为企业拥有者", code=RET.FORBIDDEN.code)

    # 保留 version 乐观锁：并发移交只允许一个成功；裸 SQL 不受操作者租户上下文过滤。
    owner = await get_current_owner_row(db, tenant_id)
    if owner and owner["member_id"] == target_member_id:
        raise CustomException(msg="目标成员已是当前企业拥有者", code=RET.CONFLICT.code)
    from_member_id = owner["member_id"] if owner else None

    if owner:
        # version 乐观锁：并发移交仅一个成功，其余 409（防双 Owner/零 Owner）
        new_version = owner["version"] + 1
        result = await db.execute(
            text("UPDATE biz_tenant_owner SET member_id = :new, version = :v WHERE tenant_id = :t AND version = :expected"),
            {"new": target_member_id, "v": new_version, "t": tenant_id, "expected": owner["version"]},
        )
        if result.rowcount != 1:
            raise CustomException(msg="所有权已变更，请刷新后重试", code=RET.CONFLICT.code)
    else:
        # 无 Owner（开通初始化/平台补设）：tenant_id 唯一约束兜底并发补设
        db.add(BizTenantOwnerModel(tenant_id=tenant_id, member_id=target_member_id, version=1))
        new_version = 1

    # 成员仍由本事务入口处的行锁保护；后续 Admin 清理与 Owner 变更同提交。
    # B-01：清除原 Owner 与新 Owner 的普通 Admin 记录及权限（需要 Admin 由新 Owner 事后另行授权）。
    # 与 Owner 读写同用 text() 裸 SQL：操作者可能属于其他租户，不能被钩子过滤成不清理目标租户的 Admin。
    admin_member_ids = [mid for mid in (from_member_id, target_member_id) if mid is not None]
    if admin_member_ids:
        from sqlalchemy import bindparam

        admin_rows = (
            (
                await db.execute(
                    text(f"SELECT id FROM biz_tenant_admin WHERE member_id IN :ids{for_update_suffix(db)}").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": admin_member_ids},
                )
            )
            .scalars()
            .all()
        )
        if admin_rows:
            await db.execute(
                text("DELETE FROM biz_tenant_admin_permission WHERE admin_id IN :ids").bindparams(bindparam("ids", expanding=True)),
                {"ids": admin_rows},
            )
            await db.execute(
                text("DELETE FROM biz_tenant_admin WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
                {"ids": admin_rows},
            )

    db.add(
        PlatOwnerTransferAuditModel(
            source=source,
            operator_user_id=operator_user_id,
            tenant_id=tenant_id,
            from_member_id=from_member_id,
            to_member_id=target_member_id,
            reason=reason,
            result="success",
        )
    )
    await db.flush()

    # 双方旧会话清退，新权限立即生效；账号本身、项目任命与历史归属不变
    user_ids = {target["user_id"]}
    if from_member_id is not None:
        old_user_id = (
            await db.execute(text("SELECT user_id FROM biz_tenant_member WHERE id = :id"), {"id": from_member_id})
        ).scalar_one_or_none()
        if old_user_id is not None:
            user_ids.add(old_user_id)
    purged = await purge_user_sessions(redis, user_ids)
    logger.info("所有权移交完成: tenant={}, from={}, to={}, 清退会话数={}", tenant_id, from_member_id, target_member_id, purged)
    return OwnerTransferOutSchema(tenant_id=tenant_id, from_member_id=from_member_id, to_member_id=target_member_id, version=new_version)


async def audit_transfer_failure(
    *, tenant_id: int, target_member_id: int, operator_user_id: int | None, source: str, reason: str, result: str = "failed"
) -> None:
    """M-11：失败/冲突移交的独立短事务审计（业务事务回滚也不丢审计）。

    OperationLogRoute 只在原处理器正常返回时记录，覆盖不了 CustomException 的结构化 from/to/result。
    """
    from app.core.database import async_db_session

    async with async_db_session() as session, session.begin():
        owner = await get_current_owner_row(session, tenant_id)
        session.add(
            PlatOwnerTransferAuditModel(
                source=source,
                operator_user_id=operator_user_id,
                tenant_id=tenant_id,
                from_member_id=owner.member_id if owner else None,
                to_member_id=target_member_id,
                reason=reason,
                result=result,
            )
        )


async def create_login_account(auth: AuthSchema, db: AsyncSession, account):
    """新建登录账号（开通/新增成员共用）：基线哈希＋种子 USER 角色（data_scope=1 仅本人）。

    无角色用户在原生数据权限下连 current/info 自查都受限；租户域业务不受平台 Permission 影响。
    """
    from sqlalchemy import select

    from app.modules.platform.enterprise.schema import AdminAccountSchema
    from app.modules.system.role.model import RoleModel
    from app.modules.system.user.model import UserModel, UserRolesModel
    from app.utils.password_util import PwdUtil

    if not isinstance(account, AdminAccountSchema):
        raise CustomException(msg="账号参数无效", code=RET.ERROR.code)

    # M-10：跨账号/种子角色查询必须系统级精确匹配，不能被操作者平台 DATA_SCOPE_SELF 误拦
    if (
        await db.execute(select(UserModel.id).where(UserModel.username == account.username, UserModel.is_deleted == False))  # noqa: E712
    ).scalars().first():
        raise CustomException(msg="已存在相同用户名称的账号", code=RET.DATAEXIST.code)
    raw_password = account.password
    initial_password: str | None = None
    if raw_password is None:
        raw_password = PwdUtil.generate_strong_password()
        initial_password = raw_password
    new_user = await UserCRUD(auth, db).create(
        data={
            "username": account.username,
            "name": account.name,
            "mobile": account.mobile,
            "password": await PwdUtil.ahash_password(password=raw_password),
            "is_superuser": False,
            "status": 0,
        }
    )
    default_role = (
        await db.execute(select(RoleModel).where(RoleModel.code == "USER", RoleModel.is_deleted == False))  # noqa: E712
    ).scalars().first()
    if default_role:
        db.add(UserRolesModel(user_id=new_user.id, role_id=default_role.id))
        await db.flush()
    else:
        logger.warning("种子角色 USER（普通用户）缺失，账号 {} 未分配默认角色", new_user.username)
    return new_user, initial_password


class MemberService:
    """平台侧成员管理：列表/补绑/停用/移交/审计（仅超管或平台专门权限）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _require_superadmin(self) -> None:
        if not self.auth.user.is_superuser:
            raise CustomException(msg="仅平台管理员可操作", code=RET.FORBIDDEN.code)

    def _require_transfer_permission(self) -> None:
        """平台移交专门权限：默认仅 SUPERADMIN；预留 module_platform:enterprise:transfer 平台角色授予。"""
        if self.auth.user.is_superuser or "module_platform:enterprise:transfer" in self.auth.permissions:
            return
        raise CustomException(msg="缺少平台所有权移交权限", code=RET.FORBIDDEN.code)

    def _require_member_read_permission(self) -> None:
        """候选成员读取：超管或具有移交专门权限的平台账号（移交弹窗需要候选列表）。"""
        if self.auth.user.is_superuser or "module_platform:enterprise:transfer" in self.auth.permissions:
            return
        raise CustomException(msg="缺少平台成员读取权限", code=RET.FORBIDDEN.code)

    async def list_by_tenant(self, tenant_id: int) -> list[MemberOutSchema]:
        self._require_member_read_permission()
        await EnterpriseCRUD(self.auth, self.db).get_or_404(id=tenant_id, msg="企业租户不存在")
        # M-04：平台域跨租户读取不受操作者所属租户的 ORM 钩子过滤，临时清除上下文
        from app.core.tenant_context import TenantRequestContext

        saved = TenantRequestContext.get()
        TenantRequestContext.clear()
        try:
            members = await MemberCRUD(self.auth, self.db).get_list(search={"tenant_id": tenant_id}, preload=["user"])
            owner = await get_current_owner_row(self.db, tenant_id)
            admin_member_ids = set(
                (
                    await self.db.execute(
                        select(BizTenantAdminModel.member_id).where(
                            BizTenantAdminModel.tenant_id == tenant_id, BizTenantAdminModel.is_deleted == False  # noqa: E712
                        )
                    )
                )
                .scalars()
                .all()
            )
            result: list[MemberOutSchema] = []
            for member in members:
                out = MemberOutSchema.model_validate(member)
                if member.user:
                    out.username = member.user.username
                    out.name = member.user.name
                out.is_owner = bool(owner and owner.member_id == member.id)
                out.is_admin = member.id in admin_member_ids
                result.append(out)
            return result
        finally:
            if saved is not None:
                TenantRequestContext.set(saved)

    async def bind(self, tenant_id: int, data: MemberBindSchema, redis: Redis) -> MemberOutSchema:
        """平台补绑成员；无 Owner 租户首名成员自动补 Owner（开通初始化路径之一）。"""
        self._require_superadmin()
        enterprise = await EnterpriseCRUD(self.auth, self.db).get_or_404(id=tenant_id, msg="企业租户不存在")
        if enterprise.status != 1:
            raise CustomException(msg="企业租户已被冻结，禁止绑定用户", code=RET.FORBIDDEN.code)
        user = await UserCRUD(self.auth, self.db).get(id=data.user_id)
        if not user:
            raise CustomException(msg="绑定用户不存在", code=RET.NOT_FOUND.code)
        if user.is_superuser:
            raise CustomException(msg="超级管理员账号禁止加入租户成员（超管走平台域）", code=RET.FORBIDDEN.code)
        if user.status != 0:
            raise CustomException(msg="绑定账号已停用，不能加入租户成员", code=RET.FORBIDDEN.code)
        if await MemberCRUD(self.auth, self.db).get(tenant_id=tenant_id, user_id=data.user_id):
            raise CustomException(msg="该账号已是本租户成员", code=RET.CONFLICT.code)

        member = await MemberCRUD(self.auth, self.db).create(
            data={"tenant_id": tenant_id, "user_id": data.user_id, "emp_no": data.emp_no, "status": 0}
        )
        if not await get_current_owner_row(self.db, tenant_id):
            await execute_owner_transfer(
                self.db,
                redis,
                tenant_id=tenant_id,
                target_member_id=member.id,
                operator_user_id=self.auth.user.id,
                source="platform",
                reason="平台补设企业拥有者",
            )
        owner = await get_current_owner_row(self.db, tenant_id)
        out = MemberOutSchema.model_validate(member)
        out.username = user.username
        out.name = user.name
        out.is_owner = bool(owner and owner.member_id == member.id)
        await self.db.commit()
        return out

    async def disable(self, member_id: int, redis: Redis) -> None:
        """先锁成员并锁后拒绝当前 Owner，再原子停用；commit 前缓存会话清退字段。"""
        from sqlalchemy import text

        self._require_superadmin()
        member = await lock_member_for_update(self.db, member_id)
        if not member:
            raise CustomException(msg="成员不存在", code=RET.NOT_FOUND.code)
        owner = await get_current_owner_row(self.db, member["tenant_id"], for_update=True)
        if owner and owner["member_id"] == member_id:
            raise CustomException(msg="企业拥有者须先移交所有权，禁止直接停用", code=RET.FORBIDDEN.code)
        target_user_id = member["user_id"]
        await self.db.execute(text("UPDATE biz_tenant_member SET status = 1 WHERE id = :id AND status = 0"), {"id": member_id})
        await self.db.commit()
        await purge_user_sessions(redis, {target_user_id})

    async def transfer(self, tenant_id: int, target_member_id: int, reason: str, redis: Redis) -> OwnerTransferOutSchema:
        """平台侧移交：冻结期间仍保留处置能力；操作人不因此成为 Owner。"""
        try:
            self._require_transfer_permission()
            await EnterpriseCRUD(self.auth, self.db).get_or_404(id=tenant_id, msg="企业租户不存在")
            result = await execute_owner_transfer(
                self.db,
                redis,
                tenant_id=tenant_id,
                target_member_id=target_member_id,
                operator_user_id=self.auth.user.id,
                source="platform",
                reason=reason,
            )
            await self.db.commit()
            return result
        except CustomException:
            # 先释放成员/Owner 行锁，再由独立短事务写失败审计。
            await self.db.rollback()
            await audit_transfer_failure(
                tenant_id=tenant_id,
                target_member_id=target_member_id,
                operator_user_id=self.auth.user.id,
                source="platform",
                reason=reason,
            )
            raise

    async def list_audit(self, tenant_id: int) -> list[PlatOwnerTransferAuditModel]:
        self._require_superadmin()
        return await AuditCRUD(self.auth, self.db).get_list(search={"tenant_id": tenant_id}, order_by=[{"id": "desc"}])
