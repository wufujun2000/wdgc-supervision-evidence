"""项目与项目任命 Schema（ADR-001）。"""

from pydantic import BaseModel, Field

from app.core.base_schema import BaseSchema


class ProjectCreateSchema(BaseModel):
    """创建项目（project_manage）。"""

    project_code: str | None = Field(None, max_length=32, pattern=r"^PRJ-[A-Za-z0-9_-]+$", description="项目编码(PRJ-xxx)，缺省自动生成")
    name: str = Field(..., min_length=1, max_length=128, description="项目名称")
    description: str | None = Field(None, description="项目描述")


class ProjectOutSchema(BaseSchema):
    """项目响应。"""

    tenant_id: int = Field(description="所属租户ID")
    project_code: str = Field(description="项目编码")
    name: str = Field(description="项目名称")
    status: int = Field(description="项目状态(0:正常 1:停用)")
    description: str | None = Field(default=None, description="项目描述")


class ProjectAssignSchema(BaseModel):
    """项目任命（project_member_assign）：SP 必须绑定危大类别，SZ/SA 禁止携带。"""

    member_id: int = Field(..., ge=1, description="本租户有效成员ID")
    role_code: str = Field(..., pattern="^(SZ|SP|SA)$", description="项目角色(SZ:总监 SP:专监 SA:监理员)")
    hazard_codes: list[str] = Field(default_factory=list, description="专监危大类别集合(01~12；SP 必填，SZ/SA 必须为空)")


class ProjectMemberOutSchema(BaseSchema):
    """项目任命响应（含危大集合与账号信息）。"""

    tenant_id: int = Field(description="所属租户ID")
    project_id: int = Field(description="项目ID")
    member_id: int = Field(description="租户成员ID")
    role_code: str = Field(description="项目角色(SZ/SP/SA)")
    status: int = Field(description="任命状态(0:在任 1:卸任)")
    hazard_codes: list[str] = Field(default_factory=list, description="专监危大类别集合")
    username: str | None = Field(default=None, description="登录账号")
    name: str | None = Field(default=None, description="姓名")
