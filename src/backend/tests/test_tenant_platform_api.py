"""B0 平台域开通租户 API 验收：契约验收第 7/8 组。

7. 创建+绑定管理员、分页、冻结/解冻；冻结后该租户用户会话立即失效（H-02）；
   停用用户拒绝＋会话清理；超管禁止绑定；一人一租户。
8. 平台域 CRUD 无租户上下文正常工作；sys_* 原生行为不回归。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from conftest import _mock_redis, _mock_redis_store
from fastapi.testclient import TestClient

from app.core.security import decode_access_token


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/system/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


_ROLE_ID_CACHE: dict[str, int] = {}


def _default_role_id(client: TestClient, auth_headers: dict) -> int:
    """复用种子「普通用户」角色（data_scope=1 仅本人）。

    无角色用户会被 Permission 兜底条件限制为「仅本人创建的数据」，
    连 current/info 的自查都不可见（原生数据权限语义，与租户无关）。
    """
    if "default" not in _ROLE_ID_CACHE:
        resp = client.get(
            "/system/role/list",
            params={"page_no": 1, "page_size": 100, "name": "普通用户"},
            headers=auth_headers,
        )
        assert resp.json()["success"] is True, resp.text
        items = resp.json()["data"]["items"]
        assert items, "种子角色「普通用户」缺失"
        _ROLE_ID_CACHE["default"] = items[0]["id"]
    return _ROLE_ID_CACHE["default"]


def _mk_user(client: TestClient, auth_headers: dict) -> tuple[int, str, str]:
    username = f"b0_{uuid.uuid4().hex[:8]}"
    password = "Abc123!x"
    resp = client.post(
        "/system/user/create",
        json={"username": username, "name": username, "password": password, "role_ids": [_default_role_id(client, auth_headers)]},
        headers=auth_headers,
    )
    assert resp.json()["success"] is True, resp.text
    return resp.json()["data"]["id"], username, password


def _provision(client: TestClient, auth_headers: dict, *, admin_user_id: int | None = None) -> dict:
    payload: dict = {"name": f"企业-{uuid.uuid4().hex[:8]}"}
    if admin_user_id is not None:
        payload["admin_user_id"] = admin_user_id
    resp = client.post("/platform/enterprise/create", json=payload, headers=auth_headers)
    assert resp.status_code < 300, resp.text
    assert resp.json()["success"] is True, resp.text
    return resp.json()["data"]


def _token(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


def _session_keys(token: str) -> list[str]:
    session_id = decode_access_token(token).sub
    return [f"user_session:{session_id}", f"access_token:{session_id}", f"refresh_token:{session_id}"]


def _snapshot(token: str) -> dict:
    session_id = decode_access_token(token).sub
    return json.loads(_mock_redis_store[f"user_session:{session_id}"])


@pytest.fixture
def redis_keys_compat(monkeypatch: pytest.MonkeyPatch):
    """conftest mock redis 的 keys 仅支持 bytes 模式；补齐 str 模式（真实 redis decode_responses=True 行为）。"""

    async def _keys(pattern=None):
        if pattern is None:
            return list(_mock_redis_store.keys())
        text = pattern.decode() if isinstance(pattern, bytes) else str(pattern)
        prefix = text.replace("*", "")
        return [key for key in _mock_redis_store if str(key).startswith(prefix)]

    monkeypatch.setattr(_mock_redis, "keys", AsyncMock(side_effect=_keys))


class TestProvisionLifecycle:
    def test_provision_bind_freeze_unfreeze(self, test_client: TestClient, auth_headers: dict, redis_keys_compat) -> None:
        uid, username, password = _mk_user(test_client, auth_headers)
        ent = _provision(test_client, auth_headers, admin_user_id=uid)
        eid = ent["id"]
        assert ent["status"] == 1
        assert ent["enterprise_code"].startswith("ENT-")

        # 绑定管理员：is_enterprise_admin=True，携带用户账号信息
        bindings = test_client.get(f"/platform/enterprise/{eid}/bindings", headers=auth_headers).json()["data"]
        assert len(bindings) == 1
        assert bindings[0]["user_id"] == uid
        assert bindings[0]["is_enterprise_admin"] is True
        assert bindings[0]["username"] == username

        # 分页 + 名称搜索
        page = test_client.get(
            "/platform/enterprise/list",
            params={"page_no": 1, "page_size": 10, "name": ent["name"]},
            headers=auth_headers,
        ).json()["data"]
        assert page["total"] >= 1
        assert any(item["id"] == eid for item in page["items"])

        # 详情
        detail = test_client.get(f"/platform/enterprise/detail/{eid}", headers=auth_headers).json()["data"]
        assert detail["name"] == ent["name"]

        # 更新：status 不接受直改（只走 freeze/unfreeze）
        resp = test_client.put(f"/platform/enterprise/update/{eid}", json={"name": "改名企业", "status": 0}, headers=auth_headers)
        assert resp.json()["success"] is True, resp.text
        assert resp.json()["data"]["name"] == "改名企业"
        assert resp.json()["data"]["status"] == 1

        # 登录快照写入 tenant_id（经绑定解析）
        user_headers = _login(test_client, username, password)
        assert _snapshot(_token(user_headers))["tenant_id"] == eid
        # current/info 透传认证上下文的 tenant_id（完整模式＋轻量模式两个分支）
        info = test_client.get("/system/user/current/info", headers=user_headers).json()["data"]
        assert info["tenant_id"] == eid
        light = test_client.get("/system/user/current/info", params={"check_data_scope": "false"}, headers=user_headers).json()["data"]
        assert light["tenant_id"] == eid

        # 冻结：status=0，绑定用户会话三键立即清退，请求实时阻断（H-02）
        resp = test_client.post(f"/platform/enterprise/freeze/{eid}", headers=auth_headers)
        assert resp.json()["data"]["status"] == 0
        for key in _session_keys(_token(user_headers)):
            assert key not in _mock_redis_store, key
        assert test_client.get("/system/user/current/info", headers=user_headers).status_code == 401

        # 解冻：status=1，重新登录恢复
        resp = test_client.post(f"/platform/enterprise/unfreeze/{eid}", headers=auth_headers)
        assert resp.json()["data"]["status"] == 1
        renewed = _login(test_client, username, password)
        assert test_client.get("/system/user/current/info", headers=renewed).json()["data"]["tenant_id"] == eid

    def test_freeze_blocks_fresh_sessions(self, test_client: TestClient, auth_headers: dict, redis_keys_compat) -> None:
        """冻结后新登录的会话同样被 H-02 实时阻断并清退（登录流程本身不变）。"""
        uid, username, password = _mk_user(test_client, auth_headers)
        ent = _provision(test_client, auth_headers, admin_user_id=uid)
        assert test_client.post(f"/platform/enterprise/freeze/{ent['id']}", headers=auth_headers).json()["success"] is True

        headers = _login(test_client, username, password)  # 登录不校验企业状态（只加字段，不改登录流程）
        resp = test_client.get("/system/user/current/info", headers=headers)
        assert resp.status_code == 401
        assert "冻结" in resp.json()["msg"]
        for key in _session_keys(_token(headers)):
            assert key not in _mock_redis_store, key

    def test_disabled_user_rejected_and_session_purged(self, test_client: TestClient, auth_headers: dict, redis_keys_compat) -> None:
        uid, username, password = _mk_user(test_client, auth_headers)
        ent = _provision(test_client, auth_headers, admin_user_id=uid)
        headers = _login(test_client, username, password)

        # 停用用户（sys_user 原生批量状态接口）
        resp = test_client.patch("/system/user/status/batch", json={"ids": [uid], "status": 1}, headers=auth_headers)
        assert resp.json()["success"] is True, resp.text

        resp = test_client.get("/system/user/current/info", headers=headers)
        assert resp.status_code == 401
        assert "停用" in resp.json()["msg"]
        for key in _session_keys(_token(headers)):
            assert key not in _mock_redis_store, key

        # 重新启用后可再次登录（企业仍正常）
        assert test_client.patch("/system/user/status/batch", json={"ids": [uid], "status": 0}, headers=auth_headers).json()["success"] is True
        renewed = _login(test_client, username, password)
        assert test_client.get("/system/user/current/info", headers=renewed).status_code == 200
        assert _snapshot(_token(renewed))["tenant_id"] == ent["id"]


class TestBindingRules:
    def test_superadmin_cannot_bind(self, test_client: TestClient, auth_headers: dict) -> None:
        admin_id = test_client.get("/system/user/current/info", headers=auth_headers).json()["data"]["id"]
        name = f"超管绑定-{uuid.uuid4().hex[:8]}"
        resp = test_client.post("/platform/enterprise/create", json={"name": name, "admin_user_id": admin_id}, headers=auth_headers)
        assert resp.status_code == 403
        # 绑定失败整体回滚：企业不得落库
        page = test_client.get("/platform/enterprise/list", params={"name": name}, headers=auth_headers).json()["data"]
        assert page["total"] == 0

        ent = _provision(test_client, auth_headers)
        resp = test_client.post(f"/platform/enterprise/{ent['id']}/bindings", json={"user_id": admin_id}, headers=auth_headers)
        assert resp.status_code == 403
        assert test_client.get(f"/platform/enterprise/{ent['id']}/bindings", headers=auth_headers).json()["data"] == []

    def test_frozen_enterprise_rejects_binding(self, test_client: TestClient, auth_headers: dict) -> None:
        """评审 Major-1：冻结企业禁止绑定用户。"""
        uid, _, _ = _mk_user(test_client, auth_headers)
        ent = _provision(test_client, auth_headers)
        assert test_client.post(f"/platform/enterprise/freeze/{ent['id']}", headers=auth_headers).json()["data"]["status"] == 0
        resp = test_client.post(f"/platform/enterprise/{ent['id']}/bindings", json={"user_id": uid}, headers=auth_headers)
        assert resp.status_code == 403
        assert "冻结" in resp.json()["msg"]
        assert test_client.get(f"/platform/enterprise/{ent['id']}/bindings", headers=auth_headers).json()["data"] == []

    def test_one_user_one_tenant_and_unbind_rebind(self, test_client: TestClient, auth_headers: dict) -> None:
        uid, username, password = _mk_user(test_client, auth_headers)
        ent1 = _provision(test_client, auth_headers, admin_user_id=uid)
        ent2 = _provision(test_client, auth_headers)

        # 一人一租户：已绑定用户不能再绑他租户；同租户重复绑定亦拒绝
        resp = test_client.post(f"/platform/enterprise/{ent2['id']}/bindings", json={"user_id": uid}, headers=auth_headers)
        assert resp.status_code == 409
        resp = test_client.post(f"/platform/enterprise/{ent1['id']}/bindings", json={"user_id": uid}, headers=auth_headers)
        assert resp.status_code == 409

        headers = _login(test_client, username, password)
        assert _snapshot(_token(headers))["tenant_id"] == ent1["id"]

        # 解绑后快照 tenant_id 回到 None，可改绑他租户
        binding_id = test_client.get(f"/platform/enterprise/{ent1['id']}/bindings", headers=auth_headers).json()["data"][0]["id"]
        resp = test_client.delete(f"/platform/enterprise/bindings/{binding_id}", headers=auth_headers)
        assert resp.json()["success"] is True, resp.text
        assert test_client.get(f"/platform/enterprise/{ent1['id']}/bindings", headers=auth_headers).json()["data"] == []

        unbound = _login(test_client, username, password)
        assert _snapshot(_token(unbound))["tenant_id"] is None

        resp = test_client.post(f"/platform/enterprise/{ent2['id']}/bindings", json={"user_id": uid, "emp_no": "E001"}, headers=auth_headers)
        assert resp.status_code < 300, resp.text
        assert resp.json()["data"]["tenant_id"] == ent2["id"]
        rebound = _login(test_client, username, password)
        assert _snapshot(_token(rebound))["tenant_id"] == ent2["id"]

    def test_non_superadmin_forbidden(self, test_client: TestClient, auth_headers: dict) -> None:
        _, username, password = _mk_user(test_client, auth_headers)
        headers = _login(test_client, username, password)
        ent = _provision(test_client, auth_headers)

        assert test_client.post("/platform/enterprise/create", json={"name": "越权企业"}, headers=headers).status_code == 403
        assert test_client.get("/platform/enterprise/list", headers=headers).status_code == 403
        assert test_client.get(f"/platform/enterprise/detail/{ent['id']}", headers=headers).status_code == 403
        assert test_client.put(f"/platform/enterprise/update/{ent['id']}", json={"name": "越权改名"}, headers=headers).status_code == 403
        assert test_client.post(f"/platform/enterprise/freeze/{ent['id']}", headers=headers).status_code == 403
        assert test_client.post(f"/platform/enterprise/unfreeze/{ent['id']}", headers=headers).status_code == 403
        assert test_client.get(f"/platform/enterprise/{ent['id']}/bindings", headers=headers).status_code == 403
        assert test_client.post(f"/platform/enterprise/{ent['id']}/bindings", json={"user_id": 1}, headers=headers).status_code == 403
        assert test_client.delete("/platform/enterprise/bindings/1", headers=headers).status_code == 403

    def test_requires_auth(self, test_client: TestClient) -> None:
        assert test_client.get("/platform/enterprise/list").status_code == 401
        assert test_client.post("/platform/enterprise/create", json={"name": "匿名"}).status_code == 401


class TestPlatformDomainAndSysRegression:
    def test_platform_crud_without_tenant_context(self, test_client: TestClient, auth_headers: dict) -> None:
        """超管无租户绑定：上下文 tenant_id=None，平台域 CRUD 正常。"""
        info = test_client.get("/system/user/current/info", headers=auth_headers).json()["data"]
        assert info["tenant_id"] is None

        ent = _provision(test_client, auth_headers)
        credit_code = f"91{uuid.uuid4().hex[:16].upper()}"
        resp = test_client.put(f"/platform/enterprise/update/{ent['id']}", json={"credit_code": credit_code}, headers=auth_headers)
        assert resp.json()["data"]["credit_code"] == credit_code

        # 唯一约束：重复信用代码拒绝
        other = _provision(test_client, auth_headers)
        resp = test_client.put(f"/platform/enterprise/update/{other['id']}", json={"credit_code": credit_code}, headers=auth_headers)
        assert resp.status_code == 409

        # 显式 enterprise_code 开通 + 重复编码拒绝
        code = f"ENT-{uuid.uuid4().hex[:8].upper()}"
        resp = test_client.post("/platform/enterprise/create", json={"name": "编码企业", "enterprise_code": code}, headers=auth_headers)
        assert resp.status_code < 300
        assert resp.json()["data"]["enterprise_code"] == code
        resp = test_client.post("/platform/enterprise/create", json={"name": "编码重复", "enterprise_code": code}, headers=auth_headers)
        assert resp.status_code == 409

    def test_sys_native_behavior_no_regression(self, test_client: TestClient, auth_headers: dict) -> None:
        """sys_* 原生行为不回归：用户分页/详情/当前信息正常。"""
        resp = test_client.get("/system/user/list", params={"page_no": 1, "page_size": 5}, headers=auth_headers)
        assert resp.json()["success"] is True, resp.text
        assert resp.json()["data"]["total"] >= 1

        uid, username, _ = _mk_user(test_client, auth_headers)
        detail = test_client.get(f"/system/user/detail/{uid}", headers=auth_headers).json()["data"]
        assert detail["username"] == username
