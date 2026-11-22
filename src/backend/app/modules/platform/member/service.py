"""租户成员与所有权服务（ADR-001）。

execute_owner_transfer 为平台侧与租户侧共用的原子移交：
- 单持有人记录 version 乐观锁（rowcount≠1 → 409），任何时刻不产生零 Owner 或双 Owner 的已提交状态；
- 同事务写 plat_owner_transfer_audit（append-only）；
- 双方旧会话清退（三键），新权限立即生效；原 Owner 不自动保留 Admin，项目任命与历史归属不变。
"""

import json

from redis.asyncio.client import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET, RedisInitKeyConfig
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.core.redis_crud import RedisCURD
from app.core.tenant_permission import get_current_owner
from app.modules.platform.enterprise.crud import EnterpriseCRUD
from app.modules.system.user.crud import UserCRUD
from app.modules.tenant.member.model import BizTenantAdminModel, BizTenantMemberModel, BizTenantOwnerModel

from .crud import AuditCRUD, MemberCRUD
from .model import PlatOwnerTransferAuditModel
from .schema import MemberBindSchema, MemberOutSchema, OwnerTransferOutSchema


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

    # 跨租户校验须看到非本租户目标：do_orm_execute 兜底钩子会把 ORM 查询过滤为本租户，
    # 这里用 text() 裸 SQL（钩子边界外）取目标，区分「跨租户 403 / 停用 403 / 不存在 404」。
    from sqlalchemy import text

    target = (
        await db.execute(
            text("SELECT id, tenant_id, user_id, status, is_deleted FROM biz_tenant_member WHERE id = :id"),
            {"id": target_member_id},
        )
    ).mappings().first()
    if not target or target["is_deleted"]:
        raise CustomException(msg="目标成员不存在", code=RET.NOT_FOUND.code)
    if target["tenant_id"] != tenant_id:
        raise CustomException(msg="目标必须是本租户的有效成员，禁止跨租户移交", code=RET.FORBIDDEN.code)
    if target["status"] != 0:
        raise CustomException(msg="目标成员已停用，不能成为企业拥有者", code=RET.FORBIDDEN.code)

    owner = await get_current_owner(db, tenant_id)
    if owner and owner.member_id == target_member_id:
        raise CustomException(msg="目标成员已是当前企业拥有者", code=RET.CONFLICT.code)
    from_member_id = owner.member_id if owner else None

    if owner:
        # version 乐观锁：并发移交仅一个成功，其余 409（防双 Owner/零 Owner）。
        # 先取目标版本号：批量 UPDATE 同步内存对象后 owner.version 已是新值，不能再 +1
        new_version = owner.version + 1
        result = await db.execute(
            update(BizTenantOwnerModel)
            .where(BizTenantOwnerModel.tenant_id == tenant_id, BizTenantOwnerModel.version == owner.version)
            .values(member_id=target_member_id, version=new_version)
        )
        if result.rowcount != 1:
            raise CustomException(msg="所有权已变更，请刷新后重试", code=RET.CONFLICT.code)
    else:
        # 无 Owner（开通初始化/平台补设）：tenant_id 唯一约束兜底并发补设
        db.add(BizTenantOwnerModel(tenant_id=tenant_id, member_id=target_member_id, version=1))
        new_version = 1

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
        old_member = await db.get(BizTenantMemberModel, from_member_id)
        if old_member:
            user_ids.add(old_member.user_id)
    purged = await purge_user_sessions(redis, user_ids)
    logger.info("所有权移交完成: tenant={}, from={}, to={}, 清退会话数={}", tenant_id, from_member_id, target_member_id, purged)
    return OwnerTransferOutSchema(tenant_id=tenant_id, from_member_id=from_member_id, to_member_id=target_member_id, version=new_version)


async def create_login_account(auth: AuthSchema, db: AsyncSession, account):
    """新建登录账号（开通/新增成员共用）：基线哈希＋种子 USER 角色（data_scope=1 仅本人）。

    无角色用户在原生数据权限下连 current/info 自查都受限；租户域业务不受平台 Permission 影响。
    """
    from app.modules.platform.enterprise.schema import AdminAccountSchema
    from app.modules.system.role.crud import RoleCRUD
    from app.modules.system.user.model import UserRolesModel
    from app.utils.password_util import PwdUtil

    if not isinstance(account, AdminAccountSchema):
        raise CustomException(msg="账号参数无效", code=RET.ERROR.code)
    if await UserCRUD(auth, db).get(username=account.username):
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
    default_role = await RoleCRUD(auth, db).get(code="USER")
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
        """平台移交专门权限：默认仅 SUPERADMIN；预留 platform:owner:transfer 平台角色授予。"""
        from app.core.tenant_permission import PLATFORM_OWNER_TRANSFER_PERMISSION

        if self.auth.user.is_superuser or PLATFORM_OWNER_TRANSFER_PERMISSION in self.auth.permissions:
            return
        raise CustomException(msg="缺少平台所有权移交权限", code=RET.FORBIDDEN.code)

    async def list_by_tenant(self, tenant_id: int) -> list[MemberOutSchema]:
        self._require_superadmin()
        await EnterpriseCRUD(self.auth, self.db).get_or_404(id=tenant_id, msg="企业租户不存在")
        members = await MemberCRUD(self.auth, self.db).get_list(search={"tenant_id": tenant_id}, preload=["user"])
        owner = await get_current_owner(self.db, tenant_id)
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
        if await MemberCRUD(self.auth, self.db).get(tenant_id=tenant_id, user_id=data.user_id):
            raise CustomException(msg="该账号已是本租户成员", code=RET.CONFLICT.code)

        member = await MemberCRUD(self.auth, self.db).create(
            data={"tenant_id": tenant_id, "user_id": data.user_id, "emp_no": data.emp_no, "status": 0}
        )
        if not await get_current_owner(self.db, tenant_id):
            await execute_owner_transfer(
                self.db,
                redis,
                tenant_id=tenant_id,
                target_member_id=member.id,
                operator_user_id=self.auth.user.id,
                source="platform",
                reason="平台补设企业拥有者",
            )
        owner = await get_current_owner(self.db, tenant_id)
        out = MemberOutSchema.model_validate(member)
        out.username = user.username
        out.name = user.name
        out.is_owner = bool(owner and owner.member_id == member.id)
        await self.db.commit()
        return out

    async def disable(self, member_id: int, redis: Redis) -> None:
        """成员停用（不物理删除，保留历史归属）；当前 Owner 一律先移交，禁止直接停用。"""
        self._require_superadmin()
        member = await MemberCRUD(self.auth, self.db).get_or_404(id=member_id, msg="成员不存在")
        owner = await get_current_owner(self.db, member.tenant_id)
        if owner and owner.member_id == member.id:
            raise CustomException(msg="企业拥有者须先移交所有权，禁止直接停用", code=RET.FORBIDDEN.code)
        await MemberCRUD(self.auth, self.db).update(id=member.id, data={"status": 1})
        await self.db.commit()
        await purge_user_sessions(redis, {member.user_id})

    async def transfer(self, tenant_id: int, target_member_id: int, reason: str, redis: Redis) -> OwnerTransferOutSchema:
        """平台侧移交：冻结期间仍保留处置能力；操作人不因此成为 Owner。"""
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

    async def list_audit(self, tenant_id: int) -> list[PlatOwnerTransferAuditModel]:
        self._require_superadmin()
        return await AuditCRUD(self.auth, self.db).get_list(search={"tenant_id": tenant_id}, order_by=[{"id": "desc"}])
