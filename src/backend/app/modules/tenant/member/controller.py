"""租户侧成员、管理员与所有权控制器（/api/v1/tenant，ADR-001）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from fastapi.responses import JSONResponse
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import db_getter, get_current_user, redis_getter
from app.core.router_class import OperationLogRoute
from app.modules.platform.member.schema import MemberOutSchema, OwnerAuditOutSchema, OwnerTransferOutSchema, OwnerTransferSchema

from .schema import AdminGrantSchema, AdminPermissionUpdateSchema, MemberCreateSchema
from .service import TenantMemberService

TenantMemberRouter = APIRouter(route_class=OperationLogRoute, tags=["租户-成员与所有权"])


@TenantMemberRouter.post("/members", status_code=status.HTTP_201_CREATED, summary="新增租户成员", response_model=ResponseSchema[MemberOutSchema])
async def create_member_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: MemberCreateSchema,
) -> JSONResponse:
    result = await TenantMemberService(auth, db).create_member(data)
    return SuccessResponse(data=result, msg="新增租户成员成功")


@TenantMemberRouter.get("/members/list", summary="租户成员列表", response_model=ResponseSchema[list[MemberOutSchema]])
async def list_members_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await TenantMemberService(auth, db).list_members()
    return SuccessResponse(data=result, msg="查询租户成员成功")


@TenantMemberRouter.post("/members/{member_id}/disable", summary="停用租户成员", response_model=ResponseSchema[None])
async def disable_member_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    member_id: Annotated[int, Path(description="租户成员ID")],
) -> JSONResponse:
    await TenantMemberService(auth, db).disable_member(member_id, redis)
    return SuccessResponse(msg="停用租户成员成功")


@TenantMemberRouter.post("/admins", summary="设置企业管理员", response_model=ResponseSchema[MemberOutSchema])
async def set_admin_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: AdminGrantSchema,
) -> JSONResponse:
    result = await TenantMemberService(auth, db).set_admin(data)
    return SuccessResponse(data=result, msg="设置企业管理员成功")


@TenantMemberRouter.put("/admins/{member_id}/permissions", summary="调整管理员权限", response_model=ResponseSchema[MemberOutSchema])
async def update_admin_permissions_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    member_id: Annotated[int, Path(description="租户成员ID")],
    data: AdminPermissionUpdateSchema,
) -> JSONResponse:
    result = await TenantMemberService(auth, db).update_admin_permissions(member_id, data)
    return SuccessResponse(data=result, msg="调整管理员权限成功")


@TenantMemberRouter.delete("/admins/{member_id}", summary="撤销企业管理员", response_model=ResponseSchema[MemberOutSchema])
async def revoke_admin_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    member_id: Annotated[int, Path(description="租户成员ID")],
) -> JSONResponse:
    result = await TenantMemberService(auth, db).revoke_admin(member_id)
    return SuccessResponse(data=result, msg="撤销企业管理员成功")


@TenantMemberRouter.post("/owner/transfer", summary="移交企业拥有者", response_model=ResponseSchema[OwnerTransferOutSchema])
async def transfer_owner_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: OwnerTransferSchema,
) -> JSONResponse:
    result = await TenantMemberService(auth, db).transfer_owner(data.target_member_id, data.reason, redis)
    return SuccessResponse(data=result, msg="所有权移交成功")


@TenantMemberRouter.get("/owner-audit", summary="所有权审计", response_model=ResponseSchema[list[OwnerAuditOutSchema]])
async def list_owner_audit_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await TenantMemberService(auth, db).list_owner_audit()
    return SuccessResponse(data=[OwnerAuditOutSchema.model_validate(row) for row in result], msg="查询所有权审计成功")
