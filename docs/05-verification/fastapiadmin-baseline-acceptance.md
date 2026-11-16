# FastapiAdmin 原生技术基线验收记录

| 项目 | 内容 |
| :--- | :--- |
| 验收日期 | 2026-11-16 |
| 验收对象 | FastapiAdmin 原生技术基线第一步：源码导入、独立工程检查、真实运行与页面 |
| 上游来源 | `fastapiadmin/FastapiAdmin`，固定提交 `6828ba16a5c14fbce8479fe1b09b9e8d6ee540c2` |
| 验收结论 | **PASS（仅限 FastapiAdmin 原生基线）**，可进入后续底座加固；不代表业务模块、试点或全量上线验收通过 |
| 执行边界 | 未开发本项目业务模块，未创建 `tenant-web`，未修改 `vendor/`，未进行系统级安装或配置修改 |

## 一、源码与环境基线

| 项目 | 实测结果 |
| :--- | :--- |
| 后端映射 | `backend/` → `src/backend/`，保留 `main.py`、`create_app()`、`pyproject.toml`、`uv.lock`、迁移和测试 |
| 平台端映射 | `frontend/web/` → `src/platform-web/`，保留 `pnpm-lock.yaml` |
| 移动端映射 | `frontend/app/` → `src/mp-app/`，保留 `pnpm-lock.yaml` |
| 许可 | FastapiAdmin MIT 许可保留于 `src/backend/LICENSE` 及前端相应文件 |
| Python / uv | Python 3.12.12；uv、Python 与缓存均在仓库 `tmp/` 或工程 `.venv/` |
| Node / pnpm | Node 26.13.0；pnpm 使用仓库内工具与缓存 |
| Docker / Compose | Docker 29.7.2；Compose v5.5.0 |
| MySQL / Redis | MySQL 8.0.46；Redis 7.4.12 |
| 环境隔离 | `HOME`、XDG、临时目录、包缓存和浏览器均定向到仓库 `tmp/`；真实后端密钥文件不入库 |

## 二、自动化与构建验收

| 工程 | 检查 | 结果 |
| :--- | :--- | :--- |
| 后端 | `uv run --no-sync pytest -q` | **560 passed**，7 warnings，隔离 SQLite / 内存 Redis |
| 后端 | `uv tool run --from basedpyright basedpyright --pythonpath .venv/bin/python` | **0 errors、0 warnings、0 notes** |
| 后端 | `ruff check --no-fix .` | 177 项上游格式/风格债务，未作为本轮门禁进行全库改写 |
| 平台端 | 非修改式 ESLint / Prettier / Stylelint | 全部通过 |
| 平台端 | `pnpm ts:check` | 通过 |
| 平台端 | `pnpm test` | **4 个测试文件、44 个用例全部通过** |
| 平台端 | `pnpm build` | 通过 |
| 移动端 | `pnpm type-check`、`pnpm lint` | 全部通过 |
| 移动端 | `pnpm build:h5`、`pnpm build:mp-weixin` | 全部通过 |

既有警告保留记录：后端 Pydantic/OBS 与测试协程警告；移动端 Sass `@import` 弃用和 UnoCSS `failed to load icon "-"` 警告；Web 构建的 Node/Browserslist 警告。均未隐瞒为“零警告”。

## 三、真实运行验收

