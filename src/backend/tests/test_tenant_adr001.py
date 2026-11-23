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
from test_tenant_platform_api import _login, _mk_user, _provision, _session_keys, _token

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


def _grant_menu_permissions(client: TestClient, admin_headers: dict, uid: int, wanted: set[str]) -> None:
    tree = client.get("/system/menu/tree", headers=admin_headers).json()["data"]
    found: dict[str, int] = {}

    def walk(nodes):
        for node in nodes:
            if node.get("permission") in wanted:
                found[node["permission"]] = node["id"]
            walk(node.get("children") or [])

    walk(tree)
    assert set(found) == wanted
    menu_ids = list(found.values())
    role = client.post(
        "/system/role/create",
        json={"name": f"权限-{uuid.uuid4().hex[:6]}", "code": f"ROLE_{uuid.uuid4().hex[:8]}", "menu_ids": menu_ids},
        headers=admin_headers,
    )
    assert role.json()["success"] is True, role.text
    role_id = role.json()["data"]["id"]
    assert client.put(
        "/system/role/permission", json={"role_ids": [role_id], "menu_ids": menu_ids, "data_scope": 3}, headers=admin_headers
    ).json()["success"] is True
    assert client.put(f"/system/user/update/{uid}", json={"role_ids": [role_id]}, headers=admin_headers).json()["success"] is True


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

        # m-04：移交前双方均建立会话（新 Owner 也有旧会话），移交后分别断言失效
        new_owner_old_headers = _login(test_client, new_owner["username"], "Abc123!x")
        resp = _transfer_tenant(test_client, old_headers, new_owner["id"])
        assert resp.status_code < 300, resp.text
        data = resp.json()["data"]
        assert data["to_member_id"] == new_owner["id"]
        assert data["from_member_id"] is not None
        assert data["version"] == 2

        # 双方旧会话全部失效
        assert test_client.get("/tenant/members/list", headers=old_headers).status_code == 401
        assert test_client.get("/tenant/members/list", headers=new_owner_old_headers).status_code == 401
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
        from conftest import _mock_redis_store

        ent = owner_env["ent"]
        old_headers = owner_env["owner_headers"]
        new_owner_old_headers = _login(test_client, owner_env["member"]["username"], "Abc123!x")
        old_keys = _session_keys(_token(old_headers))
        new_owner_keys = _session_keys(_token(new_owner_old_headers))
        resp = _transfer_platform(test_client, auth_headers, ent["id"], owner_env["member"]["id"])
        assert resp.status_code < 300, resp.text
        assert test_client.get("/tenant/members/list", headers=old_headers).status_code == 401
        assert test_client.get("/tenant/members/list", headers=new_owner_old_headers).status_code == 401
        assert all(key not in _mock_redis_store for key in old_keys + new_owner_keys)
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
            crud = MemberCRUD(AuthSchema(), seed_db)
            m0 = await crud.create({"tenant_id": ent.id, "user_id": owner_user.id, "status": 0})
            ma = await crud.create({"tenant_id": ent.id, "user_id": target_a.id, "status": 0})
            await execute_owner_transfer(seed_db, _mock_redis, tenant_id=ent.id, target_member_id=m0.id, operator_user_id=None, source="platform", reason="初始化")
        tenant_id = ent.id
        target_a_id = ma.id

        outcomes: list[str] = []

        async def _transfer(target_id: int) -> None:
            async with async_db_session() as session, session.begin():
                try:
                    await execute_owner_transfer(session, _mock_redis, tenant_id=ent.id, target_member_id=target_id, operator_user_id=None, source="tenant", reason="并发")
                    outcomes.append("success")
                except CustomException as exc:
                    outcomes.append(f"conflict:{exc.code}")

        # SQLite 单写者会令不同目标顺序成功；同目标确定一成功一 409，跨目标乐观锁由真实 MySQL 用例覆盖。
        await asyncio.gather(_transfer(target_a_id), _transfer(target_a_id))
        assert outcomes.count("success") == 1, outcomes
        assert any(code.startswith("conflict:409") for code in outcomes), outcomes

        from sqlalchemy import select

        async with async_db_session() as read_db:
            owners = (await read_db.execute(select(BizTenantOwnerModel).where(BizTenantOwnerModel.tenant_id == tenant_id))).scalars().all()
        assert len(owners) == 1
        assert owners[0].member_id == target_a_id
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


