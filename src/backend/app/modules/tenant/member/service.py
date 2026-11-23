"""租户侧成员、管理员与所有权服务（ADR-001）。

权限校验全部在服务端：普通管理走 require_permission，所有权专属走 require_owner。
平台超管账号禁止加入租户成员；当前 Owner 不得进入普通角色分配列表。
"""

from redis.asyncio.client import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.core.tenant_context import TenantRequestContext
from app.core.tenant_permission import (
    DELEGABLE_PERMISSIONS,
    is_current_owner,
    require_owner,
    require_permission,
    validate_delegable_subset,
)
from app.modules.platform.enterprise.crud import EnterpriseCRUD
from app.modules.platform.member.crud import AuditCRUD, MemberCRUD, MemberIsolatedCRUD
from app.modules.platform.member.schema import MemberOutSchema, OwnerTransferOutSchema
from app.modules.platform.member.service import (
    execute_owner_transfer,
    for_update_suffix,
    get_current_owner_row,
    lock_member_for_update,
    purge_user_sessions,
)
from app.modules.system.user.model import UserModel
from app.modules.tenant.member.model import BizTenantAdminModel, BizTenantAdminPermissionModel, BizTenantMemberModel

from .schema import AdminGrantSchema, AdminPermissionUpdateSchema, MemberCreateSchema


