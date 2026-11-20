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
from app.modules.platform.tenant_user.schema import TenantUserBindSchema, TenantUserOutSchema

from .schema import EnterpriseCreateSchema, EnterpriseOutSchema, EnterpriseQueryParam, EnterpriseUpdateSchema
from .service import EnterpriseService

EnterpriseRouter = APIRouter(route_class=OperationLogRoute, prefix="/enterprise", tags=["平台-租户开通"])


@EnterpriseRouter.post("/create", status_code=status.HTTP_201_CREATED, summary="开通租户", response_model=ResponseSchema[EnterpriseOutSchema])
async def create_enterprise_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: EnterpriseCreateSchema,
) -> JSONResponse:
    result = await EnterpriseService(auth, db).create(data=data)
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


@EnterpriseRouter.get("/{id}/bindings", summary="按租户列绑定", response_model=ResponseSchema[list[TenantUserOutSchema]])
async def list_enterprise_bindings_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="企业租户ID", ge=1)],
) -> JSONResponse:
    result = await EnterpriseService(auth, db).list_bindings(id=id)
    return SuccessResponse(data=result, msg="查询租户绑定成功")


@EnterpriseRouter.post("/{id}/bindings", status_code=status.HTTP_201_CREATED, summary="绑定用户到租户", response_model=ResponseSchema[TenantUserOutSchema])
async def bind_enterprise_user_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="企业租户ID", ge=1)],
    data: TenantUserBindSchema,
) -> JSONResponse:
    result = await EnterpriseService(auth, db).bind_user(id=id, data=data)
    return SuccessResponse(data=result, msg="绑定用户成功")


@EnterpriseRouter.delete("/bindings/{binding_id}", summary="解绑用户", response_model=ResponseSchema[None])
async def unbind_enterprise_user_controller(
    auth: Annotated[AuthSchema, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(db_getter)],
    binding_id: Annotated[int, Path(description="绑定记录ID", ge=1)],
) -> JSONResponse:
    await EnterpriseService(auth, db).unbind_user(binding_id=binding_id)
    return SuccessResponse(msg="解绑用户成功")