| 验收项 | 实测证据与结果 |
| :--- | :--- |
| 项目容器 | `wdgc-mysql`、`wdgc-redis` healthy；`wdgc-nginx` running |
| Docker 隔离 | 网络 `wdgc-supervision-evidence_default`；卷 `wdgc-mysql-data`、`wdgc-redis-data`；未操作其他项目对象 |
| 网络绑定 | MySQL `127.0.0.1:3307`、Redis `127.0.0.1:6380`、后端 `127.0.0.1:8001`、Web `127.0.0.1:5173`、Nginx `127.0.0.1:8080` |
| 数据库初始化 | `wdgc_supervision` 实际创建 44 张表；3 个原生用户、3 个原生角色、176 条有效菜单；迁移为 head，无模型漂移 |
| 健康接口 | 直连与 Nginx 均返回 200，`db_status=1`、`redis_status=1`、`code_exec_enabled=false` |
| OpenAPI | `/openapi.json` 返回 200，原生 API 共 246 个路径；`/docs` 返回 200 |
| 未认证访问 | 角色列表直连与 Nginx 均返回 401 |
| 超级管理员 | 在 `5173/platform/` 完成滑块验证、登录、动态菜单和首页加载 |
| 普通用户 | 在 `5173/platform/` 登录后仅显示首页/仪表盘；角色查询与创建均返回 403，未创建越权数据 |
| 管理员与代理 | 在 `8080/platform/` 完成滑块验证并进入管理员首页，动态菜单正常，无控制台错误或失败请求 |
| 退出登录 | 超级管理员、普通用户及移动端会话均调用真实 logout，返回 200 |
| 临时 CRUD | 创建唯一 `e2e_` 角色，MySQL 持久化和正确分页查询通过；调用删除接口后有效列表为 0 |
| CRUD 清理 | 临时角色 `is_deleted=1`，保留审计需要的历史行；有效 `e2e_` 角色数量为 0 |
| 本地资源 | Logo、Favicon、背景和头像使用本后端 `/api/v1/static/image/`；登录和首页不依赖外部 Iconify 服务 |
| 移动 H5 | `5180/app` 登录页稳定渲染；普通用户与管理员均完成真实滑块验证和登录 |
| 移动权限 | 普通用户首页不再请求无权接口，0 个 403；管理员数据卡片、统计、趋势和快捷入口正常，0 个 403 |
| 最终页面健康 | 修复后平台首页、角色页、Nginx 首页、移动 H5 均无页面异常、控制台错误或失败请求 |

## 四、验收中修复的问题

1. 修正后端 7 项应用层类型问题，并补充空时间、ARRAY 反射、空 Alembic head、DML rowcount、公告约束和调度时间回归覆盖。
2. 将平台第三方登录、通知、搜索、设置等图标切换到本地 Iconify 集合，消除外部图标服务依赖。
3. 清理 Vite 过期优化缓存并恢复动态路由加载；最终页面无 `Outdated Optimize Dep`。
4. 移动端首页按用户已有菜单权限同时裁剪请求和入口，未放宽后端权限或硬编码普通角色。
5. 修正 Nginx 回环访问、Host 转发、完整 `/api/v1` URI 与 WebSocket/HMR 头；Nginx host 网络仅限本机 Linux 联调。
6. 将必需的自动导入声明和 ESLint 配置纳入源码，保证干净检出可直接执行检查和构建。

## 五、运行入口与证据位置

- 后端：`http://127.0.0.1:8001/docs`
- 平台直连：`http://127.0.0.1:5173/platform/`
- Nginx 代理：`http://127.0.0.1:8080/platform/`
- 移动 H5：`http://127.0.0.1:5180/app`
- 后端日志：`tmp/runtime/logs/backend-dev.log`、`src/backend/logs/fastapiadmin.log`
- Web 日志：`tmp/runtime/logs/platform-web-dev-force.log`
- H5 日志：`tmp/runtime/logs/mp-app-h5-dev.log`
- 页面截图：本机被 Git 忽略的 `tmp/acceptance/`；这些截图是本次实测证据，不作为可生成的源码交付。

## 六、明确不在本次验收范围

- `tenant-web` 与 Figma Make 原型移交；
- 本项目业务模块、危大任务、证据链和法定履职流程；
- H-01～H-03、`TenantModelMixin`、`TenantCRUDBase`、项目级权限及双租户隔离；
- RuoYi-FastAPI 能力融合、OSS/WORM、AI 外部模型、微信开发者工具和真机；
- 生产部署、性能容量、法务合规及全量上线准入。

**下一步只进入原生底座加固阶段，不直接开始业务模块开发。**
