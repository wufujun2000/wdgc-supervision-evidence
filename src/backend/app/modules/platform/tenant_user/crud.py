"""租户用户绑定数据层。

双 CRUD 分工（契约 B.3）：
- TenantUserCRUD：平台侧管理（开通动作本身是平台域），CRUDBase＋显式 tenant_id；
- TenantUserIsolatedCRUD：租户上下文内的读写，走 TenantCRUDBase 铁律。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase, TenantCRUDBase
from app.core.base_schema import AuthSchema

from .model import BizTenantUserModel
from .schema import TenantUserBindSchema


class TenantUserCRUD(CRUDBase[BizTenantUserModel, TenantUserBindSchema, TenantUserBindSchema]):
    """平台侧绑定管理数据层（查询须显式携带 tenant_id）"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=BizTenantUserModel, auth=auth, db=db)


class TenantUserIsolatedCRUD(TenantCRUDBase[BizTenantUserModel, TenantUserBindSchema, TenantUserBindSchema]):
    """租户上下文内绑定读写数据层（自动注入/校验 tenant_id）"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=BizTenantUserModel, auth=auth, db=db)
