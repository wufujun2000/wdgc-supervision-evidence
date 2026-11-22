"""企业租户开通 Schema。"""

import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.base_schema import BaseQueryParam, BaseSchema
from app.core.validator import mobile_validator, password_validator


class AdminAccountSchema(BaseModel):
    """一步开通：同事务新建企业管理员账号（初始密码留空则自动生成，仅响应返回一次）。"""

    username: str = Field(..., min_length=3, max_length=32, description="管理员登录账号")
    name: str = Field(..., min_length=1, max_length=32, description="管理员姓名/昵称")
    mobile: str | None = Field(None, description="手机号")
    password: str | None = Field(None, description="初始密码（留空自动生成；线下告知企业）")

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str):
        """与基线用户创建同口径：字母开头，3-32 位"""
        v = value.strip()
        if not re.match(r"^[A-Za-z][A-Za-z0-9_.-]{2,31}$", v):
            raise ValueError("账号需以字母开头，3-32 位，仅允许字母、数字、_ . -")
        return v

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str | None):
        return mobile_validator(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None):
        return password_validator(value)


class EnterpriseCreateSchema(BaseModel):
    """开通租户：创建企业，可同请求绑定已有账号或一步新建企业管理员账号。"""

    name: str = Field(..., min_length=1, max_length=128, description="企业名称")
    enterprise_code: str | None = Field(None, max_length=32, pattern=r"^ENT-[A-Za-z0-9_-]+$", description="企业编码(ENT-xxx)，缺省自动生成")
    credit_code: str | None = Field(None, max_length=64, description="统一社会信用代码")
    description: str | None = Field(None, description="备注")
    admin_user_id: int | None = Field(None, ge=1, description="同请求绑定的企业管理员账号ID（禁止超管）")
    admin_account: AdminAccountSchema | None = Field(None, description="一步新建企业管理员账号（与 admin_user_id 互斥）")

    @model_validator(mode="after")
    def validate_admin_exclusive(self):
        """ADR-001：开通必须原子创建首名成员＋唯一 Owner，两个字段互斥且必填其一。"""
        if self.admin_user_id is not None and self.admin_account is not None:
            raise ValueError("admin_user_id 与 admin_account 互斥，只能二选一")
        if self.admin_user_id is None and self.admin_account is None:
            raise ValueError("开通租户必须指定首名企业拥有者：admin_user_id 与 admin_account 二选一")
        return self


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


class EnterpriseProvisionOutSchema(EnterpriseOutSchema):
    """开通租户响应：企业信息＋管理员绑定结果。

    admin_initial_password 仅在「一步新建账号且未显式指定密码」时返回一次（线下告知企业），
    调用方自带密码时恒为 None（不回显）；该键已加入操作日志脱敏表。
    """

    admin_user_id: int | None = Field(default=None, description="企业管理员账号ID")
    admin_username: str | None = Field(default=None, description="企业管理员登录账号")
    admin_initial_password: str | None = Field(default=None, description="自动生成的初始密码（仅本次返回一次）")


class EnterpriseQueryParam(BaseQueryParam):
    """企业租户查询参数。"""

    name: str | None = Field(None, description="企业名称", json_schema_extra={"q": "like"})
    enterprise_code: str | None = Field(None, description="企业编码", json_schema_extra={"q": "like"})
    credit_code: str | None = Field(None, description="统一社会信用代码", json_schema_extra={"q": "eq"})
    status: int | None = Field(None, description="状态(1:正常 0:冻结)", json_schema_extra={"q": "eq"})
