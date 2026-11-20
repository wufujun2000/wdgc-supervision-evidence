"""企业租户开通 Schema。"""

from pydantic import BaseModel, Field

from app.core.base_schema import BaseQueryParam, BaseSchema


class EnterpriseCreateSchema(BaseModel):
    """开通租户：创建企业，可同请求绑定企业管理员账号。"""

    name: str = Field(..., min_length=1, max_length=128, description="企业名称")
    enterprise_code: str | None = Field(None, max_length=32, pattern=r"^ENT-[A-Za-z0-9_-]+$", description="企业编码(ENT-xxx)，缺省自动生成")
    credit_code: str | None = Field(None, max_length=64, description="统一社会信用代码")
    description: str | None = Field(None, description="备注")
    admin_user_id: int | None = Field(None, ge=1, description="同请求绑定的企业管理员账号ID（禁止超管）")


class EnterpriseUpdateSchema(BaseModel):
    """更新企业基本信息。状态变更只走 freeze/unfreeze（冻结须清退会话），不接受直改 status。"""

    name: str | None = Field(None, min_length=1, max_length=128, description="企业名称")
    credit_code: str | None = Field(None, max_length=64, description="统一社会信用代码")
    description: str | None = Field(None, description="备注")


class EnterpriseOutSchema(BaseSchema):
    """企业租户响应。"""

    enterprise_code: str = Field(description="企业编码(ENT-xxx)")
    name: str = Field(description="企业名称")
    credit_code: str | None = Field(default=None, description="统一社会信用代码")
    status: int = Field(description="状态(1:正常 0:冻结)")
    description: str | None = Field(default=None, description="备注")


class EnterpriseQueryParam(BaseQueryParam):
    """企业租户查询参数。"""

    name: str | None = Field(None, description="企业名称", json_schema_extra={"q": "like"})
    enterprise_code: str | None = Field(None, description="企业编码", json_schema_extra={"q": "like"})
    credit_code: str | None = Field(None, description="统一社会信用代码", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, description="状态(1:正常 0:冻结)", json_schema_extra={"q": "eq"})
