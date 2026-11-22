# ADR-001 现状差异与迁移方案（2026-11-22 · 技术负责人）

> 决策基线：ADR-001（Accepted）。本方案只做身份权限迁移，不开展节点库/V/P/采集证据等新契约业务。
> 实施分支：`feat/b0-multi-tenant`（续 B0~B0.2）。

## 一、现状差异（B0 过渡模型 → ADR-001）

| 维度 | 现状（B0~B0.2） | ADR-001 目标 |
| :--- | :--- | :--- |
| 成员模型 | `biz_tenant_user`，`user_id` 单列唯一（一人一租户） | `biz_tenant_member`，`(tenant_id, user_id)` 唯一；多租户成员由业务规则控制 |
| 企业管理员 | `is_enterprise_admin` 布尔 | `TENANT_ADMIN`＋独立可委托权限授予（0~N 名） |
| 企业拥有者 | 无 | `biz_tenant_owner` 单持有人记录（tenant_id 唯一＋version 并发控制），不进普通授权列表 |
| 项目体系 | 无 | `biz_project` / `biz_project_member`(SZ/SP/SA) / `biz_project_member_hazard`（SP 危大集合） |
| 权限校验 | 仅超管/绑定检查 | `require_permission`（Owner 默认通过，Admin 按授权）＋`require_owner`（只认有效所有权记录）＋项目任命门控 |
| 所有权移交 | 无 | 平台＋租户两路径；版本/行锁防双 Owner；二次确认＋审计＋双方会话失效 |
| 开通语义 | 管理员可空（可开空企业） | 原子创建首名成员＋唯一 Owner，失败整体回滚；移除「暂不指定」 |
| 成员解绑 | 物理删除 | 停用（status），保留历史归属，禁止物理删除 |
| 租户上下文 | `tenant_id` | `tenant_id + member_id`；`X-Tenant-Id` 仅作选择，服务端校验成员归属 |

## 二、数据模型与迁移（单 Alembic revision）

1. `biz_tenant_user` → `biz_tenant_member`：改名（存量保留），加 `status`（0正常/1停用），唯一约束由 `user_id` 改为 `(tenant_id, user_id)`；`is_enterprise_admin` 数据迁出后弃用该列。
2. 新表 `biz_tenant_owner`：`tenant_id` 主键、`member_id` 唯一（防一成员多租户 Owner 由业务校验）、`version` 乐观锁；含审计字段。
3. 新表 `biz_tenant_admin`：`tenant_id`、`member_id`，`(tenant_id, member_id)` 唯一。
4. 新表 `biz_tenant_admin_permission`：`tenant_id`、`admin_id`、`permission_code`，`(admin_id, permission_code)` 唯一。
5. 新表 `biz_project`：`tenant_id`、`project_code`（租户内唯一）、`name`、`status`、`description`。
6. 新表 `biz_project_member`：`tenant_id`、`project_id`、`member_id`、`role_code`(SZ/SP/SA)、`status`，`(project_id, member_id)` 唯一（每成员每项目一条有效任命）。
7. 新表 `biz_project_member_hazard`：`tenant_id`、`project_member_id`、`hazard_code`(01~12)，`(project_member_id, hazard_code)` 唯一。
8. 新表 `plat_owner_transfer_audit`（平台域）：来源（platform/tenant）、操作人 user_id、tenant_id、原/新 Owner member_id、原因、结果、时间。
9. 存量数据映射：`is_enterprise_admin=True` → Admin＋全部 delegable 权限；每租户最早 admin 成员 → 初始 Owner（写 version=1）；无成员租户保持无 Owner（不可用，经平台补绑首名成员自动补 Owner）。
10. 所有 biz_* 新表继承 `TenantModelMixin`（tenant_id Integer FK RESTRICT），纳入行级隔离与跨租户测试。

## 三、权限目录（代码静态、平台受控变更）

- 角色模板：`TENANT_OWNER`（不可分配）、`TENANT_ADMIN`、`SZ`/`SP`/`SA`（项目模板）。
- 可委托权限（delegable=True）：`tenant_member_manage`、`tenant_admin_manage`、`project_manage`、`project_member_assign`。
- 所有权专属（owner_only=True）：`tenant_owner_transfer`（平台默认仅 SUPERADMIN；其它平台账号须专门权限，预留 `platform:owner:transfer`，不建菜单）。
- 严禁把租户/项目角色写入 `sys_user_roles`；`sys_role/sys_user_roles` 只承载平台域。

