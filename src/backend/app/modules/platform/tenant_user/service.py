"""租户用户绑定服务（平台侧管理：开通动作本身是平台域，仅超管）。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.modules.platform.enterprise.crud import EnterpriseCRUD
from app.modules.system.user.crud import UserCRUD

from .crud import TenantUserCRUD
from .model import BizTenantUserModel
from .schema import TenantUserBindSchema, TenantUserOutSchema


class TenantUserService:
    """租户用户绑定服务：绑定/解绑/按租户列绑定。

    规则：禁止绑定超管账号（超管走平台域，后续代管穿透）；一人一租户；禁止重复绑定。
    """

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _require_superadmin(self) -> None:
        if not self.auth.user.is_superuser:
            raise CustomException(msg="仅平台管理员可操作", code=RET.FORBIDDEN.code)

    async def bind(self, tenant_id: int, data: TenantUserBindSchema) -> TenantUserOutSchema:
        """绑定用户到租户（显式 tenant_id，平台域 CRUDBase）。"""
        self._require_superadmin()
        enterprise = await EnterpriseCRUD(self.auth, self.db).get_or_404(id=tenant_id, msg="企业租户不存在")
        if enterprise.status != 1:
            raise CustomException(msg="企业租户已被冻结，禁止绑定用户", code=RET.FORBIDDEN.code)

        user = await UserCRUD(self.auth, self.db).get(id=data.user_id)
        if not user:
            raise CustomException(msg="绑定用户不存在", code=RET.NOT_FOUND.code)
        if user.is_superuser:
            raise CustomException(msg="超级管理员账号禁止绑定租户（超管走平台域）", code=RET.FORBIDDEN.code)
        if await TenantUserCRUD(self.auth, self.db).get(user_id=data.user_id):
            raise CustomException(msg="该用户已绑定租户（一人一租户）", code=RET.CONFLICT.code)

        binding = await TenantUserCRUD(self.auth, self.db).create(
            data={
                "tenant_id": tenant_id,
                "user_id": data.user_id,
                "is_enterprise_admin": data.is_enterprise_admin,
                "emp_no": data.emp_no,
            }
        )
        return self._to_out(binding)

    async def unbind(self, binding_id: int) -> None:
        """解绑（物理删除绑定记录；用户账号本身不受影响）。

        user_id 唯一索引对软删行同样占位，软删会阻塞「解绑→改绑他租户」，
        故解绑即物理移除绑定事实；解绑动作由操作日志审计。
        """
        self._require_superadmin()
        binding = await TenantUserCRUD(self.auth, self.db).get_or_404(id=binding_id, msg="绑定记录不存在")
        await self.db.delete(binding)
        await self.db.flush()

    async def list_by_tenant(self, tenant_id: int) -> list[TenantUserOutSchema]:
        """按租户列绑定（平台侧显式 tenant_id 查询）。"""
        self._require_superadmin()
        await EnterpriseCRUD(self.auth, self.db).get_or_404(id=tenant_id, msg="企业租户不存在")
        bindings = await TenantUserCRUD(self.auth, self.db).get_list(search={"tenant_id": tenant_id}, preload=["user"])
        return [self._to_out(binding) for binding in bindings]

    @staticmethod
    def _to_out(binding: BizTenantUserModel) -> TenantUserOutSchema:
        out = TenantUserOutSchema.model_validate(binding)
        if binding.user:
            out.username = binding.user.username
            out.name = binding.user.name
        return out
