"""租户成员/所有权/审计数据层（平台侧 CRUDBase＋显式条件，租户侧走 MemberIsolatedCRUD）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase, TenantCRUDBase
from app.core.base_schema import AuthSchema
from app.modules.tenant.member.model import BizTenantMemberModel

from .model import PlatOwnerTransferAuditModel
from .schema import MemberBindSchema


class MemberCRUD(CRUDBase[BizTenantMemberModel, MemberBindSchema, MemberBindSchema]):
    """平台侧成员数据层（查询须显式携带 tenant_id/user_id 条件）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=BizTenantMemberModel, auth=auth, db=db)


class MemberIsolatedCRUD(TenantCRUDBase[BizTenantMemberModel, MemberBindSchema, MemberBindSchema]):
    """租户上下文内成员读写（TenantCRUDBase 铁律）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=BizTenantMemberModel, auth=auth, db=db)


class AuditCRUD(CRUDBase[PlatOwnerTransferAuditModel, dict, dict]):
    """所有权审计只读数据层（append-only，无更新/删除 API）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=PlatOwnerTransferAuditModel, auth=auth, db=db)


async def get_first_active_member(db: AsyncSession, user_id: int) -> BizTenantMemberModel | None:
    """登录/认证解析：账号最早的有效成员（status=0），优先未冻结租户（C1）。

    全部所属租户冻结时回退最早成员，冻结拦截由认证层统一执行。
    """
    from app.modules.platform.enterprise.model import EnterpriseModel  # 延迟导入：登录链路不新增导入期依赖

    members = (
        (
            await db.execute(
                select(BizTenantMemberModel)
                .where(
                    BizTenantMemberModel.user_id == user_id,
                    BizTenantMemberModel.status == 0,
                    BizTenantMemberModel.is_deleted == False,  # noqa: E712
                )
                .order_by(BizTenantMemberModel.id)
            )
        )
        .scalars()
        .all()
    )
    if not members:
        return None
    active_tenant_ids = set(
        (
            await db.execute(
                select(EnterpriseModel.id).where(
                    EnterpriseModel.id.in_({m.tenant_id for m in members}),
                    EnterpriseModel.status == 1,
                    EnterpriseModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .all()
    )
    return next((m for m in members if m.tenant_id in active_tenant_ids), members[0])
