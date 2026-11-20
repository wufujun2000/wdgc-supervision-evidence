"""ORM 执行钩子兜底（B0 多租户底座）。

租户上下文存在时，对涉及 TenantModelMixin 具体模型的 ORM 语句注入租户过滤：
- SELECT：对注册表内**全部**具体租户模型挂 ``with_loader_criteria``（不在语句中的模型自动无操作），
   criteria 会传播到 joinedload/selectinload 等关联预加载目标，裸 select 同样被过滤；
- UPDATE/DELETE：直接叠加租户 WHERE（with_loader_criteria 对 DML 无效，故走 where）。

边界说明：
- 上下文不存在或 tenant_id 为 None 时不注入（平台域/后台任务合法）；
- ``text()`` 裸 SQL 绕过 ORM 事件，不在兜底范围 —— 租户域代码必须走 TenantCRUDBase；
- 本钩子是兜底防线，第一道防线仍是 TenantCRUDBase 的铁律条件。
"""

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.core.base_model import MappedBase, TenantModelMixin
from app.core.tenant_context import TenantRequestContext


def _tenant_model_classes() -> tuple[type, ...]:
    """遍历全局注册表收集具体租户模型（含测试局部模型，无需手工注册）。"""
    return tuple(mapper.class_ for mapper in MappedBase.registry.mappers if issubclass(mapper.class_, TenantModelMixin))


def _inject_tenant_criteria(orm_execute_state: ORMExecuteState) -> None:
    context = TenantRequestContext.get()
    if context is None or context.tenant_id is None:
        return
    tenant_id = context.tenant_id

    if orm_execute_state.is_select:
        for model in _tenant_model_classes():
            orm_execute_state.statement = orm_execute_state.statement.options(
                with_loader_criteria(model, lambda cls: cls.tenant_id == tenant_id, include_aliases=True)
            )
    elif orm_execute_state.is_update or orm_execute_state.is_delete:
        mapper = orm_execute_state.bind_mapper
        if mapper is not None and issubclass(mapper.class_, TenantModelMixin):
            orm_execute_state.statement = orm_execute_state.statement.where(mapper.class_.tenant_id == tenant_id)


def register_tenant_guard() -> None:
    """注册全局 do_orm_execute 兜底钩子（幂等，database.py 初始化时调用）。"""
    if not event.contains(Session, "do_orm_execute", _inject_tenant_criteria):
        event.listen(Session, "do_orm_execute", _inject_tenant_criteria)
