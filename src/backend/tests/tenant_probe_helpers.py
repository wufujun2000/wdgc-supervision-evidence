"""B0 租户隔离测试共享探针模型与工具（非测试模块，pytest 不收集）。

局部租户模型在模块导入期定义（collection 早于 TestClient 启动 create_all），
fixture 内再按依赖顺序 checkfirst 建表兜底，保证单文件/乱序运行亦可开箱即跑。
刻意不建 sys_menu（空库哨兵）：TestClient 尚未布局时 init_db 仍走 create_all+stamp 路径。
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_crud import TenantCRUDBase
from app.core.base_model import TenantModelMixin, UserMixin
from app.core.base_schema import AuthSchema
from app.core.database import async_engine
from app.core.tenant_context import TenantRequestContext
from app.modules.platform.enterprise.model import EnterpriseModel
from app.modules.system.dept.model import DeptModel
from app.modules.system.role.model import RoleModel
from app.modules.system.user.model import UserModel, UserRolesModel
from app.modules.tenant.member.model import BizTenantMemberModel as BizTenantUserModel


class TenantProbeModel(TenantModelMixin, UserMixin):
    """测试局部租户探针表（biz_* 纪律：TenantModelMixin）。"""

    __tablename__: str = "biz_tenant_probe"
    __table_args__: dict[str, str] = {"comment": "租户隔离测试探针表(测试局部)"}

    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态")
    label: Mapped[str] = mapped_column(String(64), nullable=False, comment="标签")

    children: Mapped[list[TenantProbeChildModel]] = relationship(back_populates="parent")


class TenantProbeChildModel(TenantModelMixin):
    """测试局部租户探针子表（关联预加载兜底用）。"""

    __tablename__: str = "biz_tenant_probe_child"
    __table_args__: dict[str, str] = {"comment": "租户隔离测试探针子表(测试局部)"}

    note: Mapped[str] = mapped_column(String(64), nullable=False, comment="备注")
    probe_id: Mapped[int] = mapped_column(Integer, ForeignKey("biz_tenant_probe.id"), nullable=False, index=True, comment="探针父表ID")

    parent: Mapped[TenantProbeModel] = relationship(back_populates="children")


class ProbeCreateSchema(BaseModel):
    """探针新增载荷（tenant_id 可选：缺省注入 / 伪造拒绝）。"""

    label: str
    status: int = 0
    tenant_id: int | None = None


class ProbeUpdateSchema(BaseModel):
    """探针更新载荷。"""

    label: str | None = None
    status: int | None = None
    tenant_id: int | None = None


class ProbeCRUD(TenantCRUDBase[TenantProbeModel, ProbeCreateSchema, ProbeUpdateSchema]):
    """探针租户 CRUD"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        super().__init__(model=TenantProbeModel, auth=auth, db=db)


@pytest.fixture(autouse=True)
def _isolate_tenant_context():
    """每个测试前后清空租户上下文（contextvars 线程内持久，防跨测试串号）。"""
    TenantRequestContext.clear()
    yield
    TenantRequestContext.clear()


@pytest.fixture(autouse=True)
async def _ensure_probe_tables():
    """按依赖顺序 checkfirst 建表（不建 sys_menu，保留 init_db 空库哨兵语义）。"""
    tables = [
        DeptModel.__table__,
        UserModel.__table__,
        RoleModel.__table__,
        UserRolesModel.__table__,
        EnterpriseModel.__table__,
        BizTenantUserModel.__table__,
        TenantProbeModel.__table__,
        TenantProbeChildModel.__table__,
    ]
    async with async_engine.begin() as conn:
        for table in tables:
            await conn.run_sync(lambda sync_conn, t=table: t.create(sync_conn, checkfirst=True))
    yield


def set_ctx(tenant_id: int | None, *, read_only: bool = False) -> None:
    TenantRequestContext.set(TenantRequestContext(tenant_id=tenant_id, read_only=read_only))


async def make_enterprise(db: AsyncSession, name: str) -> EnterpriseModel:
    obj = EnterpriseModel(enterprise_code=f"ENT-{uuid.uuid4().hex[:8].upper()}", name=name, status=1)
    db.add(obj)
    await db.flush()
    return obj


async def make_user(db: AsyncSession, username: str) -> UserModel:
    obj = UserModel(username=username, password="not-a-real-hash", name=username, status=0)
    db.add(obj)
    await db.flush()
    return obj


async def seed_probe(db: AsyncSession, tenant_id: int, label: str) -> TenantProbeModel:
    set_ctx(tenant_id)
    return await ProbeCRUD(AuthSchema(), db).create(ProbeCreateSchema(label=label))
