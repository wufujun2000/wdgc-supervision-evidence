"""租户侧成员与管理员 Schema（ADR-001）。"""

from pydantic import BaseModel, Field, model_validator

from app.modules.platform.enterprise.schema import AdminAccountSchema


class MemberCreateSchema(BaseModel):
    """租户新增成员：绑定已有账号或新建登录账号（tenant_member_manage）。"""

    user_id: int | None = Field(None, ge=1, description="绑定已有账号ID（禁止超管）")
    account: AdminAccountSchema | None = Field(None, description="新建登录账号（与 user_id 互斥）")
    emp_no: str | None = Field(None, max_length=32, description="企业内工号")

    @model_validator(mode="after")
    def validate_account_exclusive(self):
        if self.user_id is not None and self.account is not None:
            raise ValueError("user_id 与 account 互斥，只能二选一")
        if self.user_id is None and self.account is None:
            raise ValueError("必须指定账号：user_id 与 account 二选一")
        return self


class AdminGrantSchema(BaseModel):
    """设置企业管理员并授予可委托权限（tenant_admin_manage；Owner 不得作为目标）。"""

    member_id: int = Field(..., ge=1, description="目标租户成员ID")
    permissions: list[str] = Field(default_factory=list, description="可委托权限集合（可为空=零权限管理员）")


class AdminPermissionUpdateSchema(BaseModel):
    """调整企业管理员权限（不超过操作者自身可转授范围）。"""

    permissions: list[str] = Field(..., min_length=0, description="可委托权限集合")
