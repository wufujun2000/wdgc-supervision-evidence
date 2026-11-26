# 危大工程监理履职证据链系统

危大工程监理履职证据链系统面向监理企业、项目总监、专业监理工程师和现场监理人员，用于支撑危大工程履职过程中的任务驱动采集、现场影像取证、监理审核、隐患整改、停复工、验收签认、档案归集与证据导出。

系统重点解决多企业与多项目并行情况下的租户隔离、项目级权限、原始证据保护、弱网离线采集、履职过程追踪及证据完整性核验问题。

## 一、当前项目状态

当前处于**PRD v2.4 需求基线已冻结、文档与数据基线已建立、FastapiAdmin 原生技术基线已通过本机运行验收**阶段。产品原型团队以 [`docs/02-prd/PRD_v2.4_基线冻结版.md`](docs/02-prd/PRD_v2.4_基线冻结版.md) 为当前需求基线继续原型开发；冻结后的需求变更走协作规则中的受控变更流程。

`src/backend/`、`src/platform-web/`、`src/mp-app/` 已分别由固定提交 `6828ba16a5c14fbce8479fe1b09b9e8d6ee540c2` 的 `backend/`、`frontend/web/`、`frontend/app/` 完整映射导入，保留上游依赖锁文件、测试、配置模板及启动链。当前仅包含上游原生能力，尚未实现本项目业务模块；`tenant-web` 仍等待 Figma Make，未创建。

FastapiAdmin 原生基线已完成自动化测试、真实 MySQL/Redis、接口、登录、权限、CRUD、Nginx 和移动 H5 验收；实测证据与范围见 [`docs/05-verification/fastapiadmin-baseline-acceptance.md`](docs/05-verification/fastapiadmin-baseline-acceptance.md)。该结论不代表本项目业务、试点或上线验收通过。

当前只开展 FastapiAdmin 原生技术基线搭建与验收，暂不进入业务模块开发；产品原型、业务校审和专项 PoC 可按协作规则独立并行。全量上线仍需完成源数据业务校审、真机与云服务 PoC、行为验收及法务合规复核，具体状态见 `docs/04-baseline-data/validation_report.json`。

## 二、目标业务能力

- 平台端、租户工作台和微信现场采集端分离；
- 企业、项目、危大类别和人员角色的多维权限控制；
- 按危大实体、楼栋、部位和施工批次生成任务发生实例；
- 现场相机采集、离线队列、断点续传和元数据绑定；
- 原始帧摘要与归档文件摘要分离，支持全文件完整性核验；
- 影像审核、隐患整改、严重隐患停工与报告、复工及验收闭环；
- 监理表单、影像和业务单据关联，形成可调阅、可导出的履职证据包。

## 三、开发 Agent 阅读入口

新介入的开发 Agent 不应从历史评审报告中推测当前需求，应按以下顺序阅读：

| 顺序 | 文件                                                                                                                                     | 用途                                             |
| :--- | :--------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------- |
| 1    | [`docs/README.md`](docs/README.md)                                                                                                       | 完整文档地图、当前版本、逐文件说明和角色阅读路线 |
| 2    | [`docs/02-prd/PRD_v2.4_基线冻结版.md`](docs/02-prd/PRD_v2.4_基线冻结版.md)                                                               | 当前产品需求、角色、功能、数据规则及验收要求     |
| 3    | [`docs/03-architecture/system-architecture-design.md`](docs/03-architecture/system-architecture-design.md)                               | 技术选型、工程拓扑、多租户与证据链架构           |
| 4    | [`docs/06-collaboration/team-collaboration-and-delivery-workflow.md`](docs/06-collaboration/team-collaboration-and-delivery-workflow.md) | 产品、技术、测试和专家评审团队的协作规则         |
| 5    | [`docs/04-baseline-data/validation_report.json`](docs/04-baseline-data/validation_report.json)                                           | 当前结构、业务校审和开发准入状态                 |

**所有文档相关说明统一查看 [`docs/README.md`](docs/README.md)。根 README 只承担项目入口和工程导航职责。**

## 四、仓库结构

