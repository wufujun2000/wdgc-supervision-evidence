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
from app.modules.platform.member.crud import MemberCRUD
from app.modules.platform.member.service import execute_owner_transfer
from app.modules.system.user.crud import UserCRUD
from app.utils.common_util import search_to_dict

from .crud import EnterpriseCRUD
from .schema import EnterpriseCreateSchema, EnterpriseOutSchema, EnterpriseProvisionOutSchema, EnterpriseQueryParam, EnterpriseUpdateSchema


class EnterpriseService:
    """企业租户开通服务：创建（可带管理员绑定）/分页/详情/更新/冻结/解冻/绑定管理。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _require_superadmin(self) -> None:
        if not self.auth.user.is_superuser:
            raise CustomException(msg="仅平台管理员可操作", code=RET.FORBIDDEN.code)

    async def create(self, data: EnterpriseCreateSchema, redis: Redis) -> EnterpriseProvisionOutSchema:
        """开通租户（ADR-001）：同事务完成企业＋首名成员＋唯一 Owner＋审计，失败整体回滚。"""
        self._require_superadmin()
        crud = EnterpriseCRUD(self.auth, self.db)

        admin_user = None
        if data.admin_user_id is not None:
            admin_user = await UserCRUD(self.auth, self.db).get(id=data.admin_user_id)
            if not admin_user:
                raise CustomException(msg="绑定用户不存在", code=RET.NOT_FOUND.code)
            if admin_user.is_superuser:
                raise CustomException(msg="超级管理员账号禁止加入租户成员（超管走平台域）", code=RET.FORBIDDEN.code)
            if admin_user.status != 0:
                raise CustomException(msg="绑定账号已停用，不能成为企业拥有者", code=RET.FORBIDDEN.code)

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

        admin_user_id = data.admin_user_id
        admin_username: str | None = None
        admin_initial_password: str | None = None
        if data.admin_account:
            # 一步开通：先建账号再建成员；username 重复等任何失败都在请求事务内整体回滚
            from app.modules.platform.member.service import create_login_account

            new_user, admin_initial_password = await create_login_account(self.auth, self.db, data.admin_account)
            admin_user_id = new_user.id
            admin_username = new_user.username
        # ADR-001：首名成员＋唯一 Owner＋开通审计（任一步失败整体回滚，不留无 Owner 可用租户）
        member = await MemberCRUD(self.auth, self.db).create(
            data={"tenant_id": enterprise.id, "user_id": admin_user_id, "emp_no": None, "status": 0}
        )
        await execute_owner_transfer(
            self.db,
            redis,
            tenant_id=enterprise.id,
            target_member_id=member.id,
            operator_user_id=self.auth.user.id,
            source="platform",
            reason="开通租户初始化企业拥有者",
        )
        if not admin_username:
            admin_user = await UserCRUD(self.auth, self.db).get(id=admin_user_id)
            admin_username = admin_user.username if admin_user else None
        enterprise_out = await self.detail(enterprise.id)
        # 写后读竞态：db_getter 在响应后才提交，开通后续调用（登录/授权）须读到已提交状态；
        # session.begin() 上下文内 commit 后不得再查询，故提交放在所有读取之后。
        await self.db.commit()
        return EnterpriseProvisionOutSchema(
            **enterprise_out.model_dump(),
            admin_user_id=admin_user_id,
            admin_username=admin_username,
            admin_initial_password=admin_initial_password,
        )

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
        result = await self.detail(id)
        await self.db.commit()
        return result

    async def unfreeze(self, id: int) -> EnterpriseOutSchema:
        """解冻企业租户（status=1）；用户需重新登录（冻结时会话已清退）。"""
        self._require_superadmin()
        crud = EnterpriseCRUD(self.auth, self.db)
        await crud.get_or_404(id=id, msg="企业租户不存在")
        await crud.update(id=id, data={"status": 1})
        result = await self.detail(id)
        await self.db.commit()
        return result

    async def _purge_tenant_sessions(self, redis: Redis, tenant_id: int) -> int:
        """清退租户全部绑定用户的会话（参考 online 模块会话键做法，三键全删）。"""
        bindings = await MemberCRUD(self.auth, self.db).get_list(search={"tenant_id": tenant_id})
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
