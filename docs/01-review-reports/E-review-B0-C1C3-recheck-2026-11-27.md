# B0 / ADR-001 第三方快速复验报告（C1~C3 合并门禁 · 2026-11-27）

| 项目 | 内容 |
| :--- | :--- |
| 复验对象 | 分支 `origin/feat/b0-multi-tenant`（代码修复 `e9454b2`、复验提请 `32c03d0`，相对 E 复审基线 `44c1834` 共变更 10 个代码/测试文件，+553 / -17 行） |
| 复验依据 | [`E-review-B0-ADR001-2026-11-25.md`](./E-review-B0-ADR001-2026-11-25.md)（合并门禁 C1~C3 及建议同批项 F-03/F-04）；[`致第三方评审-C1C3修复复验提请-2026-11-26.md`](../06-collaboration/致第三方评审-C1C3修复复验提请-2026-11-26.md) |
| 复验方式 | 全量 Diff 静态代码走查＋全仓符号/配置引用核查＋Python AST/正则测试用例计数核验（本机 Docker 不可用，未本地复跑；运行时结果以技术侧实跑记录及 CI 为准） |
| **裁定结论** | **Approve（复验通过）—— 0 Blocker / 0 Major；正式放行 `feat/b0-multi-tenant` 合并 `main`** |

---

## 一、逐项核验结论

| 门禁项 | 复验结论 | 核验代码与测试证据（`origin/feat/b0-multi-tenant`） |
| :---: | :---: | :--- |
| **C1**<br>冻结租户缺省解析与平台专员自查保护 | **通过** | • `src/backend/app/core/dependencies.py`（L58-69, L251-268, L282-293）与 `src/backend/app/modules/platform/member/crud.py`（L35-72）：缺省 `X-Tenant-Id` 时，认证与登录快照同口径优先选取未冻结租户（`status==1`）的最早有效成员，全部冻结才回退拦截。<br>• 平台权限账号（`is_superuser` 或权限含 `module_platform:`）对 `/system/user/current/info` 的自查豁免已收紧为 **`selected_tenant_id is None`**；客户端显式 `X-Tenant-Id` 选中冻结租户时一律 `401` 并清退会话；平台域 M-04 兜底移交未受误伤。<br>• 回归测试 `src/backend/tests/test_e_review_2026_11_25.py`（4 例）：覆盖首租户冻结次租户可用、全冻清退、平台专员缺省自查保会话＋移交、平台专员显式选冻结租户 401 清退。 |
| **C2**<br>批量导入停用绕过现任 Owner 保护 | **通过** | • `src/backend/app/modules/system/user/service.py`（L529-538）：`_process_import_row` 在 `update_support` 且 `user_data["status"] == 1`（含全部非“正常”停用行）时接入 `_reject_if_current_owner([exists_user.id])` 预检，并在行级 `begin_nested()` SAVEPOINT 内执行更新＋`_assert_no_owner_after_write` 写后复核，失败仅回滚本行、不牵连同批其余行。<br>• 回归测试 3 例：单行拦截、混合行隔离（Owner 被拒且非 Owner 正常导入停用）、monkeypatch 跳过预检模拟写时竞态 SAVEPOINT 行级回滚。 |
| **C3**<br>第三方自动注册默认平台 ADMIN 风险 | **通过** | • `src/backend/app/config/setting.py`（L148）：移除硬编码 `[2]`，默认改为 `OAUTH_DEFAULT_ROLE_IDS: list[int] = []` 并附运维覆盖风险注释。<br>• `src/backend/app/modules/system/auth/service.py`（L74-93）：`auto_register_login_user` 缺省按 `RoleModel.code == "USER"` 解析种子普通用户角色（与 `create_login_account` 同口径）。全仓 `git grep` 确认 OAuth（`oauth_service.py:314`）与小程序（`wx_mini_service.py:278,309`）全部自动注册入口均经此函数，全仓无残留 `[2]` 配置。<br>• 回归测试 1 例：断言自动注册账号含 `USER`、不含 `ADMIN`/`SUPER_ADMIN`，且默认配置不包含管理员角色 ID。 |
| **F-03 / E2-04**<br>审计菜单权限码一致 | **通过** | • `src/backend/app/modules/platform/member/service.py`（L296-300, L419-421）：新增 `_require_audit_permission()`（超管或 `module_platform:enterprise:audit`），`list_audit` 已改用该函数，与前端按钮权限码对齐。<br>• 回归测试 2 例：授权菜单码返回 `200`、无权限返回 `403`。 |
| **F-04**<br>前端审计结果列与移交状态同步 | **通过** | • `src/platform-web/src/views/module_platform/enterprise/index.vue`（L247-254, L948-960）：审计表补 `result` 成功/失败列（`FaStatusTag`），`submitTransfer` 成功后同步置双方 `is_admin = false` 并更新 `is_owner` 标识。<br>• 前端回归 `src/platform-web/src/__tests__/enterprise-transfer-audit.spec.ts`（2 例）覆盖上述两项渲染与状态同步。 |