```text
wdgc-supervision-evidence/
├── README.md                         # 项目说明与开发 Agent 总入口
├── src/                              # 应用工程（自研代码）
│   ├── backend/                      # FastAPI 后端工程（Python 3.12 + uv）
│   │   ├── pyproject.toml / uv.lock  # 上游依赖声明与锁文件
│   │   ├── main.py                   # 真实 CLI / Uvicorn 启动入口
│   │   ├── app/                      # FastapiAdmin 原生后端源码
│   │   └── tests/                    # 隔离 SQLite / 内存 Redis 测试
│   ├── platform-web/                 # FastapiAdmin 管理端（Vue3 + TS，端口 5173）
│   └── mp-app/                       # FastapiAdmin 移动端（UniApp + TS）
# tenant-web 等待 Figma Make，尚未创建
├── vendor/                           # 上游基线源码（本地克隆，不纳入版本控制）
│   ├── FastapiAdmin/                 # 后端主骨架基线（固定提交 6828ba1）
│   └── RuoYi-FastAPI/                # 文件治理、防重放、多模态 SSE 参考基线（固定提交 7f7c66d）
├── deploy/
│   └── dev/                          # 项目级 MySQL/Redis/Nginx 隔离环境
├── docs/                             # 需求、架构、数据、验证与评审资料
│   ├── README.md                     # 文档总目录和逐文件说明
│   ├── 00-source-materials/          # 原始研究报告、附录和履约模板
│   ├── 01-review-reports/            # 历次第三方审查与复审记录
│   ├── 02-prd/                       # 当前及历史 PRD
│   ├── 03-architecture/              # 总体架构与框架选型依据
│   ├── 04-baseline-data/             # 机器可读基线及校验报告
│   ├── 05-verification/              # 业务校审与技术 PoC 工作清单
│   └── 06-collaboration/             # 跨团队协作与交付规则
├── scripts/                          # 基线生成、PRD 生成和一致性校验脚本
└── tests/                            # 跨端契约、集成与验收测试（随开发落地）
```

自研代码统一写入 `src/`：`src/backend/` 为后端工程，`src/platform-web/`、`src/tenant-web/`、`src/mp-app/` 为三端前端工程。上游开源框架的基线源码统一放在 `vendor/`，仅作比对与移植参考，禁止直接修改；`vendor/` 为本地克隆、不纳入版本控制，获取方式见 4.1。不得仅将代码放入文档目录。

### 4.1 上游基线源码（vendor/）

首次检出仓库后，在仓库根目录执行：

```bash
git clone https://github.com/fastapiadmin/FastapiAdmin.git vendor/FastapiAdmin
git clone https://github.com/insistence/RuoYi-FastAPI.git vendor/RuoYi-FastAPI
```

网络较慢时可加 `--depth 1`。架构文档与 PRD 锁定的固定基线提交：

| 上游仓库        | 固定提交                                   | 用途                                                   |
| :-------------- | :----------------------------------------- | :----------------------------------------------------- |
| `FastapiAdmin`  | `6828ba16a5c14fbce8479fe1b09b9e8d6ee540c2` | 后端主骨架（RBAC、代码生成、系统监控、fastapp 移动端） |
| `RuoYi-FastAPI` | `7f7c66d373b6b344899961a42249ff51285cd865` | 文件治理、接口防重放签名、Agno 多模态 SSE 参考         |

克隆到最新主干后如需对齐固定提交：

```bash
git -C vendor/FastapiAdmin fetch origin 6828ba16a5c14fbce8479fe1b09b9e8d6ee540c2
git -C vendor/FastapiAdmin checkout 6828ba16a5c14fbce8479fe1b09b9e8d6ee540c2
git -C vendor/RuoYi-FastAPI checkout 7f7c66d373b6b344899961a42249ff51285cd865
```

### 4.2 原生技术基线命令

本机工具、Python 和缓存位于被 Git 忽略的 `tmp/`；三套工程的依赖分别位于各自的 `.venv/` 或 `node_modules/`。在仓库根目录使用本次安装的本地工具：