# ── 评审修复回归（Slow-2） ─────────────────────────────────────
class TestReviewFixOwnership:
    def test_admin_to_owner_to_third_clears_admin(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """B-01：A 给 B 全权限 → A→B→C 后 B 不自动保留 Admin；原 Owner 亦无 Admin 残留。"""
        owner_headers = owner_env["owner_headers"]
        member_b = owner_env["member"]
        assert _grant(test_client, owner_headers, member_b["id"], ALL_DELEGABLE).status_code < 300
        # A→B：B 成为 Owner，其旧 Admin 记录清除
        assert _transfer_tenant(test_client, owner_headers, member_b["id"]).status_code < 300
        b_headers = _login(test_client, member_b["username"], "Abc123!x")
        members = test_client.get("/tenant/members/list", headers=b_headers).json()["data"]
        assert next(m for m in members if m["id"] == member_b["id"])["is_admin"] is False

        # B→C：B 卸任后同样不保留 Admin
        member_c = _create_member(test_client, b_headers, account=_account())
        assert _transfer_tenant(test_client, b_headers, member_c["id"]).status_code < 300
        c_headers = _login(test_client, member_c["username"], "Abc123!x")
        members = test_client.get("/tenant/members/list", headers=c_headers).json()["data"]
        assert next(m for m in members if m["id"] == member_b["id"])["is_admin"] is False
        assert next(m for m in members if m["id"] == member_c["id"])["is_owner"] is True

    def test_revoke_admin_success(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """M-01：正常撤销成功（commit 在输出之后，无 InvalidRequestError）。"""
        owner_headers = owner_env["owner_headers"]
        member = owner_env["member"]
        assert _grant(test_client, owner_headers, member["id"], ["tenant_member_manage"]).status_code < 300
        resp = test_client.delete(f"/tenant/admins/{member['id']}", headers=owner_headers)
        assert resp.status_code < 300, resp.text
        assert resp.json()["data"]["is_admin"] is False
        admin_headers = _login(test_client, member["username"], "Abc123!x")
        assert test_client.post("/tenant/members", json={"account": _account()}, headers=admin_headers).status_code == 403

    def test_disabled_or_deleted_account_cannot_own(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """M-02：停用账号开通/绑定/移交均被拒；当前 Owner 原生停用/删除被 M-12 拦截。"""
        uid, username, password = _mk_user(test_client, auth_headers)
        assert test_client.put(f"/system/user/update/{uid}", json={"status": 1}, headers=auth_headers).json()["success"] is True
        # 停用账号开通 → 403
        resp = test_client.post("/platform/enterprise/create", json={"name": "停用账号开通", "admin_user_id": uid}, headers=auth_headers)
        assert resp.status_code == 403
        # 停用账号绑定 → 403（平台与租户两端）
        assert test_client.post(f"/platform/enterprise/{owner_env['ent']['id']}/members", json={"user_id": uid}, headers=auth_headers).status_code == 403
        assert test_client.post("/tenant/members", json={"user_id": uid}, headers=owner_env["owner_headers"]).status_code == 403
        # 软删账号租户绑定 → 404；停用统一账号的非 Owner 目标移交 → 403
        deleted_uid, _, _ = _mk_user(test_client, auth_headers)
        assert test_client.request("DELETE", "/system/user/delete", json=[deleted_uid], headers=auth_headers).json()["success"] is True
        assert test_client.post("/tenant/members", json={"user_id": deleted_uid}, headers=owner_env["owner_headers"]).status_code == 404
        target_uid, _, _ = _mk_user(test_client, auth_headers)
        target = _create_member(test_client, owner_env["owner_headers"], user_id=target_uid)
        assert test_client.put(f"/system/user/update/{target_uid}", json={"status": 1}, headers=auth_headers).json()["success"] is True
        assert _transfer_tenant(test_client, owner_env["owner_headers"], target["id"]).status_code == 403

    def test_platform_dedicated_permission_cross_tenant(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """M-04：非超管专门权限账号可跨租户移交、可读候选、不被自身冻结租户拦截。"""
        ent_a = owner_env["ent"]
        ent_b = _provision(test_client, auth_headers)
        old_b_headers = _login(test_client, ent_b["admin_username"], "Abc123!x")
        old_b_keys = _session_keys(_token(old_b_headers))
        uid, username, password = _mk_user(test_client, auth_headers)
        # 角色携带移交菜单权限
        tree = test_client.get("/system/menu/tree", headers=auth_headers).json()["data"]

        def find_perm(nodes):
            for node in nodes:
                if node.get("permission") == "module_platform:enterprise:transfer":
                    return node["id"]
                found = find_perm(node.get("children") or [])
                if found:
                    return found
            return None

        menu_id = find_perm(tree)
        assert menu_id is not None
        role_resp = test_client.post("/system/role/create", json={"name": f"移交专员-{uuid.uuid4().hex[:6]}", "code": f"TRANSFER_{uuid.uuid4().hex[:6]}", "menu_ids": [menu_id]}, headers=auth_headers)
        assert role_resp.json()["success"] is True, role_resp.text
        role_id = role_resp.json()["data"]["id"]
        # 角色授权走专门端点（create/update 不处理 menu_ids）
        assert test_client.put("/system/role/permission", json={"role_ids": [role_id], "menu_ids": [menu_id], "data_scope": 3}, headers=auth_headers).json()["success"] is True
        assert test_client.put(f"/system/user/update/{uid}", json={"role_ids": [role_id]}, headers=auth_headers).json()["success"] is True
        # 加入租户 A（非 Owner），再冻结 A：平台处置仍应放行
        assert test_client.post(f"/platform/enterprise/{ent_a['id']}/members", json={"user_id": uid}, headers=auth_headers).status_code < 300
        assert test_client.post(f"/platform/enterprise/freeze/{ent_a['id']}", headers=auth_headers).json()["success"] is True

        x_headers = _login(test_client, username, password)
        # 专门权限可加载企业页及移交详情，不再被超管门禁阻断
        assert test_client.get("/platform/enterprise/list", params={"page_no": 1, "page_size": 10}, headers=x_headers).status_code == 200
        assert test_client.get(f"/platform/enterprise/detail/{ent_b['id']}", headers=x_headers).status_code == 200
        # 可读 B 候选成员（移交专门权限）
        members_b = test_client.get(f"/platform/enterprise/{ent_b['id']}/members", headers=x_headers)
        assert members_b.status_code == 200, members_b.text
        # B 目前只有 Owner，先补一名非 Owner 成员作为移交目标
        uid2, _, _ = _mk_user(test_client, auth_headers)
        assert test_client.post(f"/platform/enterprise/{ent_b['id']}/members", json={"user_id": uid2}, headers=auth_headers).status_code < 300
        members_b = test_client.get(f"/platform/enterprise/{ent_b['id']}/members", headers=x_headers).json()["data"]
        target_b = next(m for m in members_b if not m["is_owner"])
        # 平台移交 B（X 属于 A 且 A 冻结，仍应成功）
        resp = _transfer_platform(test_client, x_headers, ent_b["id"], target_b["id"])
        assert resp.status_code < 300, resp.text
        from conftest import _mock_redis_store

        assert test_client.get("/tenant/members/list", headers={**old_b_headers, "X-Tenant-Id": str(ent_b["id"])}).status_code == 401
        assert all(key not in _mock_redis_store for key in old_b_keys)
        # X 不因此成为 B 的 Owner/成员
        members_b_after = test_client.get(f"/platform/enterprise/{ent_b['id']}/members", headers=x_headers).json()["data"]
        assert all(m["user_id"] != uid for m in members_b_after)
        assert any(m["id"] == target_b["id"] and m["is_owner"] for m in members_b_after)

    def test_old_module_removed_from_metadata(self) -> None:
        """M-05：旧 tenant_user 模型已从运行元数据移除（fresh create_all 不再创建 biz_tenant_user）。"""
        from app.core.base_model import MappedBase

        assert "biz_tenant_user" not in MappedBase.metadata.tables
        assert "biz_tenant_member" in MappedBase.metadata.tables

    def test_owner_binds_other_account_and_names_visible(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """M-10：Owner 绑定他人账号不被 DATA_SCOPE_SELF 误拦；他人姓名可见；新账号带 USER 角色。"""
        uid, username, password = _mk_user(test_client, auth_headers)
        resp = test_client.post("/tenant/members", json={"user_id": uid}, headers=owner_env["owner_headers"])
        assert resp.status_code < 300, resp.text
        members = test_client.get("/tenant/members/list", headers=owner_env["owner_headers"]).json()["data"]
        other = next(m for m in members if m["user_id"] == uid)
        assert other["username"] == username and other["name"] is not None
        # 新账号自查可用（USER 角色已分配）
        info = test_client.get("/system/user/current/info", headers=_login(test_client, username, password)).json()["data"]
        assert info["tenant_id"] == owner_env["ent"]["id"]

    def test_failed_transfer_writes_audit(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """越权/业务失败均审计；A 域操作者不得把 B 的 from_member_id 过滤为 NULL。"""
        ent = owner_env["ent"]
        current = next(row for row in _members(test_client, auth_headers, ent["id"]) if row["is_owner"])
        other = _provision(test_client, auth_headers)
        other_member = _members(test_client, auth_headers, other["id"])[0]
        reason = f"跨租户目标-{uuid.uuid4().hex[:6]}"
        assert _transfer_platform(test_client, auth_headers, ent["id"], other_member["id"], reason).status_code == 403
        audit = test_client.get(f"/platform/enterprise/{ent['id']}/owner-audit", headers=auth_headers).json()["data"]
        row = next(row for row in audit if row["reason"] == reason)
        assert row["result"] == "failed" and row["from_member_id"] == current["id"]

        # A 域专门权限账号对 B 的当前 Owner 发起冲突移交，审计仍读取 B 原 Owner。
        uid, username, password = _mk_user(test_client, auth_headers)
        _grant_menu_permissions(test_client, auth_headers, uid, {"module_platform:enterprise:transfer"})
        assert test_client.post(f"/platform/enterprise/{ent['id']}/members", json={"user_id": uid}, headers=auth_headers).status_code < 300
        x_headers = _login(test_client, username, password)
        x_reason = f"A到B失败-{uuid.uuid4().hex[:6]}"
        assert _transfer_platform(test_client, x_headers, other["id"], other_member["id"], x_reason).status_code == 409
        b_audit = test_client.get(f"/platform/enterprise/{other['id']}/owner-audit", headers=auth_headers).json()["data"]
        x_row = next(row for row in b_audit if row["reason"] == x_reason)
        assert x_row["result"] == "failed" and x_row["from_member_id"] == other_member["id"]

        # 全 delegable Admin 仍非 Owner，require_owner 失败也进入失败审计。
        admin = owner_env["member"]
        assert _grant(test_client, owner_env["owner_headers"], admin["id"], ALL_DELEGABLE).status_code < 300
        admin_headers = _login(test_client, admin["username"], "Abc123!x")
        admin_reason = f"Admin越权-{uuid.uuid4().hex[:6]}"
        assert _transfer_tenant(test_client, admin_headers, current["id"], admin_reason).status_code == 403
        admin_audit = test_client.get(f"/platform/enterprise/{ent['id']}/owner-audit", headers=auth_headers).json()["data"]
        admin_row = next(row for row in admin_audit if row["reason"] == admin_reason)
        assert admin_row["result"] == "failed" and admin_row["from_member_id"] == current["id"]

    def test_native_account_disable_delete_owner_protected(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """M-12：原生 update(status=1)/batch/delete 对当前 Owner 均拒绝；移交后可停用原 Owner。"""
        owner_uid = owner_env["ent"]["admin_user_id"]
        assert test_client.put(f"/system/user/update/{owner_uid}", json={"status": 1}, headers=auth_headers).status_code == 403
        assert test_client.patch("/system/user/status/batch", json={"ids": [owner_uid], "status": 1}, headers=auth_headers).status_code == 403
        assert test_client.request("DELETE", "/system/user/delete", json=[owner_uid], headers=auth_headers).status_code == 403
        # 移交后原 Owner 可停用
        new_owner = owner_env["member"]
        assert _transfer_tenant(test_client, owner_env["owner_headers"], new_owner["id"]).status_code < 300
        assert test_client.put(f"/system/user/update/{owner_uid}", json={"status": 1}, headers=auth_headers).status_code < 300

    def test_cross_tenant_native_owner_protection(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """操作者上下文属于 A 时，原生账号写路径仍必须保护 B 的当前 Owner。"""
        targets = [_provision(test_client, auth_headers) for _ in range(3)]
        uid, username, password = _mk_user(test_client, auth_headers)
        _grant_menu_permissions(
            test_client, auth_headers, uid, {"module_system:user:update", "module_system:user:patch", "module_system:user:delete"}
        )
        bound = test_client.post(
            f"/platform/enterprise/{owner_env['ent']['id']}/members", json={"user_id": uid}, headers=auth_headers
        )
        assert bound.status_code < 300, bound.text
        headers = _login(test_client, username, password)
        update_uid, batch_uid, delete_uid = (ent["admin_user_id"] for ent in targets)
        assert test_client.put(f"/system/user/update/{update_uid}", json={"status": 1}, headers=headers).status_code == 403
        assert test_client.patch("/system/user/status/batch", json={"ids": [batch_uid], "status": 1}, headers=headers).status_code == 403
        assert test_client.request("DELETE", "/system/user/delete", json=[delete_uid], headers=headers).status_code == 403
        for ent, target_uid in zip(targets, (update_uid, batch_uid, delete_uid), strict=True):
            detail = test_client.get(f"/system/user/detail/{target_uid}", headers=auth_headers).json()["data"]
            assert detail["status"] == 0 and detail["is_deleted"] is False
            members = _members(test_client, auth_headers, ent["id"])
            assert any(row["user_id"] == target_uid and row["is_owner"] for row in members)

    def test_owner_target_permission_update_rejected(self, test_client: TestClient, auth_headers: dict, owner_env, db) -> None:
        """M-13：Owner 不得作为 PUT /tenant/admins/{id}/permissions 目标。"""
        from app.modules.tenant.member.model import BizTenantAdminModel

        ent = owner_env["ent"]
        owner_member_id = _members(test_client, auth_headers, ent["id"])[0]["id"]
        # 模拟存量 Owner＋Admin 行（迁移已清理此类，本用例验证入口保护）
        db.add(BizTenantAdminModel(tenant_id=ent["id"], member_id=owner_member_id))
        resp = test_client.put(f"/tenant/admins/{owner_member_id}/permissions", json={"permissions": ["tenant_member_manage"]}, headers=owner_env["owner_headers"])
        assert resp.status_code == 403

    def test_blank_reason_rejected(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """m-02：全空白原因服务端拒绝（422）。"""
        resp = test_client.post(
            "/tenant/owner/transfer",
            json={"target_member_id": owner_env["member"]["id"], "reason": "   ", "confirm": True},
            headers=owner_env["owner_headers"],
        )
        assert resp.status_code == 422

    def test_expire_on_commit_config_safe(self, test_client: TestClient, auth_headers: dict, owner_env, monkeypatch: pytest.MonkeyPatch) -> None:
        """m-05：EXPIRE_ON_COMMIT=True 时停用/建项目不触发隐式刷新。"""
        from app.config.setting import settings
        from app.core.database import async_db_session

        monkeypatch.setattr(settings, "EXPIRE_ON_COMMIT", True)
        monkeypatch.setitem(async_db_session.kw, "expire_on_commit", True)
        owner_headers = owner_env["owner_headers"]
        resp = test_client.post("/tenant/projects", json={"name": "过期配置项目"}, headers=owner_headers)
        assert resp.status_code < 300, resp.text
        target = _create_member(test_client, owner_headers, account=_account())
        assert test_client.post(f"/tenant/members/{target['id']}/disable", headers=owner_headers).status_code < 300
        platform_target = _create_member(test_client, owner_headers, account=_account())
        assert test_client.post(f"/platform/enterprise/members/{platform_target['id']}/disable", headers=auth_headers).status_code < 300


    async def test_transfer_vs_disable_never_disabled_owner(self, test_client: TestClient) -> None:
        """M-03：移交与停用竞态，不产生已停用的 Owner。"""
        from conftest import _mock_redis

        async with async_db_session() as seed_db, seed_db.begin():
            ent = await make_enterprise(seed_db, "移交停用竞态")
            owner_user = await make_user(seed_db, "race_owner")
            target_user = await make_user(seed_db, "race_target")
            crud = MemberCRUD(AuthSchema(), seed_db)
            owner_member = await crud.create({"tenant_id": ent.id, "user_id": owner_user.id, "status": 0})
            target_member = await crud.create({"tenant_id": ent.id, "user_id": target_user.id, "status": 0})
            await execute_owner_transfer(seed_db, _mock_redis, tenant_id=ent.id, target_member_id=owner_member.id, operator_user_id=None, source="platform", reason="初始化")
        tenant_id = ent.id
        owner_member_id = owner_member.id
        target_member_id = target_member.id

        async def _disable() -> str:
            from app.core.base_schema import CoreUserSchema
            from app.modules.tenant.member.service import TenantMemberService

            async with async_db_session() as session, session.begin():
                set_ctx(tenant_id)
                try:
                    service = TenantMemberService(AuthSchema(user=CoreUserSchema(id=owner_user.id, is_superuser=False)), session)
                    await service.disable_member(target_member_id, _mock_redis)
                    return "disable_success"
                except CustomException as exc:
                    return f"disable_fail:{exc.code}"

        async def _transfer() -> str:
            from app.core.base_schema import CoreUserSchema
            from app.modules.tenant.member.service import TenantMemberService

            async with async_db_session() as session, session.begin():
                set_ctx(tenant_id)
                try:
                    service = TenantMemberService(AuthSchema(user=CoreUserSchema(id=owner_user.id, is_superuser=False)), session)
                    await service.transfer_owner(target_member_id, "竞态", _mock_redis)
                    return "transfer_success"
                except CustomException as exc:
                    return f"transfer_fail:{exc.code}"

        outcomes = await asyncio.gather(_disable(), _transfer())
        from sqlalchemy import select

        from app.modules.tenant.member.model import BizTenantMemberModel

        async with async_db_session() as read_db:
            owner = (await read_db.execute(select(BizTenantOwnerModel).where(BizTenantOwnerModel.tenant_id == tenant_id))).scalar_one()
            member = (await read_db.execute(select(BizTenantMemberModel).where(BizTenantMemberModel.id == target_member_id))).scalar_one()
        # 不允许 Owner 指向已停用成员；只允许两种一致结局
        if owner.member_id == target_member_id:
            assert member.status == 0, "停用成员成为 Owner（竞态缺陷）"
            assert "transfer_success" in outcomes
        else:
            assert owner.member_id == owner_member_id
            assert member.status == 1 or any(str(o).startswith("disable_fail") for o in outcomes)


class TestReviewFixProjects:
    async def test_project_disable_and_negative_cases(self, test_client: TestClient, auth_headers: dict, owner_env, db) -> None:
        """m-06：卸任后 403 且历史保留、错配 404、跨租户任命拒绝、未任命全权限 Admin 403、SA 危大 403。"""
        owner_headers = owner_env["owner_headers"]
        member = owner_env["member"]
        pa = test_client.post("/tenant/projects", json={"name": "卸任项目"}, headers=owner_headers).json()["data"]
        pb = test_client.post("/tenant/projects", json={"name": "其他项目"}, headers=owner_headers).json()["data"]
        assign = test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": member["id"], "role_code": "SP", "hazard_codes": ["01"]}, headers=owner_headers)
        assert assign.status_code < 300
        appointment_id = assign.json()["data"]["id"]

        # 项目/任命错配 404
        assert test_client.post(f"/tenant/projects/{pb['id']}/members/{appointment_id}/disable", headers=owner_headers).status_code == 404
        # 卸任后成员访问 403，任命与危大历史保留
        assert test_client.post(f"/tenant/projects/{pa['id']}/members/{appointment_id}/disable", headers=owner_headers).status_code < 300
        member_headers = _login(test_client, member["username"], "Abc123!x")
        assert test_client.get(f"/tenant/projects/{pa['id']}/members", headers=member_headers).status_code == 403
        from sqlalchemy import select

        from app.modules.tenant.project.model import BizProjectMemberHazardModel

        set_ctx(owner_env["ent"]["id"])
        appointment = await ProjectMemberCRUD(AuthSchema(), db).get_or_404(id=appointment_id)
        assert appointment.status == 1
        hazards = (await db.execute(select(BizProjectMemberHazardModel.hazard_code).where(BizProjectMemberHazardModel.project_member_id == appointment_id))).scalars().all()
        assert list(hazards) == ["01"]

        # 未任命的全权限 Admin 同样 403
        admin_member = _create_member(test_client, owner_headers, account=_account())
        assert _grant(test_client, owner_headers, admin_member["id"], ALL_DELEGABLE).status_code < 300
        admin_headers = _login(test_client, admin_member["username"], "Abc123!x")
        assert test_client.get(f"/tenant/projects/{pa['id']}/members", headers=admin_headers).status_code == 403
        # SA 携带危大 403
        assert test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": admin_member["id"], "role_code": "SA", "hazard_codes": ["01"]}, headers=owner_headers).status_code == 403

    def test_cross_tenant_assignment_rejected(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """m-06：他租户成员不得被任命到本项目。"""
        owner_headers = owner_env["owner_headers"]
        pa = test_client.post("/tenant/projects", json={"name": "跨租户任命项目"}, headers=owner_headers).json()["data"]
        other = _provision(test_client, auth_headers)
        other_member = _members(test_client, auth_headers, other["id"])[0]
        resp = test_client.post(f"/tenant/projects/{pa['id']}/members", json={"member_id": other_member["id"], "role_code": "SZ"}, headers=owner_headers)
        assert resp.status_code in (403, 404)

    def test_cross_tenant_appointment_disable_combinations(self, test_client: TestClient, auth_headers: dict, owner_env) -> None:
        """跨租户 project_id/appointment_id 组合均不可写，双方任命保持在职。"""
        a_headers = owner_env["owner_headers"]
        a_project = test_client.post("/tenant/projects", json={"name": "A任命项目"}, headers=a_headers).json()["data"]
        a_assignment = test_client.post(
            f"/tenant/projects/{a_project['id']}/members", json={"member_id": owner_env["member"]["id"], "role_code": "SZ"}, headers=a_headers
        )
        assert a_assignment.status_code < 300, a_assignment.text
        a_appointment = a_assignment.json()["data"]["id"]

        ent_b = _provision(test_client, auth_headers)
        b_headers = _login(test_client, ent_b["admin_username"], "Abc123!x")
        b_member = _create_member(test_client, b_headers, account=_account())
        b_project = test_client.post("/tenant/projects", json={"name": "B任命项目"}, headers=b_headers).json()["data"]
        b_assignment = test_client.post(
            f"/tenant/projects/{b_project['id']}/members", json={"member_id": b_member["id"], "role_code": "SZ"}, headers=b_headers
        )
        assert b_assignment.status_code < 300, b_assignment.text
        b_appointment = b_assignment.json()["data"]["id"]

        assert test_client.post(
            f"/tenant/projects/{b_project['id']}/members/{a_appointment}/disable", headers=a_headers
        ).status_code in (403, 404)
        assert test_client.post(
            f"/tenant/projects/{a_project['id']}/members/{b_appointment}/disable", headers=a_headers
        ).status_code in (403, 404)
        a_member_headers = _login(test_client, owner_env["member"]["username"], "Abc123!x")
        b_member_headers = _login(test_client, b_member["username"], "Abc123!x")
        a_rows = test_client.get(f"/tenant/projects/{a_project['id']}/members", headers=a_member_headers).json()["data"]
        b_rows = test_client.get(f"/tenant/projects/{b_project['id']}/members", headers=b_member_headers).json()["data"]
        assert next(row for row in a_rows if row["id"] == a_appointment)["status"] == 0
        assert next(row for row in b_rows if row["id"] == b_appointment)["status"] == 0

