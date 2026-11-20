"""租户用户绑定 Schema。"""

from pydantic import BaseModel, Field

from app.core.base_schema import BaseSchema


class TenantUserBindSchema(BaseModel):
    """绑定用户到租户（一人一租户，禁止超管）。"""

    user_id: int = Field(..., ge=1, description="用户ID")
    is_enterprise_admin: bool = Field(default=False, description="是否企业管理员")
    emp_no: str | None = Field(None, max_length=32, description="工号")


class TenantUserOutSchema(BaseSchema):
    """租户用户绑定响应。"""

    tenant_id: int = Field(description="所属租户ID")
    user_id: int = Field(description="用户ID")
    is_enterprise_admin: bool = Field(description="是否企业管理员")
    emp_no: str | None = Field(default=None, description="工号")
    username: str | None = Field(default=None, description="用户登录账号")
    name: str | None = Field(default=None, description="用户昵称")