```bash
export REPO_ROOT="$PWD"
export PATH="$REPO_ROOT/tmp/bin:$REPO_ROOT/tmp/node-tools/node_modules/.bin:$PATH"
export HOME="$REPO_ROOT/tmp/home"
export XDG_CACHE_HOME="$REPO_ROOT/tmp/xdg-cache"
export XDG_CONFIG_HOME="$REPO_ROOT/tmp/xdg-config"
export XDG_DATA_HOME="$REPO_ROOT/tmp/xdg-data"
export XDG_STATE_HOME="$REPO_ROOT/tmp/xdg-state"
export TMPDIR="$REPO_ROOT/tmp/tmp"
export TEMP="$TMPDIR"
export TMP="$TMPDIR"
export UV_CACHE_DIR="$REPO_ROOT/tmp/uv-cache"
export UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
export UV_PYTHON_INSTALL_DIR="$REPO_ROOT/tmp/python"
export UV_PYTHON_BIN_DIR="$REPO_ROOT/tmp/bin"
export UV_TOOL_DIR="$REPO_ROOT/tmp/uv-tools"
export UV_TOOL_BIN_DIR="$REPO_ROOT/tmp/bin"
export PNPM_HOME="$REPO_ROOT/tmp/pnpm-home"
export COREPACK_HOME="$REPO_ROOT/tmp/corepack"
export NPM_CONFIG_CACHE="$REPO_ROOT/tmp/npm-cache"
export npm_config_cache="$NPM_CONFIG_CACHE"
export HUSKY=0
export PYTHONDONTWRITEBYTECODE=1
export NPM_CONFIG_UPDATE_NOTIFIER=false
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$TMPDIR" "$UV_TOOL_DIR" "$PNPM_HOME" "$COREPACK_HOME"

uv python install 3.12
cd src/backend
uv sync --extra mysql
uv run --no-sync pytest -q
uv run --no-sync ruff check --no-fix .
uv tool run --from basedpyright basedpyright --pythonpath .venv/bin/python

cd ../platform-web
pnpm install --frozen-lockfile --store-dir "$REPO_ROOT/tmp/pnpm-store"
pnpm ts:check
pnpm test
pnpm build

cd ../mp-app
pnpm install --frozen-lockfile --store-dir "$REPO_ROOT/tmp/pnpm-store"
pnpm type-check
pnpm build:h5
pnpm build:mp-weixin
```

后端本地配置为 `src/backend/env/.env.dev`，该文件及真实密钥被 Git 忽略；前端公共 `.env` 与开发配置可复现提交。Web 直接开发地址为 `http://127.0.0.1:5173/platform/`，后端端口为 `8001`。移动端仓库不保存真实微信 appid，其 `.env.production` 仅含项目域名占位符，部署前必须用被忽略的 `.env.production.local` 配置本项目 API/WSS 地址。上游 MIT 许可已原样保留到 `src/backend/LICENSE`；初始化种子中的 Logo、Favicon、登录背景和头像均使用本后端的 `/api/v1/static/image/` 相对路径，不依赖上游演示服务。

需要真实 MySQL/Redis 联调时，先在具备 Docker 的环境执行 `docker compose -f deploy/dev/docker-compose.yml up -d mysql redis`，再按 `src/backend/README.md` 启动后端；不要在服务未就绪时把上游 SQLite 测试结果当作 MySQL 验收。MySQL `3307` 与 Redis `6380` 只绑定 `127.0.0.1`，Compose 顶层项目名为 `wdgc-supervision-evidence`，其默认网络与其他目录隔离。可选 Nginx 使用 `--profile with-nginx`，**仅用于本机 Linux 联调**：容器采用 `network_mode: host`，直接监听 `127.0.0.1:8080`，API、平台和租户上游分别指向回环地址 `8001`、`5173`、`5174`，后端仍只监听回环地址，不开放宿主防火墙。`/api/` 保留完整 URI，API 与平台代理已配置 HTTP 1.1、WebSocket Upgrade 及转发头，用于 AI WebSocket 和 Vite HMR。该 host 网络模式不是生产配置；本次已在用户明确授权后完成 Nginx 页面、API 与管理员登录实测。

### 4.3 本次工程检查记录