---

## 二、边界与回归核验

1. **红线与契约边界未突破**：`git diff --name-only 44c1834..origin/feat/b0-multi-tenant` 对 `src/backend/app/alembic/`、`model.py`、`schema.py` 均无变更；单持有人 Owner、租户隔离双防线、`sys_user_roles` 零污染及 `vendor/` 零修改均保持完好。
2. **既有测试调整核验**：`src/backend/tests/test_tenant_isolation.py`（L312-314）将脆弱全表计数改为显式按 `tenant_id` 计数，保持跨租户隔离断言意图，合理无风险。
3. **验证数字一致**：AST 与正则静态核验确认新增后端测试 `test_e_review_2026_11_25.py` 为 **10** 个用例、前端 `enterprise-transfer-audit.spec.ts` 为 **2** 个用例，与技术侧提请声明（后端 `658 passed / 7 skipped`、前端 Vitest `51/51`、`ts:check` 与 `build` 通过）完全吻合。

---

## 三、合并注意事项与后续排期（不阻塞合并 `main`）

1. **合并文档冲突保护（重要）**：
   - `main` 分支已于 2026-11-26/27 新增根目录 `AGENTS.md`（双仓协同规则，产品仅访问独立协同仓 `wdgc-supervision-evidence-collab`），并更新了 `README.md`、`docs/06-collaboration/team-collaboration-and-delivery-workflow.md`、`docs/06-collaboration/work-orders-2026-11-19.md` 与 `docs/06-collaboration/产品交接-租户身份与权限体系-2026-11-25.md`。
   - 将 `feat/b0-multi-tenant` 合并至 `main` 时，上述文档冲突**必须以 `main` 最新版本为准**，切勿被功能分支内的历史副本回退覆盖。
2. **后续排期（须由技术团队纳入节奏，协同推进走协同仓）**：
   - **头号前置卡点**：技术负责人尽快拍板 **D1 新契约结构决策单（D-1~D-6）**，结论沉淀至协同仓 `baseline/decisions/`，以解锁 **B1 / B6** 及产品 PRD 第二段；
   - **B0-收尾 / B1**：落地协同仓 `DEC-002`（4 入口在职单企业唯一校验＋并发防竞态、冻结光杆拥有者受控释放、`unfreeze` 禁解冻无主企业守卫＋原子「补设拥有者并解冻」、一期离职回原企业复职启用）及 [`E-review-B0-ADR001-2026-11-25.md`](./E-review-B0-ADR001-2026-11-25.md) 第四节安全/质量加固项；
   - **小程序生产前必修**：**C4**（微信手机号碰撞接管防护）；
   - **非阻塞补档**：**D2**（FastapiAdmin 选型 ADR）。
