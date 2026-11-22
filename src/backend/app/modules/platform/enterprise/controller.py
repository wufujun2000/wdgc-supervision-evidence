"""企业租户开通控制器（/api/v1/platform/enterprise，仅超管）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import JSONResponse
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import db_getter, get_current_user, redis_getter
from app.core.router_class import OperationLogRoute
from app.modules.platform.member.schema import MemberBindSchema, MemberOutSchema, OwnerAuditOutSchema, OwnerTransferOutSchema, OwnerTransferSchema
from app.modules.platform.member.service import MemberService

from .schema import EnterpriseCreateSchema, EnterpriseOutSchema, EnterpriseProvisionOutSchema, EnterpriseQueryParam, EnterpriseUpdateSchema
from .service import EnterpriseService

EnterpriseRouter = APIRouter(route_class=OperationLogRoute, prefix="/enterprise", tags=["平台-租户开通"])


@EnterpriseRouter.post("/create", status_code=status.HTTP_201_CREATED, summary="开通租户", response_model=ResponseSchema[EnterpriseProvisionOutSchema])
async def create_enterprise_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: EnterpriseCreateSchema,
) -> JSONResponse:
    result = await EnterpriseService(auth, db).create(data=data, redis=redis)
    return SuccessResponse(data=result, msg="开通租户成功")


@EnterpriseRouter.get("/list", summary="查询企业租户", response_model=ResponseSchema[PageResultSchema[EnterpriseOutSchema]])
async def get_enterprise_list_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[EnterpriseQueryParam, Query()],
) -> JSONResponse:
    result = await EnterpriseService(auth, db).page(
        page_no=page.page_no,
        page_size=page.page_size,
        search=search,
        order_by=page.order_by,
    )
    return SuccessResponse(data=result, msg="查询企业租户成功")


@EnterpriseRouter.get("/detail/{id}", summary="查询企业租户详情", response_model=ResponseSchema[EnterpriseOutSchema])
async def get_enterprise_detail_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="企业租户ID", ge=1)],
) -> JSONResponse:
    result = await EnterpriseService(auth, db).detail(id=id)
    return SuccessResponse(data=result, msg="获取企业租户详情成功")


@EnterpriseRouter.put("/update/{id}", summary="更新企业租户", response_model=ResponseSchema[EnterpriseOutSchema])
async def update_enterprise_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="企业租户ID", ge=1)],
    data: EnterpriseUpdateSchema,
) -> JSONResponse:
    result = await EnterpriseService(auth, db).update(id=id, data=data)
    return SuccessResponse(data=result, msg="更新企业租户成功")


@EnterpriseRouter.post("/freeze/{id}", summary="冻结企业租户", response_model=ResponseSchema[EnterpriseOutSchema])
async def freeze_enterprise_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    id: Annotated[int, Path(description="企业租户ID", ge=1)],
) -> JSONResponse:
    result = await EnterpriseService(auth, db).freeze(id=id, redis=redis)
    return SuccessResponse(data=result, msg="冻结企业租户成功")


@EnterpriseRouter.post("/unfreeze/{id}", summary="解冻企业租户", response_model=ResponseSchema[EnterpriseOutSchema])
async def unfreeze_enterprise_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="企业租户ID", ge=1)],
) -> JSONResponse:
    result = await EnterpriseService(auth, db).unfreeze(id=id)
    return SuccessResponse(data=result, msg="解冻企业租户成功")


@EnterpriseRouter.get("/{id}/members", summary="查询租户成员", response_model=ResponseSchema[list[MemberOutSchema]])
async def list_enterprise_members_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="企业租户ID")],
) -> JSONResponse:
    result = await MemberService(auth, db).list_by_tenant(id)
    return SuccessResponse(data=result, msg="查询租户成员成功")


@EnterpriseRouter.post("/{id}/members", status_code=status.HTTP_201_CREATED, summary="补绑租户成员", response_model=ResponseSchema[MemberOutSchema])
async def bind_enterprise_member_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    id: Annotated[int, Path(description="企业租户ID")],
    data: MemberBindSchema,
) -> JSONResponse:
    result = await MemberService(auth, db).bind(tenant_id=id, data=data, redis=redis)
    return SuccessResponse(data=result, msg="绑定成员成功")


@EnterpriseRouter.post("/members/{member_id}/disable", summary="停用租户成员", response_model=ResponseSchema[None])
async def disable_enterprise_member_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    member_id: Annotated[int, Path(description="租户成员ID")],
) -> JSONResponse:
    await MemberService(auth, db).disable(member_id=member_id, redis=redis)
    return SuccessResponse(msg="停用成员成功")


@EnterpriseRouter.post("/{id}/owner/transfer", summary="移交企业拥有者", response_model=ResponseSchema[OwnerTransferOutSchema])
async def transfer_enterprise_owner_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    id: Annotated[int, Path(description="企业租户ID")],
    data: OwnerTransferSchema,
) -> JSONResponse:
    result = await MemberService(auth, db).transfer(tenant_id=id, target_member_id=data.target_member_id, reason=data.reason, redis=redis)
    return SuccessResponse(data=result, msg="所有权移交成功")


@EnterpriseRouter.get("/{id}/owner-audit", summary="查询所有权审计", response_model=ResponseSchema[list[OwnerAuditOutSchema]])
async def list_enterprise_owner_audit_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="企业租户ID")],
) -> JSONResponse:
    result = await MemberService(auth, db).list_audit(tenant_id=id)
    return SuccessResponse(data=[OwnerAuditOutSchema.model_validate(row) for row in result], msg="查询所有权审计成功")
