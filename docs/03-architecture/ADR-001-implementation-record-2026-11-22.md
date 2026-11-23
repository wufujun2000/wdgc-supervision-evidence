# ADR-001 身份权限体系实施记录（2026-11-22）

> 基线：ADR-001（Accepted）＋迁移方案 `ADR-001-migration-plan-2026-11-22.md`。
> 分支：`feat/b0-multi-tenant`（B0~B0.2 成果保留：TenantCRUDBase 行级隔离、开通、冻结清退会话、platform-web 最小开通）。
> 范围纪律：未开展节点库/V/P/采集证据/D-1~D-6/PRD 生成器；vendor 未改；ADR-001 原文未改。

## 一、模型映射

| 旧（B0 过渡） | 新（ADR-001） | 说明 |
| :--- | :--- | :--- |
| `biz_tenant_user`＋`user_id` 单列唯一＋`is_enterprise_admin` | `biz_tenant_member`：`(tenant_id, user_id)` 唯一＋`status`（0正常/1停用） | 改名重建保留存量；停用不物理删除 |
| 无 | `biz_tenant_owner`：`tenant_id` 唯一＋`member_id`＋`version` | 单持有人记录，仅开通初始化/补设/移交变更；version 乐观锁防并发双 Owner |
| `is_enterprise_admin` 布尔 | `biz_tenant_admin`＋`biz_tenant_admin_permission` | 管理员 0~N 名，独立可委托权限授予；Owner 不得作为目标 |
| 无 | `biz_project`、`biz_project_member`(SZ/SP/SA)、`biz_project_member_hazard` | 项目级任命，`(project_id, member_id)` 唯一；SP 必须绑定危大集合 |
| 无 | `plat_owner_transfer_audit`（平台域） | 开通/补设/移交全路径审计（来源、操作人、原/新 Owner、原因、结果、时间） |

存量映射（Alembic `e5f6a7b8c9d0`）：`is_enterprise_admin=True` → Admin＋全部 delegable 权限；每租户最早 admin 成员 → 初始 Owner（version=1）。
移交/审计按钮菜单（Alembic `f6a7b8c9d0e1`）与 `sql/sys_menu.json` 种子双轨一致。

## 二、权限目录与引擎（`app/core/tenant_permission.py`）

- delegable：`tenant_member_manage`、`tenant_admin_manage`、`project_manage`、`project_member_assign`。
- owner_only：`tenant_owner_transfer`（平台默认仅 SUPERADMIN，预留 `platform:owner:transfer`）。
- `require_permission(code)`：当前有效 Owner 默认通过；Admin 按授权；`require_owner()` 只认 `biz_tenant_owner` 有效记录，Admin 全权限也拒绝。
- `require_project_role(project_id, roles)`：按当前项目有效任命；Owner/Admin 未任命同样 403（法定签署场景）。
- `require_hazard_scope(pm, code)`：SZ 全部；SP 按 `biz_project_member_hazard`；SA 由业务层按本人任务另行过滤。
- 授权不得超过操作者自身可转授范围（`get_delegable_scope`），owner_only 永不可委托。
- 严禁租户/项目角色写入 `sys_user_roles`；`sys_user.is_superuser` 禁止加入租户成员。

## 三、认证与上下文

`_authenticate` 经 `biz_tenant_member`（status=0）解析 `tenant_id + member_id`；`X-Tenant-Id` 仅作选择、归属必校验，缺省最早有效成员；成员停用/租户冻结即清退会话（401）；登录快照同样按最早有效成员写入 `tenant_id`。

## 四、所有权移交（平台/租户共用 `execute_owner_transfer`）

- 校验：发起方（平台专门权限/当前 Owner）、目标为本租户有效成员且非当前 Owner、原因必填、confirm=true；租户侧冻结禁止（认证层 401），平台侧保留处置。
- 原子：`UPDATE biz_tenant_owner SET member_id=:new, version=version+1 WHERE tenant_id AND version=:v`，rowcount≠1 → 409；无 Owner 路径经 tenant_id 唯一约束兜底。
- 同事务写审计（append-only；拒绝事件由 OperationLogRoute 请求级日志覆盖）；双方旧会话三键清退；原 Owner 不自动保留 Admin；项目任命与历史归属不变。

## 五、API 清单

平台域（/platform/enterprise，仅超管或平台专门权限）：
- `POST /create`（管理员必填，原子企业＋账号＋成员＋Owner＋审计）；
- `GET/POST /{id}/members`、`POST /members/{member_id}/disable`、`POST /{id}/owner/transfer`、`GET /{id}/owner-audit`。

租户域（/tenant，经 TenantCRUDBase＋权限引擎）：
- members：`POST /members`、`GET /members/list`、`POST /members/{member_id}/disable`（Owner 目标拒绝）；
- admins：`POST /admins`、`PUT /admins/{member_id}/permissions`、`DELETE /admins/{member_id}`；
- `POST /owner/transfer`（require_owner）、`GET /owner-audit`（require_owner）；
- projects：`POST /projects`、`GET /projects/list`、`POST /projects/{id}/members`、`GET /projects/{id}/members`（require_project_role）、`POST /projects/{id}/members/{appointment_id}/disable`。