## 四、认证与权限引擎

- `_authenticate` 改经 `biz_tenant_member`（status=0 有效）解析 `tenant_id + member_id`；`X-Tenant-Id` 提供时校验归属，缺省取最早有效成员；成员停用/租户冻结→清退会话并 401。
- `require_permission(code)`：当前 Owner 直接通过；否则查 Admin 记录＋权限包含；无则 403。
- `require_owner()`：只认 `biz_tenant_owner` 有效记录，Admin 全权限也拒绝。
- `require_project_role(project_id, roles)`：按当前项目有效任命（status=0）判定；Owner/Admin 未任命一样 403（法定签署场景）。
- `require_hazard_scope(project_member, hazard_code)`：SZ 全部危大；SP 命中 `biz_project_member_hazard` 才通过；SA 仅本人范围（一期按本人任务语义预留校验点，不实现业务过滤）。

## 五、所有权移交（平台/租户共用原子函数）

1. 校验：发起方（平台专门权限/当前 Owner）、目标为本租户有效成员且非当前 Owner、二次确认（confirm=true）、原因必填；租户侧冻结禁止，平台侧保留处置。
2. 原子更新：`UPDATE biz_tenant_owner SET member_id=:new, version=version+1 WHERE tenant_id=:t AND version=:v`，rowcount≠1 → 409「所有权已变更，请刷新」（防并发双/零 Owner）。
3. 同事务写 `plat_owner_transfer_audit`（成功/失败均记录结果）。
4. 双方旧会话清退（沿用 freeze 三键清退），新权限立即生效；原 Owner 不自动保留 Admin；双方项目任命与历史归属不变。
5. 平台操作人不因此成为 Owner（无成员记录断言）。

## 六、API 与前端

平台域（/platform/enterprise）：
- `POST /{id}/owner/transfer`（专门权限；冻结可执行）。
- `GET /{id}/members`（替代 bindings，含 owner/admin 标识）、`POST /{id}/members`（补绑；无 Owner 租户首名成员自动 Owner＋审计）。
- `DELETE /bindings/{id}` → 成员停用（不再物理删除）。
- `GET /{id}/owner-audit`（移交审计只读）。
- 开通 create：管理员必填，原子「企业＋账号＋成员＋Owner＋审计」。

租户域（新 /api/v1/tenant，全部经 TenantCRUDBase/权限引擎）：
- members：创建/绑定、列表、`/{member_id}/disable`（Owner 目标一律拒绝）。
- admins：设置＋权限集、改权限（不超操作者范围且 delegable）、撤销；当前 Owner 不得作为目标。
- `POST /tenant/owner/transfer`（require_owner；冻结禁止）。
- `GET /tenant/owner-audit`（require_owner）。
- projects：创建（project_manage）、列表（有效成员）、`/{id}/members` 任命（project_member_assign，SP 必须 hazard、SZ/SA 禁 hazard）、`/{id}/members` 读取（require_project_role 任一）、`/{id}/members/{pm_id}/disable`（保留历史）。

platform-web：绑定区改成员＋Owner/Admin 标识、平台移交弹窗（目标成员＋原因＋二次确认）、开通移除「暂不指定」。租户侧不建新前端，API 级验证，最终交互等 PRD。

## 七、验证

- B0 既有测试按新契约适配后全绿（一人一租户→(tenant_id,user_id)、bindings→members、unbind→停用、开通必填管理员）。
- 新增：Owner 唯一与不可分配、Admin 全权限仍被 require_owner 拒绝、Admin 不得停用/降权 Owner、平台有/无权限移交、租户侧冻结禁止、并发移交（asyncio.gather 双发起仅一成）、移交后会话失效/项目任命不变、多租户成员隔离、项目角色独立与 SP 危大范围。
- 真实 MySQL 迁移（存量 biz_tenant_user 数据映射）＋关键流程 E2E（UI/真实服务），不只报单元测试。

## 八、文档同步

总体架构 §3.1（sys_user 仅供平台人员/biz_tenant_user）与 §4.2（is_enterprise_admin）标注 ADR-001 替代并更新表清单；OpenAPI 随路由自动更新；另附本实施记录。不改 ADR-001 原文、不改产品交接说明、不覆盖他人改动。
