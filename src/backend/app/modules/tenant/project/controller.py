"""租户侧项目与项目任命控制器（/api/v1/tenant，ADR-001）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import db_getter, get_current_user
from app.core.router_class import OperationLogRoute

from .schema import ProjectAssignSchema, ProjectCreateSchema, ProjectMemberOutSchema, ProjectOutSchema
from .service import TenantProjectService

TenantProjectRouter = APIRouter(route_class=OperationLogRoute, tags=["租户-项目与任命"])


@TenantProjectRouter.post("/projects", status_code=status.HTTP_201_CREATED, summary="创建项目", response_model=ResponseSchema[ProjectOutSchema])
async def create_project_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: ProjectCreateSchema,
) -> JSONResponse:
    result = await TenantProjectService(auth, db).create_project(data)
    return SuccessResponse(data=result, msg="创建项目成功")


@TenantProjectRouter.get("/projects/list", summary="项目列表", response_model=ResponseSchema[list[ProjectOutSchema]])
async def list_projects_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await TenantProjectService(auth, db).list_projects()
    return SuccessResponse(data=result, msg="查询项目列表成功")


@TenantProjectRouter.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED, summary="任命项目成员", response_model=ResponseSchema[ProjectMemberOutSchema])
async def assign_project_member_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    project_id: Annotated[int, Path(description="项目ID")],
    data: ProjectAssignSchema,
) -> JSONResponse:
    result = await TenantProjectService(auth, db).assign(project_id, data)
    return SuccessResponse(data=result, msg="任命项目成员成功")


@TenantProjectRouter.get("/projects/{project_id}/members", summary="项目成员列表", response_model=ResponseSchema[list[ProjectMemberOutSchema]])
async def list_project_members_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    project_id: Annotated[int, Path(description="项目ID")],
) -> JSONResponse:
    result = await TenantProjectService(auth, db).list_project_members(project_id)
    return SuccessResponse(data=result, msg="查询项目成员成功")


@TenantProjectRouter.post("/projects/{project_id}/members/{appointment_id}/disable", summary="卸任项目成员", response_model=ResponseSchema[None])
async def disable_project_member_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    project_id: Annotated[int, Path(description="项目ID")],
    appointment_id: Annotated[int, Path(description="任命ID")],
) -> JSONResponse:
    await TenantProjectService(auth, db).disable_project_member(project_id, appointment_id)
    return SuccessResponse(msg="卸任项目成员成功")
