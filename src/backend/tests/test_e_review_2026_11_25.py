"""E 复审（2026-11-25）合并门禁条件修复回归：C1/C2/C3 ＋ F-03。

- C1：缺省租户解析优先未冻结租户；全部冻结才拦截；平台专员 current/info 自查不清退会话；
- C2：批量导入停用现任 Owner 被拒（与 update/set_available 同守卫），其余行不受牵连；
- C3：第三方自动注册默认授种子 USER 角色，不获 ADMIN/SUPER_ADMIN；
- F-03：owner-audit 认菜单按钮权限码 module_platform:enterprise:audit，无权限拒绝。
"""

from __future__ import annotations

import uuid
from io import BytesIO

import pytest
from conftest import _mock_redis_store
from fastapi.testclient import TestClient
from openpyxl import Workbook
from test_tenant_adr001 import _grant_menu_permissions
from test_tenant_platform_api import _login, _mk_user, _provision, _session_keys, _snapshot, _token

pytest_plugins = ["test_tenant_platform_api", "test_tenant_isolation"]


def _bind(client: TestClient, headers: dict, tenant_id: int, user_id: int) -> dict:
    resp = client.post(f"/platform/enterprise/{tenant_id}/members", json={"user_id": user_id}, headers=headers)
    assert resp.status_code < 300, resp.text
    return resp.json()["data"]


def _freeze(client: TestClient, headers: dict, tenant_id: int) -> None:
    assert client.post(f"/platform/enterprise/freeze/{tenant_id}", headers=headers).json()["success"] is True


def _dept_id(client: TestClient, headers: dict) -> int:
    tree = client.get("/system/dept/tree", headers=headers).json()["data"]
    assert tree, "种子部门缺失"
    return tree[0]["id"]


