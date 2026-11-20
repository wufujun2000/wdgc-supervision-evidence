"""企业租户开通服务（平台域，仅超管）。

冻结必须清退该租户全部绑定用户的 Redis 会话（USER_SESSION/ACCESS/REFRESH 全套键），
配合 H-02 认证实时校验，做到「冻结即失效」。
"""

import json
import uuid

from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET, RedisInitKeyConfig
from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.core.redis_crud import RedisCURD
from app.modules.platform.tenant_user.crud import TenantUserCRUD
from app.modules.platform.tenant_user.schema import TenantUserBindSchema, TenantUserOutSchema
from app.modules.platform.tenant_user.service import TenantUserService
from app.utils.common_util import search_to_dict

from .crud import EnterpriseCRUD
from .schema import EnterpriseCreateSchema, EnterpriseOutSchema, EnterpriseQueryParam, EnterpriseUpdateSchema


class EnterpriseService:
    """企业租户开通服务：创建（可带管理员绑定）/分页/详情/更新/冻结/解冻/绑定管理。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _require_superadmin(self) -> None:
        if not self.auth.user.is_superuser:
            raise CustomException(msg="仅平台管理员可操作", code=RET.FORBIDDEN.code)

    async def create(self, data: EnterpriseCreateSchema) -> EnterpriseOutSchema:
        """开通租户：创建企业，可同请求绑定企业管理员（同一事务，绑定失败整体回滚）。"""
        self._require_superadmin()
        crud = EnterpriseCRUD(self.auth, self.db)

        enterprise_code = data.enterprise_code or f"ENT-{uuid.uuid4().hex[:8].upper()}"
        if await crud.get(enterprise_code=enterprise_code):
            raise CustomException(msg="企业编码已存在", code=RET.DATAEXIST.code)
        if data.credit_code and await crud.get(credit_code=data.credit_code):
            raise CustomException(msg="统一社会信用代码已存在", code=RET.DATAEXIST.code)

        enterprise = await crud.create(
            data={
                "enterprise_code": enterprise_code,
                "name": data.name,
                "credit_code": data.credit_code,
                "description": data.description,
                "status": 1,
            }
        )
        if data.admin_user_id:
            await TenantUserService(self.auth, self.db).bind(
                enterprise.id, TenantUserBindSchema(user_id=data.admin_user_id, is_enterprise_admin=True)
            )
        return await self.detail(enterprise.id)

    async def detail(self, id: int) -> EnterpriseOutSchema:
        self._require_superadmin()
        enterprise = await EnterpriseCRUD(self.auth, self.db).get_or_404(id=id, msg="企业租户不存在")
        return EnterpriseOutSchema.model_validate(enterprise)

    async def page(
        self,
        page_no: int,
        page_size: int,
        search: EnterpriseQueryParam | None = None,
        order_by: list[dict[str, str]] | None = None,
    ) -> PageResultSchema[EnterpriseOutSchema]:
        self._require_superadmin()
        offset = (page_no - 1) * page_size
        return await EnterpriseCRUD(self.auth, self.db).page(
            offset=offset,
            limit=page_size,
            order_by=order_by or [{"id": "asc"}],
            search=search_to_dict(search),
            out_schema=EnterpriseOutSchema,
        )

    async def update(self, id: int, data: EnterpriseUpdateSchema) -> EnterpriseOutSchema:
        """更新企业基本信息；状态变更只走 freeze/unfreeze（Schema 不接受 status）。"""
        self._require_superadmin()
        crud = EnterpriseCRUD(self.auth, self.db)
        await crud.get_or_404(id=id, msg="企业租户不存在")
        if data.credit_code:
            exist = await crud.get(credit_code=data.credit_code)
            if exist and exist.id != id:
                raise CustomException(msg="统一社会信用代码已存在", code=RET.DATAEXIST.code)
        await crud.update(id=id, data=data.model_dump(exclude_unset=True, exclude_none=True))
        return await self.detail(id)

    async def freeze(self, id: int, redis: Redis) -> EnterpriseOutSchema:
        """冻结企业租户（status=0）并清退全部绑定用户会话。幂等：重复冻结仍执行清退。"""
        self._require_superadmin()
        crud = EnterpriseCRUD(self.auth, self.db)
        await crud.get_or_404(id=id, msg="企业租户不存在")
        await crud.update(id=id, data={"status": 0})
        purged = await self._purge_tenant_sessions(redis, id)
        logger.info(f"企业租户已冻结: id={id}, 清退会话数={purged}")
        return await self.detail(id)

    async def unfreeze(self, id: int) -> EnterpriseOutSchema:
        """解冻企业租户（status=1）；用户需重新登录（冻结时会话已清退）。"""
        self._require_superadmin()
        crud = EnterpriseCRUD(self.auth, self.db)
        await crud.get_or_404(id=id, msg="企业租户不存在")
        await crud.update(id=id, data={"status": 1})
        return await self.detail(id)

    async def list_bindings(self, id: int) -> list[TenantUserOutSchema]:
        return await TenantUserService(self.auth, self.db).list_by_tenant(id)

    async def bind_user(self, id: int, data: TenantUserBindSchema) -> TenantUserOutSchema:
        return await TenantUserService(self.auth, self.db).bind(id, data)

    async def unbind_user(self, binding_id: int) -> None:
        await TenantUserService(self.auth, self.db).unbind(binding_id)

    async def _purge_tenant_sessions(self, redis: Redis, tenant_id: int) -> int:
        """清退租户全部绑定用户的会话（参考 online 模块会话键做法，三键全删）。"""
        bindings = await TenantUserCRUD(self.auth, self.db).get_list(search={"tenant_id": tenant_id})
        user_ids = {binding.user_id for binding in bindings}
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