class TenantMemberService:
    """租户侧成员/管理员/所有权服务（上下文 tenant_id + member_id 驱动）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _tenant_id(self) -> int:
        return TenantRequestContext.require_tenant_id()

    def _member_id(self) -> int:
        context = TenantRequestContext.get()
        if context is None or context.member_id is None:
            raise CustomException(msg="缺少租户成员上下文", code=RET.FORBIDDEN.code)
        return context.member_id

    async def _out(self, member: BizTenantMemberModel) -> MemberOutSchema:
        out = MemberOutSchema.model_validate(member)
        # M-10：优先消费预加载的 member.user（避免平台 DATA_SCOPE_SELF 重查误拦）；
        # 未预加载时用主键直查（db.get 不经 Permission），绝不走关系懒加载（MissingGreenlet）
        user = member.user if "user" in member.__dict__ and member.user is not None else await self.db.get(UserModel, member.user_id)
        if user:
            out.username = user.username
            out.name = user.name
        out.is_owner = await is_current_owner(self.db, member.tenant_id, member.id)
        out.is_admin = bool(
            (
                await self.db.execute(
                    select(BizTenantAdminModel.id).where(
                        BizTenantAdminModel.member_id == member.id, BizTenantAdminModel.is_deleted == False  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )
        return out

    # ── 成员管理 ────────────────────────────────────────────────
    async def create_member(self, data: MemberCreateSchema) -> MemberOutSchema:
        await require_permission(self.db, "tenant_member_manage")
        tenant_id = self._tenant_id()
        user_id = data.user_id
        username: str | None = None
        name: str | None = None
        if data.account:
            from app.modules.platform.member.service import create_login_account

            new_user, _ = await create_login_account(self.auth, self.db, data.account)
            user_id = new_user.id
            username, name = new_user.username, new_user.name
        else:
            # M-10：主键直查（不经 Permission），避免 Owner 绑定他人被 DATA_SCOPE_SELF 误判不存在
            user = await self.db.get(UserModel, user_id)
            if not user or user.is_deleted:
                raise CustomException(msg="绑定用户不存在", code=RET.NOT_FOUND.code)
            if user.status != 0:
                raise CustomException(msg="绑定账号已停用，不能加入租户成员", code=RET.FORBIDDEN.code)
            if user.is_superuser:
                raise CustomException(msg="超级管理员账号禁止加入租户成员", code=RET.FORBIDDEN.code)
            username, name = user.username, user.name

        if await MemberCRUD(self.auth, self.db).get(tenant_id=tenant_id, user_id=user_id):
            raise CustomException(msg="该账号已是本租户成员", code=RET.CONFLICT.code)
        member = await MemberIsolatedCRUD(self.auth, self.db).create(
            data={"user_id": user_id, "emp_no": data.emp_no, "status": 0}
        )
        out = await self._out(member)
        out.username, out.name = username, name
        await self.db.commit()
        return out

    async def list_members(self) -> list[MemberOutSchema]:
        members = await MemberIsolatedCRUD(self.auth, self.db).get_list(preload=["user"])
        return [await self._out(member) for member in members]

    async def disable_member(self, member_id: int, redis: Redis) -> None:
        from sqlalchemy import text

        await require_permission(self.db, "tenant_member_manage")
        tenant_id = self._tenant_id()
        member = await lock_member_for_update(self.db, member_id, tenant_id)
        if not member:
            raise CustomException(msg="成员不存在", code=RET.NOT_FOUND.code)
        owner = await get_current_owner_row(self.db, tenant_id, for_update=True)
        if owner and owner["member_id"] == member_id:
            raise CustomException(msg="企业拥有者须先移交所有权，禁止直接停用", code=RET.FORBIDDEN.code)
        target_user_id = member["user_id"]
        await self.db.execute(
            text("UPDATE biz_tenant_member SET status = 1 WHERE id = :id AND tenant_id = :tenant_id AND status = 0"),
            {"id": member_id, "tenant_id": tenant_id},
        )
        await self.db.commit()
        await purge_user_sessions(redis, {target_user_id})

    # ── 企业管理员及权限管理 ─────────────────────────────────────
    async def _grant_admin(self, member: BizTenantMemberModel, permissions: list[str]) -> None:
        from sqlalchemy import text

        locked = await lock_member_for_update(self.db, member.id, member.tenant_id)
        if not locked:
            raise CustomException(msg="成员不存在", code=RET.NOT_FOUND.code)
        if locked["status"] != 0:
            raise CustomException(msg="停用成员不能设为企业管理员", code=RET.FORBIDDEN.code)
        owner = await get_current_owner_row(self.db, member.tenant_id, for_update=True)
        if owner and owner["member_id"] == member.id:
            raise CustomException(msg="企业拥有者不得进入普通角色分配列表", code=RET.FORBIDDEN.code)

        # 目标成员与 Owner 行锁定后重算操作者 scope，避免旧 Owner 在移交后沿用锁前全权限。
        context = TenantRequestContext.get()
        if context is None or context.tenant_id is None or context.member_id is None:
            scope: set[str] = set()
        elif owner and owner["member_id"] == context.member_id:
            scope = set(DELEGABLE_PERMISSIONS)
        else:
            rows = (
                await self.db.execute(
                    text(
                        "SELECT p.permission_code FROM biz_tenant_admin_permission p"
                        " JOIN biz_tenant_admin a ON a.id = p.admin_id"
                        " WHERE a.tenant_id = :tenant_id AND a.member_id = :member_id"
                        " AND a.is_deleted = FALSE AND p.is_deleted = FALSE"
                        f" ORDER BY p.permission_code{for_update_suffix(self.db)}"
                    ),
                    {"tenant_id": context.tenant_id, "member_id": context.member_id},
                )
            ).scalars().all()
            scope = set(rows)
        validate_delegable_subset(permissions, scope)

        admin_id = (
            await self.db.execute(
                text(
                    "SELECT id FROM biz_tenant_admin WHERE member_id = :member_id"
                    f" AND is_deleted = FALSE{for_update_suffix(self.db)}"
                ),
                {"member_id": member.id},
            )
        ).scalar_one_or_none()
        if admin_id is None:
            admin = BizTenantAdminModel(tenant_id=member.tenant_id, member_id=member.id)
            self.db.add(admin)
            await self.db.flush()
            admin_id = admin.id
        # 替换权限集：旧授予物理清除（当前态授权，操作日志审计），重新写入。
        await self.db.execute(delete(BizTenantAdminPermissionModel).where(BizTenantAdminPermissionModel.admin_id == admin_id))
        for code in dict.fromkeys(permissions):
            self.db.add(BizTenantAdminPermissionModel(tenant_id=member.tenant_id, admin_id=admin_id, permission_code=code))
        await self.db.flush()

    async def set_admin(self, data: AdminGrantSchema) -> MemberOutSchema:
        await require_permission(self.db, "tenant_admin_manage")
        member = await MemberIsolatedCRUD(self.auth, self.db).get_or_404(id=data.member_id, msg="成员不存在")
        await self._grant_admin(member, data.permissions)
        out = await self._out(member)
        await self.db.commit()
        return out

    async def update_admin_permissions(self, member_id: int, data: AdminPermissionUpdateSchema) -> MemberOutSchema:
        await require_permission(self.db, "tenant_admin_manage")
        member = await MemberIsolatedCRUD(self.auth, self.db).get_or_404(id=member_id, msg="成员不存在")
        # M-13：Owner 不得作为普通权限调整目标
        if await is_current_owner(self.db, member.tenant_id, member.id):
            raise CustomException(msg="企业拥有者身份不可经普通授权变更", code=RET.FORBIDDEN.code)
        admin = (
            (
                await self.db.execute(
                    select(BizTenantAdminModel).where(
                        BizTenantAdminModel.member_id == member.id, BizTenantAdminModel.is_deleted == False  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )
        if not admin:
            raise CustomException(msg="目标成员不是企业管理员", code=RET.NOT_FOUND.code)
        await self._grant_admin(member, data.permissions)
        out = await self._out(member)
        await self.db.commit()
        return out

    async def revoke_admin(self, member_id: int) -> MemberOutSchema:
        await require_permission(self.db, "tenant_admin_manage")
        member = await MemberIsolatedCRUD(self.auth, self.db).get_or_404(id=member_id, msg="成员不存在")
        if await is_current_owner(self.db, member.tenant_id, member.id):
            raise CustomException(msg="企业拥有者身份不可经普通授权变更", code=RET.FORBIDDEN.code)
        admin = (
            (
                await self.db.execute(
                    select(BizTenantAdminModel).where(
                        BizTenantAdminModel.member_id == member.id, BizTenantAdminModel.is_deleted == False  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )
        if admin:
            await self.db.execute(delete(BizTenantAdminPermissionModel).where(BizTenantAdminPermissionModel.admin_id == admin.id))
            await self.db.delete(admin)
            await self.db.flush()
        out = await self._out(member)
        await self.db.commit()
        return out

    # ── 所有权移交与审计 ─────────────────────────────────────────
    async def transfer_owner(self, target_member_id: int, reason: str, redis: Redis) -> OwnerTransferOutSchema:
        tenant_id = self._tenant_id()
        try:
            await require_owner(self.db)
            enterprise = await EnterpriseCRUD(self.auth, self.db).get_or_404(id=tenant_id, msg="企业租户不存在")
            if enterprise.status != 1:
                raise CustomException(msg="租户冻结期间禁止租户侧移交，请联系平台处置", code=RET.FORBIDDEN.code)
            result = await execute_owner_transfer(
                self.db,
                redis,
                tenant_id=tenant_id,
                target_member_id=target_member_id,
                operator_user_id=self.auth.user.id,
                source="tenant",
                reason=reason,
            )
            await self.db.commit()
            return result
        except CustomException:
            from app.modules.platform.member.service import audit_transfer_failure

            await self.db.rollback()
            await audit_transfer_failure(
                tenant_id=tenant_id,
                target_member_id=target_member_id,
                operator_user_id=self.auth.user.id,
                source="tenant",
                reason=reason,
            )
            raise

    async def list_owner_audit(self):
        await require_owner(self.db)
        return await AuditCRUD(self.auth, self.db).get_list(search={"tenant_id": self._tenant_id()}, order_by=[{"id": "desc"}])
