"""租户权限目录与权限引擎（ADR-001）。

目录为代码静态、平台受控变更（变更走代码评审＋操作日志审计），租户不得自行发明系统级角色。
严禁把租户角色或项目角色写入平台原生 sys_user_roles。

两类服务端校验：
- require_permission(code)：普通管理功能。当前有效 Owner 默认通过；企业管理员按
  biz_tenant_admin + biz_tenant_admin_permission 授权判断；delegable 权限才可授予。
- require_owner()：所有权专属功能（owner_only，目前至少 tenant_owner_transfer）。
  只认 biz_tenant_owner 有效记录，权限数量、菜单可见性、TENANT_ADMIN 身份均不可替代。

项目维度：
- require_project_role(project_id, roles)：按当前项目有效任命（status=0 在任）判定，
  企业 Owner/Admin 未经项目任命同样 403（不得代行项目法定职责）。
- require_hazard_scope(pm, hazard_code)：SZ 全部危大；SP 按 biz_project_member_hazard；
  SA 以本人任务为范围（由业务层另行过滤，本校验点拒绝按专监危大动作）。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET
from app.core.exceptions import CustomException
from app.core.tenant_context import TenantRequestContext

# ── 角色模板（平台维护，租户不可发明） ──
TENANT_ROLE_OWNER = "TENANT_OWNER"
TENANT_ROLE_ADMIN = "TENANT_ADMIN"
PROJECT_ROLES = ("SZ", "SP", "SA")

# ── 权限目录 ──
# 可委托权限：可按规则授予企业管理员（0~全部）
DELEGABLE_PERMISSIONS: frozenset[str] = frozenset(
    {"tenant_member_manage", "tenant_admin_manage", "project_manage", "project_member_assign"}
)
# 所有权专属权限：不可委托，任何授权不得包含
OWNER_ONLY_PERMISSIONS: frozenset[str] = frozenset({"tenant_owner_transfer"})
# 平台侧所有权移交专门权限标识（默认仅 SUPERADMIN；预留平台角色授予，不建菜单）
PLATFORM_OWNER_TRANSFER_PERMISSION = "platform:owner:transfer"

# 危大类别编码范围（与既有架构裁定 3 一致：01~12）
HAZARD_CODES: frozenset[str] = frozenset(f"{i:02d}" for i in range(1, 13))


def validate_delegable_subset(codes: list[str], allowed: set[str] | frozenset[str]) -> None:
    """校验授权集合：必须 delegable 且不超操作者自身可转授范围。"""
    for code in codes:
        if code in OWNER_ONLY_PERMISSIONS:
            raise CustomException(msg=f"权限 {code} 为所有权专属，不可委托", code=RET.FORBIDDEN.code)
        if code not in DELEGABLE_PERMISSIONS:
            raise CustomException(msg=f"权限 {code} 不在可委托目录", code=RET.FORBIDDEN.code)
        if code not in allowed:
            raise CustomException(msg=f"授权超出操作者自身可转授范围: {code}", code=RET.FORBIDDEN.code)


async def get_current_owner(db: AsyncSession, tenant_id: int):
    """读取当前有效所有权记录（无则 None，调用方决定拒绝语义）。"""
    from app.modules.tenant.member.model import BizTenantOwnerModel

    return (
        (
            await db.execute(
                select(BizTenantOwnerModel).where(
                    BizTenantOwnerModel.tenant_id == tenant_id, BizTenantOwnerModel.is_deleted == False  # noqa: E712
                )
            )
        )
        .scalars()
        .first()
    )


async def require_owner(db: AsyncSession):
    """只认可当前有效所有权记录；Admin 全权限也拒绝（验收不变式）。"""
    from app.modules.tenant.member.model import BizTenantOwnerModel

    context = TenantRequestContext.get()
    if context is None or context.tenant_id is None or context.member_id is None:
        raise CustomException(msg="缺少租户成员上下文", code=RET.FORBIDDEN.code)
    owner = (
        (
            await db.execute(
                select(BizTenantOwnerModel).where(
                    BizTenantOwnerModel.tenant_id == context.tenant_id,
                    BizTenantOwnerModel.member_id == context.member_id,
                    BizTenantOwnerModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .first()
    )
    if not owner:
        raise CustomException(msg="仅企业拥有者可执行所有权专属操作", code=RET.FORBIDDEN.code)
    return owner


async def is_current_owner(db: AsyncSession, tenant_id: int, member_id: int) -> bool:
    """目标成员是否为当前 Owner（停用/降权 Owner 等保护判断用）。"""
    owner = await get_current_owner(db, tenant_id)
    return bool(owner and owner.member_id == member_id)


async def require_permission(db: AsyncSession, code: str) -> None:
    """普通管理功能校验：Owner 默认通过；Admin 按授权；owner_only 转 require_owner。"""
    if code in OWNER_ONLY_PERMISSIONS:
        await require_owner(db)
        return
    if code not in DELEGABLE_PERMISSIONS:
        raise CustomException(msg=f"权限 {code} 不在权限目录", code=RET.FORBIDDEN.code)
    context = TenantRequestContext.get()
    if context is None or context.tenant_id is None or context.member_id is None:
        raise CustomException(msg="缺少租户成员上下文", code=RET.FORBIDDEN.code)
    if await is_current_owner(db, context.tenant_id, context.member_id):
        return
    from app.modules.tenant.member.model import BizTenantAdminModel, BizTenantAdminPermissionModel

    admin = (
        (
            await db.execute(
                select(BizTenantAdminModel).where(
                    BizTenantAdminModel.tenant_id == context.tenant_id,
                    BizTenantAdminModel.member_id == context.member_id,
                    BizTenantAdminModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .first()
    )
    if not admin:
        raise CustomException(msg=f"缺少权限: {code}", code=RET.FORBIDDEN.code)
    granted = (
        (
            await db.execute(
                select(BizTenantAdminPermissionModel.id).where(
                    BizTenantAdminPermissionModel.admin_id == admin.id,
                    BizTenantAdminPermissionModel.permission_code == code,
                    BizTenantAdminPermissionModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .first()
    )
    if not granted:
        raise CustomException(msg=f"缺少权限: {code}", code=RET.FORBIDDEN.code)


async def get_delegable_scope(db: AsyncSession) -> set[str]:
    """操作者自身可转授范围：Owner 全部 delegable；Admin 已授予集合；其余为空。"""
    context = TenantRequestContext.get()
    if context is None or context.tenant_id is None or context.member_id is None:
        return set()
    if await is_current_owner(db, context.tenant_id, context.member_id):
        return set(DELEGABLE_PERMISSIONS)
    from app.modules.tenant.member.model import BizTenantAdminModel, BizTenantAdminPermissionModel

    rows = (
        (
            await db.execute(
                select(BizTenantAdminPermissionModel.permission_code)
                .join(BizTenantAdminModel, BizTenantAdminModel.id == BizTenantAdminPermissionModel.admin_id)
                .where(
                    BizTenantAdminModel.tenant_id == context.tenant_id,
                    BizTenantAdminModel.member_id == context.member_id,
                    BizTenantAdminModel.is_deleted == False,  # noqa: E712
                    BizTenantAdminPermissionModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def require_project_role(db: AsyncSession, project_id: int, roles: tuple[str, ...] = PROJECT_ROLES):
    """按当前项目有效任命授权（企业 Owner/Admin 未任命同样拒绝）。返回任命记录。"""
    from app.modules.tenant.project.model import BizProjectMemberModel

    context = TenantRequestContext.get()
    if context is None or context.tenant_id is None or context.member_id is None:
        raise CustomException(msg="缺少租户成员上下文", code=RET.FORBIDDEN.code)
    appointment = (
        (
            await db.execute(
                select(BizProjectMemberModel).where(
                    BizProjectMemberModel.tenant_id == context.tenant_id,
                    BizProjectMemberModel.project_id == project_id,
                    BizProjectMemberModel.member_id == context.member_id,
                    BizProjectMemberModel.role_code.in_(roles),
                    BizProjectMemberModel.status == 0,
                    BizProjectMemberModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .first()
    )
    if not appointment:
        raise CustomException(msg="未获本项目任命，不能代行项目职责", code=RET.FORBIDDEN.code)
    return appointment


async def require_hazard_scope(db: AsyncSession, appointment, hazard_code: str) -> None:
    """专监危大范围校验：SZ 全部；SP 命中绑定集合；SA 由业务层按本人任务另行过滤。"""
    if hazard_code not in HAZARD_CODES:
        raise CustomException(msg="危大类别编码无效", code=RET.FORBIDDEN.code)
    if appointment.role_code == "SZ":
        return
    if appointment.role_code == "SA":
        raise CustomException(msg="监理员按本人任务范围操作，不适用专监危大动作", code=RET.FORBIDDEN.code)
    from app.modules.tenant.project.model import BizProjectMemberHazardModel

    granted = (
        (
            await db.execute(
                select(BizProjectMemberHazardModel.id).where(
                    BizProjectMemberHazardModel.project_member_id == appointment.id,
                    BizProjectMemberHazardModel.hazard_code == hazard_code,
                    BizProjectMemberHazardModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .first()
    )
    if not granted:
        raise CustomException(msg=f"危大类别 {hazard_code} 不在本人负责范围", code=RET.FORBIDDEN.code)