platform-web：成员管理（Owner/Admin/状态标识、停用、移交记录）、平台移交弹窗（目标成员＋原因＋二次确认）、开通移除「暂不指定」。

## 六、验证（最终数字以提交说明为准）

- 既有 B0 测试适配（成员模型/端点/语义）后全绿；
- 新增 `tests/test_tenant_adr001.py`：Owner 唯一与不可分配、Admin 全权限仍被 require_owner 拒绝、Admin 不得停用/降权 Owner、平台有/无权限移交、冻结规则、并发移交（asyncio.gather 仅一成、version=2）、多租户成员与 X-Tenant-Id、项目角色独立与 SP 危大范围、成员停用与历史保留；
- 真实 MySQL 迁移（dev 自动迁移产生的空表清理后 upgrade head）＋关键流程 E2E（UI＋API）证据。

## 七、实施中修正的缺陷

1. `create_login_account` 返回二元组，租户成员创建处未拆包（已修）。
2. 成员/任命输出的 `member.user` 关系懒加载在异步会话中 MissingGreenlet，改为显式查询/预加载（已修）。
3. 冻结企业租户侧移交在认证层即 401（H-02），服务层冻结校验作纵深防御保留。
4. dev 自动迁移对新增模型产生空表与额外 head，已清理后以手写迁移为唯一事实来源。

## 八、独立评审（Slow-2）与修复闭环（2026-11-23）

评审报告 `local://adr001-review.md`：REQUEST_CHANGES（1 blocker＋14 major＋6 minor＋1 nit），逐条修复：

- **B-01**：移交同事务清除原/新 Owner 的普通 Admin 记录与权限（text() 裸 SQL，不受操作者租户钩子过滤）；迁移初始 Owner 不再写普通 Admin；补 Admin→Owner→第三人测试。
- **M-01**：revoke_admin 输出查询移到 commit 之前；补正常撤销成功测试。
- **M-02**：移交目标 JOIN sys_user 校验账号 status/is_deleted/is_superuser；开通/绑定入口同步校验停用账号。
- **M-03**：移交先对目标成员行锁（no-op UPDATE）＋锁后重查；停用与移交固定顺序协调；补 transfer-vs-disable 并发测试（不产生已停用 Owner）。
- **M-04**：Owner 读写改 text() 裸 SQL（平台跨租户移交不受操作者租户上下文/钩子影响）；冻结校验按域放行（平台域不被操作者所属冻结租户误拦，系统/租户域保持 H-02）；前后端权限标识统一为 `module_platform:enterprise:transfer`；候选成员读取对专门权限开放；补非超管专门权限跨租户＋冻结正向测试。
- **M-05**：旧 `platform/tenant_user` 运行模块从提交删除（fresh create_all 不再创建 biz_tenant_user）；补元数据断言。
- **M-06**：六张新表补 `ix_<table>_tenant_id`；legacy 重建 audit=True；迁移 roundtrip 索引对照测试。
- **M-07**：downgrade 在 DDL 前对多租户同账号成员明确拒绝（不可逆指引）；停用成员回滚映射为 legacy 软删；补冲突/停用 roundtrip。
- **M-08**：Boolean 全部 TRUE/FALSE 字面量（MySQL/PG/SQLite）；补三方言编译/离线渲染验证。
- **M-09**：初始 Owner 取每租户最早有效成员（不限 admin）；无有效成员保持无 Owner（平台补设）；补四组存量映射测试。
- **M-10**：跨账号/种子角色查询改系统级精确匹配（db.get/直查，不经平台 DATA_SCOPE_SELF）；成员列表消费预加载 user；补绑定他人/姓名可见/新账号 USER 角色测试。
- **M-11**：失败/冲突移交经独立短事务写 result=failed 结构化审计；补失败审计测试。
- **M-12**：原生 update(status=1)/batch/delete 统一检查当前 Owner，命中要求先移交；补三入口拒绝＋移交后可停用测试。
- **M-13**：PUT /tenant/admins/{id}/permissions 增加 Owner 目标拒绝；补测试。
- **M-14**：upgrade/downgrade 显式 ID 搬迁后同步 PostgreSQL 序列（空表妥善处理）；补迁移后新增行测试。
- **m-01**：非超管合法载荷开通仍断言 403（保留 422 校验用例）。
- **m-02**：移交原因 strip 后非空校验。
- **m-03**：菜单迁移以确定性 UUID 标识所有权，预存异 UUID 行显式冲突、downgrade 仅删本迁移行。
- **m-04**：移交前双方均建立会话，移交后分别断言三键失效。
- **m-05**：EXPIRE_ON_COMMIT=True 下 commit 前缓存标量/生成 Schema；补配置测试。
- **m-06**：补卸任后 403 且历史保留、错配 404、跨租户任命拒绝、未任命全权限 Admin 403、SA 危大 403。
- **n-01**：删除重复 `_std_indexes` 定义。

修复后验证：迁移测试 12 passed；真实 MySQL downgrade/upgrade roundtrip 映射正确（初始 Owner 无 Admin 残留）；E2E 17/17；全量套件结果以最终提交说明为准。