def _import_file(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["部门编号", "账号", "昵称", "邮箱", "手机号", "性别", "状态"])
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post_import(client: TestClient, headers: dict, content: bytes):
    return client.post(
        "/system/user/import/data",
        files={"file": ("import.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )


# ── C1 冻结租户缺省解析 ──────────────────────────────────────────
class TestC1FrozenDefaultResolution:
    def test_first_tenant_frozen_still_reaches_active_tenant(self, test_client: TestClient, auth_headers: dict) -> None:
        """首租户冻结时，缺省 X-Tenant-Id 仍解析到正常租户（登录快照与请求认证同口径）。"""
        uid, username, password = _mk_user(test_client, auth_headers)
        ent_a = _provision(test_client, auth_headers, admin_user_id=uid)  # 首租户（最早成员，Owner）
        ent_b = _provision(test_client, auth_headers)
        _bind(test_client, auth_headers, ent_b["id"], uid)  # 后加入的正常租户
        _freeze(test_client, auth_headers, ent_a["id"])

        headers = _login(test_client, username, password)
        # 登录快照经 get_first_active_member 也优先未冻结租户
        assert _snapshot(_token(headers))["tenant_id"] == ent_b["id"]
        info = test_client.get("/system/user/current/info", headers=headers)
        assert info.status_code == 200, info.text
        assert info.json()["data"]["tenant_id"] == ent_b["id"]
        assert test_client.get("/tenant/members/list", headers=headers).status_code == 200
        # 显式选择冻结租户仍按 H-02 拦截（语义不变）
        assert (
            test_client.get("/system/user/current/info", headers={**headers, "X-Tenant-Id": str(ent_a["id"])}).status_code
            == 401
        )

    def test_all_tenants_frozen_blocked_and_purged(self, test_client: TestClient, auth_headers: dict) -> None:
        """全部所属租户冻结才回退拦截：普通账号自查 401 且会话清退。"""
        uid, username, password = _mk_user(test_client, auth_headers)
        ent = _provision(test_client, auth_headers, admin_user_id=uid)
        _freeze(test_client, auth_headers, ent["id"])

        headers = _login(test_client, username, password)
        keys = _session_keys(_token(headers))
        resp = test_client.get("/system/user/current/info", headers=headers)
        assert resp.status_code == 401
        assert all(key not in _mock_redis_store for key in keys)

    def test_platform_specialist_self_info_keeps_session_and_transfer(self, test_client: TestClient, auth_headers: dict) -> None:
        """平台移交专员兼属冻结租户：current/info 不清退会话，兜底移交仍可执行。"""
        ent = _provision(test_client, auth_headers)
        target = _bind(test_client, auth_headers, ent["id"], _mk_user(test_client, auth_headers)[0])
        uid, username, password = _mk_user(test_client, auth_headers)
        _grant_menu_permissions(test_client, auth_headers, uid, {"module_platform:enterprise:transfer"})
        _bind(test_client, auth_headers, ent["id"], uid)
        _freeze(test_client, auth_headers, ent["id"])

        headers = _login(test_client, username, password)
        keys = _session_keys(_token(headers))
        resp = test_client.get("/system/user/current/info", headers=headers)
        assert resp.status_code == 200, resp.text
        assert all(key in _mock_redis_store for key in keys)
        # 自查后兜底移交仍可用（冻结期间平台处置能力保留）
        resp = test_client.post(
            f"/platform/enterprise/{ent['id']}/owner/transfer",
            json={"target_member_id": target["id"], "reason": "冻结兜底移交", "confirm": True},
            headers=headers,
        )
        assert resp.status_code < 300, resp.text

    def test_platform_specialist_explicit_frozen_tenant_rejected(self, test_client: TestClient, auth_headers: dict) -> None:
        """C1 返工：显式 X-Tenant-Id 选中冻结租户一律 401 并清退，平台权限账号自查豁免不适用。"""
        ent = _provision(test_client, auth_headers)
        uid, username, password = _mk_user(test_client, auth_headers)
        _grant_menu_permissions(test_client, auth_headers, uid, {"module_platform:enterprise:transfer"})
        _bind(test_client, auth_headers, ent["id"], uid)
        _freeze(test_client, auth_headers, ent["id"])

        headers = _login(test_client, username, password)
        # 缺省解析自查仍豁免（兜底移交入口保留）
        assert test_client.get("/system/user/current/info", headers=headers).status_code == 200
        keys = _session_keys(_token(headers))
        # 显式选中冻结租户：豁免不适用，401＋会话清退
        resp = test_client.get("/system/user/current/info", headers={**headers, "X-Tenant-Id": str(ent["id"])})
        assert resp.status_code == 401
        assert all(key not in _mock_redis_store for key in keys)


# ── C2 批量导入 Owner 停用保护 ───────────────────────────────────
class TestC2ImportOwnerProtection:
    def test_import_disable_current_owner_rejected(self, test_client: TestClient, auth_headers: dict) -> None:
        ent = _provision(test_client, auth_headers)
        owner_uid = ent["admin_user_id"]
        dept_id = _dept_id(test_client, auth_headers)
        content = _import_file([[dept_id, ent["admin_username"], "拥有者", None, None, "男", "停用"]])
        resp = _post_import(test_client, auth_headers, content)
        assert resp.status_code == 200, resp.text
        result = resp.json()["data"]
        assert "成功导入 0 条" in result
        assert "企业拥有者" in result
        detail = test_client.get(f"/system/user/detail/{owner_uid}", headers=auth_headers).json()["data"]
        assert detail["status"] == 0 and detail["is_deleted"] is False

    def test_import_mixed_rows_owner_rejected_other_imported(self, test_client: TestClient, auth_headers: dict) -> None:
        """Owner 行被拒不牵连其余行；非 Owner 账号仍可经导入停用。"""
        ent = _provision(test_client, auth_headers)
        member_uid, member_username, _ = _mk_user(test_client, auth_headers)
        _bind(test_client, auth_headers, ent["id"], member_uid)
        dept_id = _dept_id(test_client, auth_headers)
        content = _import_file(
            [
                [dept_id, ent["admin_username"], "拥有者", None, None, "男", "停用"],
                [dept_id, member_username, "成员", None, None, "女", "停用"],
            ]
        )
        resp = _post_import(test_client, auth_headers, content)
        assert resp.status_code == 200, resp.text
        result = resp.json()["data"]
        assert "成功导入 1 条" in result
        assert "企业拥有者" in result
        owner = test_client.get(f"/system/user/detail/{ent['admin_user_id']}", headers=auth_headers).json()["data"]
        member = test_client.get(f"/system/user/detail/{member_uid}", headers=auth_headers).json()["data"]
        assert owner["status"] == 0
        assert member["status"] == 1

    async def test_import_post_write_owner_race_rolls_back_only_row(
        self, test_client: TestClient, auth_headers: dict, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """预检通过、写时 Owner 已在任：写后复核失败，SAVEPOINT 仅回滚本行更新，后续行不受影响。"""
        from unittest.mock import AsyncMock

        from sqlalchemy import select
        from tenant_probe_helpers import make_enterprise, make_user

        from app.core.base_schema import AuthSchema
        from app.modules.system.dept.model import DeptModel
        from app.modules.system.user.model import UserModel
        from app.modules.system.user.service import UserService
        from app.modules.tenant.member.model import BizTenantMemberModel, BizTenantOwnerModel

        ent = await make_enterprise(db, "导入竞态企业")
        owner_user = await make_user(db, f"race_owner_{uuid.uuid4().hex[:6]}")
        member = BizTenantMemberModel(tenant_id=ent.id, user_id=owner_user.id, status=0)
        db.add(member)
        await db.flush()
        db.add(BizTenantOwnerModel(tenant_id=ent.id, member_id=member.id, version=1))
        normal_user = await make_user(db, f"race_normal_{uuid.uuid4().hex[:6]}")
        await db.flush()
        dept_id = (
            await db.execute(select(DeptModel.id).where(DeptModel.is_deleted == False).limit(1))  # noqa: E712
        ).scalar_one()
        # SAVEPOINT 回滚会 expire 被改对象：先固化 id/username，断言只用纯值，避免异步外懒加载
        owner_uid, normal_uid = owner_user.id, normal_user.id
        owner_username, normal_username = owner_user.username, normal_user.username

        svc = UserService(AuthSchema(), db)
        # 模拟竞态：预检在 Owner 写入前已通过（跳过预检），写后复核必须兜住
        monkeypatch.setattr(svc, "_reject_if_current_owner", AsyncMock())
        row = {
            "username": owner_username, "name": "拥有者", "dept_id": dept_id,
            "email": None, "mobile": None, "gender": "男", "status": "停用",
        }
        delta, err = await svc._process_import_row(2, row, True)
        assert delta == 0 and err is not None and "企业拥有者" in err
        # 本行停用更新已被 SAVEPOINT 回滚（列查询取库内真值，避开身份映射缓存）
        assert (
            await db.execute(select(UserModel.status).where(UserModel.id == owner_uid))
        ).scalar_one() == 0

        # 会话仍可用：后续普通行照常导入停用
        row2 = {
            "username": normal_username, "name": "成员", "dept_id": dept_id,
            "email": None, "mobile": None, "gender": "女", "status": "停用",
        }
        delta2, err2 = await svc._process_import_row(3, row2, True)
        assert delta2 == 1 and err2 is None
        assert (
            await db.execute(select(UserModel.status).where(UserModel.id == normal_uid))
        ).scalar_one() == 1


# ── C3 第三方自动注册默认角色 ────────────────────────────────────
class TestC3OAuthDefaultRole:
    async def test_auto_register_defaults_to_user_not_admin(
        self, test_client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sqlalchemy import select

        from app.config.setting import settings
        from app.core.database import async_db_session
        from app.modules.system.auth.service import auto_register_login_user
        from app.modules.system.role.model import RoleModel
        from app.modules.system.user.model import UserRolesModel

        # 固定随机密码，排除口令复杂度抽样的偶发干扰（角色口径才是本用例断言对象）
        monkeypatch.setattr(
            "app.modules.system.auth.service.secrets.token_urlsafe", lambda n: "Oauth#2026xYz1234567890ab"
        )
        username = f"oauth_{uuid.uuid4().hex[:8]}"
        async with async_db_session() as session, session.begin():
            user = await auto_register_login_user(
                db=session, username=username, display_name="第三方用户", fail_msg="注册失败"
            )
            codes = (
                (
                    await session.execute(
                        select(RoleModel.code)
                        .join(UserRolesModel, UserRolesModel.role_id == RoleModel.id)
                        .where(UserRolesModel.user_id == user.id)
                    )
                )
                .scalars()
                .all()
            )
            admin_ids = (
                (
                    await session.execute(select(RoleModel.id).where(RoleModel.code.in_(["ADMIN", "SUPER_ADMIN"])))
                )
                .scalars()
                .all()
            )
        assert "USER" in codes
        assert "ADMIN" not in codes and "SUPER_ADMIN" not in codes
        # 配置默认不得硬编码 ADMIN/SUPER_ADMIN 角色 id
        assert not set(admin_ids) & set(settings.OAUTH_DEFAULT_ROLE_IDS)


# ── F-03 审计菜单权限码 ──────────────────────────────────────────
class TestF03AuditPermission:
    def test_audit_menu_permission_can_read(self, test_client: TestClient, auth_headers: dict) -> None:
        ent = _provision(test_client, auth_headers)
        uid, username, password = _mk_user(test_client, auth_headers)
        _grant_menu_permissions(test_client, auth_headers, uid, {"module_platform:enterprise:audit"})
        headers = _login(test_client, username, password)
        resp = test_client.get(f"/platform/enterprise/{ent['id']}/owner-audit", headers=headers)
        assert resp.status_code == 200, resp.text
        rows = resp.json()["data"]
        assert any(row["result"] == "success" for row in rows)

    def test_audit_without_permission_rejected(self, test_client: TestClient, auth_headers: dict) -> None:
        ent = _provision(test_client, auth_headers)
        _, username, password = _mk_user(test_client, auth_headers)
        headers = _login(test_client, username, password)
        resp = test_client.get(f"/platform/enterprise/{ent['id']}/owner-audit", headers=headers)
        assert resp.status_code == 403
