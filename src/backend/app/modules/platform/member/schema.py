"""租户成员与所有权 Schema（ADR-001）。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.base_schema import BaseSchema


class MemberBindSchema(BaseModel):
    """平台侧补绑成员（无 Owner 租户首名成员自动补 Owner）。"""

    user_id: int = Field(..., ge=1, description="登录账号ID（禁止超管）")
    emp_no: str | None = Field(None, max_length=32, description="企业内工号")


class MemberOutSchema(BaseSchema):
    """租户成员响应（含 Owner/Admin 派生标识）。"""

    tenant_id: int = Field(description="所属租户ID")
    user_id: int = Field(description="登录账号ID")
    emp_no: str | None = Field(default=None, description="工号")
    status: int = Field(description="成员状态(0:正常 1:停用)")
    username: str | None = Field(default=None, description="登录账号")
    name: str | None = Field(default=None, description="姓名")
    is_owner: bool = Field(default=False, description="是否当前企业拥有者")
    is_admin: bool = Field(default=False, description="是否企业管理员")


class OwnerTransferSchema(BaseModel):
    """所有权移交请求（必须二次确认＋原因）。"""

    target_member_id: int = Field(..., ge=1, description="新 Owner 目标成员ID（本租户有效成员）")
    reason: str = Field(..., min_length=1, max_length=500, description="移交原因")
    confirm: Literal[True] = Field(..., description="二次确认（必须为 true）")


class OwnerTransferOutSchema(BaseModel):
    """所有权移交结果。"""

    tenant_id: int = Field(description="租户ID")
    from_member_id: int | None = Field(default=None, description="原 Owner 成员ID")
    to_member_id: int = Field(description="新 Owner 成员ID")
    version: int = Field(description="移交后所有权版本")


class OwnerAuditOutSchema(BaseSchema):
    """所有权审计响应。"""

    source: str = Field(description="发起来源(platform/tenant)")
    operator_user_id: int | None = Field(default=None, description="操作人账号ID")
    tenant_id: int = Field(description="租户ID")
    from_member_id: int | None = Field(default=None, description="原 Owner 成员ID")
    to_member_id: int = Field(description="新 Owner 成员ID")
    reason: str = Field(description="原因")
    result: str = Field(description="结果(success/failed)")
