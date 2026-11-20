"""企业租户数据层（平台域 CRUDBase，无租户上下文要求）。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_crud import CRUDBase
from app.core.base_schema import AuthSchema

from .model import EnterpriseModel
from .schema import EnterpriseCreateSchema, EnterpriseUpdateSchema


class EnterpriseCRUD(CRUDBase[EnterpriseModel, EnterpriseCreateSchema, EnterpriseUpdateSchema]):
    """企业租户模块数据层"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=EnterpriseModel, auth=auth, db=db)
