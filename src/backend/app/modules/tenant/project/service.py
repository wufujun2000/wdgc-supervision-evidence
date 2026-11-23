"""项目与项目任命服务（ADR-001）。

项目角色只按项目任命生效：同一成员可在不同项目担任何职；
SP 必须绑定危大类别，SZ/SA 禁止携带危大集合；卸任保留历史任命，不改写历史归属。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import RET
from app.core.base_crud import TenantCRUDBase
from app.core.base_schema import AuthSchema
from app.core.exceptions import CustomException
from app.core.tenant_permission import HAZARD_CODES, require_permission, require_project_role
from app.modules.platform.member.crud import MemberIsolatedCRUD

from .model import BizProjectMemberHazardModel, BizProjectMemberModel, BizProjectModel
from .schema import ProjectAssignSchema, ProjectCreateSchema, ProjectMemberOutSchema, ProjectOutSchema


class ProjectCRUD(TenantCRUDBase[BizProjectModel, ProjectCreateSchema, ProjectCreateSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=BizProjectModel, auth=auth, db=db)


class ProjectMemberCRUD(TenantCRUDBase[BizProjectMemberModel, ProjectAssignSchema, ProjectAssignSchema]):
    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=BizProjectMemberModel, auth=auth, db=db)


class TenantProjectService:
    """租户侧项目与任命服务（项目上下文全部由服务端校验）。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def create_project(self, data: ProjectCreateSchema) -> ProjectOutSchema:
        await require_permission(self.db, "project_manage")
        crud = ProjectCRUD(self.auth, self.db)
        project_code = data.project_code or f"PRJ-{uuid.uuid4().hex[:8].upper()}"
        if await crud.get(project_code=project_code):
            raise CustomException(msg="项目编码已存在", code=RET.DATAEXIST.code)
        project = await crud.create(
            data={"project_code": project_code, "name": data.name, "description": data.description, "status": 0}
        )
        # m-05：EXPIRE_ON_COMMIT=True 时 commit 后属性过期，先生成响应再提交
        out = ProjectOutSchema.model_validate(project)
        await self.db.commit()
        return out

    async def list_projects(self) -> list[ProjectOutSchema]:
        projects = await ProjectCRUD(self.auth, self.db).get_list()
        return [ProjectOutSchema.model_validate(project) for project in projects]

    async def _member_out(self, appointment: BizProjectMemberModel) -> ProjectMemberOutSchema:
        out = ProjectMemberOutSchema.model_validate(appointment)
        out.hazard_codes = list(
            (
                await self.db.execute(
                    select(BizProjectMemberHazardModel.hazard_code).where(
                        BizProjectMemberHazardModel.project_member_id == appointment.id,
                        BizProjectMemberHazardModel.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
        # 显式预加载账号信息：member.user 关系懒加载在异步会话中会 MissingGreenlet
        member = await MemberIsolatedCRUD(self.auth, self.db).get(id=appointment.member_id, preload=["user"])
        if member and member.user:
            out.username = member.user.username
            out.name = member.user.name
        return out

    async def assign(self, project_id: int, data: ProjectAssignSchema) -> ProjectMemberOutSchema:
        await require_permission(self.db, "project_member_assign")
        await ProjectCRUD(self.auth, self.db).get_or_404(id=project_id, msg="项目不存在")
        member = await MemberIsolatedCRUD(self.auth, self.db).get_or_404(id=data.member_id, msg="成员不存在")
        if member.status != 0:
            raise CustomException(msg="停用成员不能被任命项目角色", code=RET.FORBIDDEN.code)
        if await ProjectMemberCRUD(self.auth, self.db).get(project_id=project_id, member_id=data.member_id):
            raise CustomException(msg="该成员在本项目已有任命", code=RET.CONFLICT.code)

        hazard_codes = list(dict.fromkeys(data.hazard_codes))
        if data.role_code == "SP":
            if not hazard_codes:
                raise CustomException(msg="专监(SP)必须绑定至少一个危大类别", code=RET.FORBIDDEN.code)
            invalid = [code for code in hazard_codes if code not in HAZARD_CODES]
            if invalid:
                raise CustomException(msg=f"危大类别编码无效: {invalid}", code=RET.FORBIDDEN.code)
        elif hazard_codes:
            raise CustomException(msg="总监(SZ)/监理员(SA)不绑定危大类别集合", code=RET.FORBIDDEN.code)

        appointment = await ProjectMemberCRUD(self.auth, self.db).create(
            data={"project_id": project_id, "member_id": data.member_id, "role_code": data.role_code, "status": 0}
        )
        for code in hazard_codes:
            self.db.add(BizProjectMemberHazardModel(tenant_id=appointment.tenant_id, project_member_id=appointment.id, hazard_code=code))
        await self.db.flush()
        out = await self._member_out(appointment)
        await self.db.commit()
        return out

    async def list_project_members(self, project_id: int) -> list[ProjectMemberOutSchema]:
        # 项目任命门控：仅当前项目任职成员可读；Owner/Admin 未任命同样 403
        await require_project_role(self.db, project_id)
        appointments = await ProjectMemberCRUD(self.auth, self.db).get_list(search={"project_id": project_id})
        return [await self._member_out(appointment) for appointment in appointments]

    async def disable_project_member(self, project_id: int, appointment_id: int) -> None:
        await require_permission(self.db, "project_member_assign")
        appointment = await ProjectMemberCRUD(self.auth, self.db).get_or_404(id=appointment_id, msg="任命不存在")
        if appointment.project_id != project_id:
            raise CustomException(msg="任命不属于当前项目", code=RET.NOT_FOUND.code)
        await ProjectMemberCRUD(self.auth, self.db).update(id=appointment.id, data={"status": 1})
        await self.db.commit()