- 后端：Python 3.12.12 与 `uv sync --extra mysql` 已完成；`uv run --no-sync pytest -q` 为 **560 passed、7 warnings**（隔离 SQLite / 内存 Redis）；`uv tool run --from basedpyright basedpyright --pythonpath .venv/bin/python` 修复应用层 7 项真实类型问题并为 tests 的 Mock 定向放宽两条规则后为 **0 errors、0 warnings**；`uv run --no-sync ruff check --no-fix .` 此前发现的上游 **177 个错误**仍作为质量债务记录，未开展全库 Ruff 修复。
- 平台端：`pnpm install --frozen-lockfile`、非修改式 ESLint / Prettier / Stylelint、`pnpm ts:check`、`pnpm test`（4 个测试文件、44 个用例）和 `pnpm build` 均已通过。干净检出的首次类型检查曾因自动导入声明缺失失败，现已将 Vite 生成的两份 d.ts 纳入源码后复验通过。仅对报告的 16 个文件应用 Prettier，并修复 10 个文件的 20 项 Stylelint 属性顺序、空行和冗余 `word-break` 问题；这些差异为格式与样式规则修复，不含业务功能变更。
- 移动端：`pnpm install --frozen-lockfile`、`pnpm type-check`、`pnpm lint`、`pnpm build:h5` 与 `pnpm build:mp-weixin` 均已通过；Husky 安装路径已按 `src/mp-app` 映射修正，指定文件的 lint 问题已做无行为变更修复。构建存在上游 Sass `@import` 弃用及 UnoCSS `failed to load icon "-"` 警告，命令退出码为 0；真实微信开发者工具与真机尚未验证。

- 真实运行：MySQL/Redis/Nginx 容器、44 张表初始化、246 个 OpenAPI 路径、三类账号登录、角色 CRUD 与清理、401/403 权限拒绝、Nginx 代理和移动 H5 均由主 Agent 独立实测通过；详见 [FastapiAdmin 原生技术基线验收记录](docs/05-verification/fastapiadmin-baseline-acceptance.md)。

以上结论仅适用于 FastapiAdmin 原生技术基线，不代表业务模块、生产部署、真机 PoC 或全量上线验收完成。

## 五、生成与校验

当前脚本仅依赖 Python 3.10+ 标准库：

```bash
python3 scripts/generate_baseline_data.py
python3 scripts/generate_prd.py
python3 scripts/validate_prd_consistency.py
```

生成结果包括：

- `docs/04-baseline-data/hazard_nodes_seed.json`：347 条基线记录及唯一节点身份；
- `docs/04-baseline-data/metadata_and_forms_dictionary.json`：标准字段、内部扩展和表单映射；
- `docs/04-baseline-data/validation_report.json`：结构与业务准入状态；
- `docs/04-baseline-data/prd_consistency_report.json`：实际一致性检查数量与结果（以 `checks_passed/checks_total` 为准）；
- `docs/02-prd/PRD_v2.4_基线冻结版.md`：由生成器输出的当前 PRD（v2.4 基线冻结版，技术基线搭建与前端原型开发的当前需求基线）。

`docs/04-baseline-data/source_review_decisions.json` 是独立、受版本控制的人工校审输入，不是生成输出。生成器按 `(node_uid, issue_type, source_fingerprint)` 合并其中的决定；不要直接编辑派生日志 `source_data_review_log.json` 保存人工结论。

修改原始材料、生成器或字典后，应重新执行上述命令并检查 Git 差异。不要直接手改由脚本生成的 PRD 和基线文件。

## 六、协作与贡献

> **2026-11-27 双仓协同规则生效（经项目负责人特别授权增补）**：本仓库（`wdgc-supervision-evidence`）仅限技术团队与第三方专家评审团队访问；**产品团队仅在独立协同仓库 `wdgc-supervision-evidence-collab`**。三方后续所有需求（PRD）、原型、多轮评审往返及权威业务口径统一以协同仓库为准，详见根目录 [`AGENTS.md`](AGENTS.md)。

技术、测试和专家评审团队在本代码仓内的工程交付同时遵循：

- [`AGENTS.md`](AGENTS.md)（双仓分工、跨仓协作铁律与本仓库规则边界）
- [`docs/06-collaboration/team-collaboration-and-delivery-workflow.md`](docs/06-collaboration/team-collaboration-and-delivery-workflow.md)

开发与上线门禁分离：允许当前阶段并行开发，不代表已经具备全量上线条件。业务规则、数据库、API、原型和测试变更应通过 GitHub 留痕，避免口头变更和跨文档漂移。
