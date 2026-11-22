"""ADR-001 身份权限体系验收（API 场景＋服务级并发/危大范围）。

覆盖：
- 开通唯一 Owner＋审计；Owner 不进普通授权列表；(tenant_id,user_id) 唯一；
- require_permission 按授权、require_owner 全权限 Admin 也拒绝；
- 平台/租户两条移交路径、冻结规则、无效目标、并发仅一成；
- 移交后双方会话失效、原 Owner 不自动保留 Admin、项目任命与历史归属不变；
- 项目角色独立、SP 危大范围、未任命不得代行项目职责、成员停用与历史保留。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from tenant_probe_helpers import make_enterprise, make_user, set_ctx
from test_tenant_platform_api import _login, _mk_user, _provision

from app.core.base_schema import AuthSchema
from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.core.tenant_permission import require_hazard_scope
from app.modules.platform.member.crud import MemberCRUD
from app.modules.platform.member.service import execute_owner_transfer
from app.modules.tenant.member.model import BizTenantOwnerModel
from app.modules.tenant.project.service import ProjectMemberCRUD

# 复用平台 API 测试的 redis keys 兼容 fixture（mock redis 的 str 模式 keys）
pytest_plugins = ["test_tenant_platform_api", "test_tenant_isolation"]

ALL_DELEGABLE = ["tenant_member_manage", "tenant_admin_manage", "project_manage", "project_member_assign"]


def _account() -> dict:
    return {"username": f"adr_{uuid.uuid4().hex[:8]}", "name": "ADR成员", "password": "Abc123!x"}


def _create_member(client: TestClient, headers: dict, *, account: dict | None = None, user_id: int | None = None) -> dict:
    payload = {}
    if account is not None:
        payload["account"] = account
    if user_id is not None:
        payload["user_id"] = user_id
    resp = client.post("/tenant/members", json=payload, headers=headers)
    assert resp.status_code < 300, resp.text
    return resp.json()["data"]


def _grant(client: TestClient, headers: dict, member_id: int, permissions: list[str]):
    return client.post("/tenant/admins", json={"member_id": member_id, "permissions": permissions}, headers=headers)


def _transfer_tenant(client: TestClient, headers: dict, member_id: int, reason="移交测试"):
    return client.post("/tenant/owner/transfer", json={"target_member_id": member_id, "reason": reason, "confirm": True}, headers=headers)


def _transfer_platform(client: TestClient, headers: dict, tenant_id: int, member_id: int, reason="平台移交"):
    return client.post(f"/platform/enterprise/{tenant_id}/owner/transfer", json={"target_member_id": member_id, "reason": reason, "confirm": True}, headers=headers)


def _members(client: TestClient, headers: dict, tenant_id: int) -> list[dict]:
    resp = client.get(f"/platform/enterprise/{tenant_id}/members", headers=headers)
    assert resp.json()["success"] is True, resp.text
    return resp.json()["data"]


@pytest.fixture
def owner_env(test_client: TestClient, auth_headers: dict):
    """一个开通完成的租户＋Owner 登录态＋一名普通成员（account 新建）。"""
    ent = _provision(test_client, auth_headers)
    owner_headers = _login(test_client, ent["admin_username"], "Abc123!x")
    member = _create_member(test_client, owner_headers, account=_account())
    return {"ent": ent, "owner_headers": owner_headers, "member": member}


# ── Owner 模型与唯一性 ──────────────────────────────────────────
class TestOwnerModel:
    def test_provision_unique_owner_and_audit(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        ent = owner_env["ent"]
        members = _members(test_client, auth_headers, ent["id"])
        owners = [m for m in members if m["is_owner"]]
        assert len(owners) == 1
        assert owners[0]["user_id"] == ent["admin_user_id"]

        audit = test_client.get(f"/platform/enterprise/{ent['id']}/owner-audit", headers=auth_headers).json()["data"]
        assert any(row["source"] == "platform" and row["to_member_id"] == owners[0]["id"] for row in audit)

        # Owner 不得进入普通角色分配列表
        resp = _grant(test_client, owner_env["owner_headers"], owners[0]["id"], ["tenant_member_manage"])
        assert resp.status_code == 403

    def test_supplement_bind_keeps_single_owner(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        ent = owner_env["ent"]
        uid, _, _ = _mk_user(test_client, auth_headers)
        resp = test_client.post(f"/platform/enterprise/{ent['id']}/members", json={"user_id": uid}, headers=auth_headers)
        assert resp.status_code < 300, resp.text
        assert resp.json()["data"]["is_owner"] is False
        assert len([m for m in _members(test_client, auth_headers, ent["id"]) if m["is_owner"]]) == 1

    def test_owner_only_permission_not_delegable(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        resp = _grant(test_client, owner_env["owner_headers"], owner_env["member"]["id"], ["tenant_owner_transfer"])
        assert resp.status_code == 403
        assert "不可委托" in resp.json()["msg"] or "所有权专属" in resp.json()["msg"]


# ── 权限引擎 ────────────────────────────────────────────────────
class TestAdminPermissions:
    def test_admin_grant_and_scope(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        admin_member = owner_env["member"]
        admin_headers = _login(test_client, admin_member["username"], "Abc123!x")

        # 未授权：不能创建成员
        assert test_client.post("/tenant/members", json={"account": _account()}, headers=admin_headers).status_code == 403

        assert _grant(test_client, owner_env["owner_headers"], admin_member["id"], ["tenant_member_manage"]).status_code < 300
        # 仅 tenant_member_manage：可建成员；不能设管理员、不能建项目
        assert test_client.post("/tenant/members", json={"account": _account()}, headers=admin_headers).status_code < 300
        assert _grant(test_client, admin_headers, admin_member["id"], ["tenant_admin_manage"]).status_code == 403
        assert test_client.post("/tenant/projects", json={"name": "越权项目"}, headers=admin_headers).status_code == 403

    def test_admin_full_delegable_cannot_transfer(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        admin_member = owner_env["member"]
        assert _grant(test_client, owner_env["owner_headers"], admin_member["id"], ALL_DELEGABLE).status_code < 300
        admin_headers = _login(test_client, admin_member["username"], "Abc123!x")
        target = _create_member(test_client, owner_env["owner_headers"], account=_account())
        # 验收 4：全部可委托权限的 Admin 调用 require_owner 仍被拒绝
        assert _transfer_tenant(test_client, admin_headers, target["id"]).status_code == 403

    def test_admin_cannot_disable_or_demote_owner(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        admin_member = owner_env["member"]
        assert _grant(test_client, owner_env["owner_headers"], admin_member["id"], ALL_DELEGABLE).status_code < 300
        admin_headers = _login(test_client, admin_member["username"], "Abc123!x")
        owner_member_id = _members(test_client, auth_headers, owner_env["ent"]["id"])[0]["id"]

        assert test_client.post(f"/tenant/members/{owner_member_id}/disable", headers=admin_headers).status_code == 403
        assert _grant(test_client, admin_headers, owner_member_id, ["tenant_member_manage"]).status_code == 403
        assert test_client.delete(f"/tenant/admins/{owner_member_id}", headers=admin_headers).status_code == 403

    def test_admin_grant_beyond_own_scope(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        admin_member = owner_env["member"]
        assert _grant(test_client, owner_env["owner_headers"], admin_member["id"], ["tenant_member_manage"]).status_code < 300
        admin_headers = _login(test_client, admin_member["username"], "Abc123!x")
        target = _create_member(test_client, owner_env["owner_headers"], account=_account())
        assert _grant(test_client, admin_headers, target["id"], ["project_manage"]).status_code == 403

    def test_owner_needs_no_admin_record(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        resp = test_client.post("/tenant/projects", json={"name": "Owner直建项目"}, headers=owner_env["owner_headers"])
        assert resp.status_code < 300, resp.text


# ── 所有权移交 ──────────────────────────────────────────────────
class TestOwnershipTransfer:
    def test_tenant_transfer_success_and_session_purge(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        ent = owner_env["ent"]
        new_owner = owner_env["member"]
        old_headers = owner_env["owner_headers"]
        old_owner_uid = ent["admin_user_id"]

        resp = _transfer_tenant(test_client, old_headers, new_owner["id"])
        assert resp.status_code < 300, resp.text
        data = resp.json()["data"]
        assert data["to_member_id"] == new_owner["id"]
        assert data["from_member_id"] is not None
        assert data["version"] == 2

        # 双方旧会话全部失效
        assert test_client.get("/tenant/members/list", headers=old_headers).status_code == 401
        new_headers = _login(test_client, new_owner["username"], "Abc123!x")
        # 新 Owner 权限立即可用
        assert test_client.get("/tenant/owner-audit", headers=new_headers).status_code == 200
        # 原 Owner 权限立即失效，且不自动保留 TENANT_ADMIN
        old_relogin = _login(test_client, ent["admin_username"], "Abc123!x")
        assert test_client.get("/tenant/owner-audit", headers=old_relogin).status_code == 403
        members = test_client.get("/tenant/members/list", headers=new_headers).json()["data"]
        old_member = next(m for m in members if m["user_id"] == old_owner_uid)
        assert old_member["is_owner"] is False and old_member["is_admin"] is False

        audit = test_client.get(f"/platform/enterprise/{ent['id']}/owner-audit", headers=auth_headers).json()["data"]
        assert any(row["source"] == "tenant" and row["to_member_id"] == new_owner["id"] for row in audit)

    def test_platform_transfer_success_and_not_becoming_owner(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        ent = owner_env["ent"]
        resp = _transfer_platform(test_client, auth_headers, ent["id"], owner_env["member"]["id"])
        assert resp.status_code < 300, resp.text
        # 平台操作人不因此成为 Owner：超管从不在成员列表中
        admin_uid = test_client.get("/system/user/current/info", headers=auth_headers).json()["data"]["id"]
        members = _members(test_client, auth_headers, ent["id"])
        assert all(m["user_id"] != admin_uid for m in members)
        assert len([m for m in members if m["is_owner"]]) == 1
        assert members[0]["is_owner"] is False
        assert members[1]["is_owner"] is True

    def test_platform_transfer_without_permission_rejected(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        _, username, password = _mk_user(test_client, auth_headers)
        headers = _login(test_client, username, password)
        assert _transfer_platform(test_client, headers, owner_env["ent"]["id"], owner_env["member"]["id"]).status_code == 403

    def test_tenant_transfer_frozen_forbidden_platform_allowed(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        ent = owner_env["ent"]
        third = _create_member(test_client, owner_env["owner_headers"], account=_account())
        assert test_client.post(f"/platform/enterprise/freeze/{ent['id']}", headers=auth_headers).json()["data"]["status"] == 0
        # H-02：冻结企业成员在认证层即被阻断（401）；平台侧仍保留处置能力
        assert _transfer_tenant(test_client, owner_env["owner_headers"], owner_env["member"]["id"]).status_code == 401
        # 平台保留冻结处置能力
        assert _transfer_platform(test_client, auth_headers, ent["id"], third["id"]).status_code < 300

    def test_transfer_invalid_targets(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        ent = owner_env["ent"]
        other = _provision(test_client, auth_headers)
        # 跨租户目标
        other_member = _members(test_client, auth_headers, other["id"])[0]
        assert _transfer_tenant(test_client, owner_env["owner_headers"], other_member["id"]).status_code == 403
        # 当前 Owner 本人
        current = _members(test_client, auth_headers, ent["id"])[0]
        assert _transfer_tenant(test_client, owner_env["owner_headers"], current["id"]).status_code == 409
        # 停用目标
        target = _create_member(test_client, owner_env["owner_headers"], account=_account())
        assert test_client.post(f"/tenant/members/{target['id']}/disable", headers=owner_env["owner_headers"]).json()["success"] is True
        assert _transfer_tenant(test_client, owner_env["owner_headers"], target["id"]).status_code == 403

    async def test_concurrent_transfer_single_winner(self, test_client: TestClient, redis_keys_compat) -> None:
        """验收 3：并发移交仅一成，任何时刻不产生零 Owner 或双 Owner。"""
        from conftest import _mock_redis

        # 独立事务提交种子，避免与并发会话争用 SQLite 单写者锁
        async with async_db_session() as seed_db, seed_db.begin():
            ent = await make_enterprise(seed_db, "并发移交")
            owner_user = await make_user(seed_db, "conc_owner")
            target_a = await make_user(seed_db, "conc_a")
            target_b = await make_user(seed_db, "conc_b")
            crud = MemberCRUD(AuthSchema(), seed_db)
            m0 = await crud.create({"tenant_id": ent.id, "user_id": owner_user.id, "status": 0})
            ma = await crud.create({"tenant_id": ent.id, "user_id": target_a.id, "status": 0})
            mb = await crud.create({"tenant_id": ent.id, "user_id": target_b.id, "status": 0})
            await execute_owner_transfer(seed_db, _mock_redis, tenant_id=ent.id, target_member_id=m0.id, operator_user_id=None, source="platform", reason="初始化")
        tenant_id = ent.id
        target_a_id, target_b_id = ma.id, mb.id

        outcomes: list[str] = []

        async def _transfer(target_id: int) -> None:
            async with async_db_session() as session, session.begin():
                try:
                    await execute_owner_transfer(session, _mock_redis, tenant_id=ent.id, target_member_id=target_id, operator_user_id=None, source="tenant", reason="并发")
                    outcomes.append("success")
                except CustomException as exc:
                    outcomes.append(f"conflict:{exc.code}")

        await asyncio.gather(_transfer(target_a_id), _transfer(target_b_id))
        assert outcomes.count("success") == 1, outcomes
        assert any(code.startswith("conflict:409") for code in outcomes), outcomes

        from sqlalchemy import select

        async with async_db_session() as read_db:
            owners = (await read_db.execute(select(BizTenantOwnerModel).where(BizTenantOwnerModel.tenant_id == tenant_id))).scalars().all()
        assert len(owners) == 1
        assert owners[0].member_id in (target_a_id, target_b_id)
        assert owners[0].version == 2


# ── 项目任命与危大范围 ──────────────────────────────────────────
class TestProjectAppointments:
    def _setup_projects(self, client: TestClient, headers: dict):
        pa = client.post("/tenant/projects", json={"name": "项目A"}, headers=headers).json()["data"]
        pb = client.post("/tenant/projects", json={"name": "项目B"}, headers=headers).json()["data"]
        return pa, pb

    def test_role_independence_across_projects(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        member = owner_env["member"]
        headers = owner_env["owner_headers"]
        pa, pb = self._setup_projects(test_client, headers)

        resp = test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SP", "hazard_codes": ["01", "03"]}, headers=headers)
        assert resp.status_code < 300, resp.text
        resp = test_client.post(f"/tenant/projects/{pb['id']}/members", json={"member_id": member["id"], "role_code": "SZ"}, headers=headers)
        assert resp.status_code < 300, resp.text

        member_headers = _login(test_client, member["username"], "Abc123!x")
        # 同一成员：A 项目 SP、B 项目 SZ，各自独立生效
        assert test_client.get(f"/tenant/projects/{pa['id']}/members", headers=member_headers).status_code == 200
        assert test_client.get(f"/tenant/projects/{pb['id']}/members", headers=member_headers).status_code == 200
        # Owner 未获项目任命：不能代行项目职责（验收 7）
        assert test_client.get(f"/tenant/projects/{pa['id']}/members", headers=headers).status_code == 403
        # 未任命的其他成员 403
        third = _create_member(test_client, headers, account=_account())
        third_headers = _login(test_client, third["username"], "Abc123!x")
        assert test_client.get(f"/tenant/projects/{pa['id']}/members", headers=third_headers).status_code == 403

    async def test_sp_hazard_scope(self, test_client: TestClient, auth_headers: dict, owner_env, db) -> None:
        member = owner_env["member"]
        headers = owner_env["owner_headers"]
        pa, _ = self._setup_projects(test_client, headers)
        resp = test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SP", "hazard_codes": ["01"]}, headers=headers)
        assert resp.status_code < 300, resp.text

        set_ctx(owner_env["ent"]["id"])
        appointment = await ProjectMemberCRUD(AuthSchema(), db).get_or_404(project_id=pa["id"], member_id=member["id"])
        await require_hazard_scope(db, appointment, "01")  # 命中绑定集合：通过
        with pytest.raises(CustomException) as exc_info:
            await require_hazard_scope(db, appointment, "02")
        assert exc_info.value.code == 403
        with pytest.raises(CustomException):
            await require_hazard_scope(db, appointment, "99")

        # SZ 全部危大；SA 不适用专监危大动作
        sz_member = _create_member(test_client, headers, account=_account())
        resp = test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": sz_member["id"], "role_code": "SZ"}, headers=headers)
        assert resp.status_code < 300
        sz_appointment = await ProjectMemberCRUD(AuthSchema(), db).get_or_404(project_id=pa["id"], member_id=sz_member["id"])
        await require_hazard_scope(db, sz_appointment, "05")
        sa_member = _create_member(test_client, headers, account=_account())
        resp = test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": sa_member["id"], "role_code": "SA"}, headers=headers)
        assert resp.status_code < 300
        sa_appointment = await ProjectMemberCRUD(AuthSchema(), db).get_or_404(project_id=pa["id"], member_id=sa_member["id"])
        with pytest.raises(CustomException):
            await require_hazard_scope(db, sa_appointment, "01")

    def test_assignment_rules(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        member = owner_env["member"]
        headers = owner_env["owner_headers"]
        pa, _ = self._setup_projects(test_client, headers)
        # SP 必须绑定危大
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SP"}, headers=headers).status_code == 403
        # SZ/SA 禁止携带危大集合
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SZ", "hazard_codes": ["01"]}, headers=headers).status_code == 403
        # 无效危大编码
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SP", "hazard_codes": ["99"]}, headers=headers).status_code == 403
        # 合法任命后重复任命 409
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SP", "hazard_codes": ["01"]}, headers=headers).status_code < 300
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SZ"}, headers=headers).status_code == 409

    def test_transfer_keeps_project_appointments(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        member = owner_env["member"]
        headers = owner_env["owner_headers"]
        pa, _ = self._setup_projects(test_client, headers)
        # 目标成员在 A 项目任 SP；原 Owner 在 A 项目任 SZ（Owner 也须单独任命）
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SP", "hazard_codes": ["01"]}, headers=headers).status_code < 300
        owner_member_id = _members(test_client, auth_headers, owner_env["ent"]["id"])[0]["id"]
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": owner_member_id, "role_code": "SZ"}, headers=headers).status_code < 300

        assert _transfer_tenant(test_client, headers, member["id"]).status_code < 300
        # 移交后双方项目任命不变
        new_headers = _login(test_client, member["username"], "Abc123!x")
        appointments = test_client.get(f"/tenant/projects/{pa['id']}/members", headers=new_headers).json()["data"]
        by_member = {row["member_id"]: row for row in appointments}
        assert by_member[member["id"]]["role_code"] == "SP"
        assert by_member[owner_member_id]["role_code"] == "SZ"


# ── 成员生命周期与隔离 ──────────────────────────────────────────
class TestMemberLifecycle:
    def test_disable_member_blocks_access_preserves_history(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        member = owner_env["member"]
        headers = owner_env["owner_headers"]
        member_headers = _login(test_client, member["username"], "Abc123!x")
        assert test_client.post(f"/tenant/members/{member['id']}/disable", headers=headers).json()["success"] is True

        # 旧会话失效；成员记录保留（status=1），不物理删除
        assert test_client.get("/system/user/current/info", headers=member_headers).status_code == 401
        members = _members(test_client, auth_headers, owner_env["ent"]["id"])
        target = next(m for m in members if m["id"] == member["id"])
        assert target["status"] == 1
        # 重新登录后无有效成员：租户接口 fail-closed 403
        renewed = _login(test_client, member["username"], "Abc123!x")
        assert test_client.get("/tenant/members/list", headers=renewed).status_code == 403

    def test_project_cross_tenant_isolation(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        headers = owner_env["owner_headers"]
        pa = test_client.post("/tenant/projects", json={"name": "跨租户隔离项目"}, headers=headers).json()["data"]
        other = _provision(test_client, auth_headers)
        other_headers = _login(test_client, other["admin_username"], "Abc123!x")
        # 他租户成员访问本项目任命列表：403（不属于本租户/本项目）
        assert test_client.get(f"/tenant/projects/{pa['id']}/members", headers=other_headers).status_code == 403
        # 他租户项目列表不含本项目
        assert test_client.get("/tenant/projects/list", headers=other_headers).json()["data"] == []
