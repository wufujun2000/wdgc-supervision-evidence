# 危大工程监理履职证据链系统 —— 开发测试环境搭建方案（V1.0）

> **文档定位**：作为基线搭建前的开发测试环境统一标准，供研发、测试、评审专家与运维共同遵循。  
> **核心原则**：项目级隔离、可复现、可重建、不污染服务器其他项目、与 FastapiAdmin 原生工程一致。  
> **适用阶段**：基线搭建、MVP 开发、联调测试、限定范围 PoC。

---

## 〇、系统环境隔离红线（当前执行约束）

1. 禁止执行 `apt`、`sudo`、全局 `pip/npm/pnpm`、系统 Python/Node 替换、系统服务配置、Shell Profile 或系统环境变量修改；未经用户明确授权，不得读写当前仓库以外的路径。
2. 工具、Python、依赖、缓存和临时文件只能位于仓库 `tmp/`、各工程的 `.venv/` 或 `node_modules/`。每条安装、测试和构建命令都必须在子进程中显式设置 `HOME`、XDG 目录、`TMPDIR/TEMP/TMP` 及包管理缓存到仓库内，禁止依赖工具默认的全局路径。
3. Docker Engine 与 Compose 插件由用户手动安装。创建项目专用容器、网络或命名卷同样会改变本机 Docker 状态，必须取得用户当次明确许可；不得操作其他项目的容器、网络或卷。
4. 禁止执行 `docker compose down -v`、`docker system prune` 或删除数据卷。确需删除或重建数据时，必须单独说明影响并取得用户明确授权。
5. `vendor/` 只读；当前只搭建和验收 FastapiAdmin 原生基线，不进入本项目业务模块开发。

---

## 一、方案总览

本项目采用 **“Python 3.12 + uv + 项目级 Docker Compose”** 的开发测试环境方案：

| 组成部分             | 选型                                                                                                                                  | 说明                                                                        |
| :------------------- | :------------------------------------------------------------------------------------------------------------------------------------ | :-------------------------------------------------------------------------- |
| **Python 版本**      | Python 3.12                                                                                                                           | 与 FastapiAdmin 原生要求一致                                                |
| **包与虚拟环境管理** | `uv`                                                                                                                                  | 项目级 `.venv`，依赖锁定 `uv.lock`                                          |
| **数据库**           | MySQL 8.0（Docker 容器）                                                                                                              | 项目级独立容器与数据卷                                                      |
| **缓存/会话/锁**     | Redis 7.x（Docker 容器）                                                                                                              | 项目级独立容器与数据卷                                                      |
| **反向代理**         | Nginx（Docker 容器，可选启用）                                                                                                        | 联调/演示/测试时启用，生产环境必须启用                                      |
| **工程目录**         | `src/backend/`、`src/platform-web/`、`src/tenant-web/`、`src/mp-app/`、`vendor/FastapiAdmin/`、`vendor/RuoYi-FastAPI/`、`deploy/dev/` | 自研代码集中于 `src/`，上游基线源码集中于 `vendor/`，文档目录与代码目录分离 |

---

## 二、Python 版本与包管理规范

### 2.1 为什么使用 `uv` 而不是 Conda？

- 与 FastapiAdmin 原生 `pyproject.toml + uv.lock` 完全一致；
- 安装速度快、依赖解析明确、适合 Agent Vibe Coding；
- 支持同一台服务器多个 Python 版本共存；
- 每个项目独立 `.venv`，不会影响系统 Python 或其他项目。

### 2.2 多 Python 版本并存方式

```bash
# 安装多个 Python 版本（按需）
uv python install 3.10
uv python install 3.11
uv python install 3.12

# 本项目固定 Python 3.12
uv python pin 3.12

# 创建项目虚拟环境并安装依赖
uv venv
uv sync
```

如其他项目需要不同 Python 版本，只需在其项目目录执行 `uv python pin <version>` 即可，互不影响。

### 2.3 项目级隔离要求

- 每个项目必须有独立的 `.venv`；
- 禁止将本项目依赖安装到系统 Python；
- 禁止与其他项目共用虚拟环境；
- 后端依赖必须写入 `src/backend/pyproject.toml` 并生成 `uv.lock`。

---

## 三、MySQL / Redis / Nginx 部署规范

### 3.1 项目级 Docker 隔离原则

- 本项目使用独立的 `deploy/dev/docker-compose.yml`；
- Compose 顶层项目名为 `wdgc-supervision-evidence`，MySQL、Redis 使用项目默认网络，容器与数据卷采用项目专属名称；
- 不与服务器上其他开发项目共用容器、数据库数据卷或 MySQL/Redis 默认网络；
- 环境损坏时先保留现场并诊断；删除容器、网络或数据卷及重建操作须按第〇章单独取得用户明确授权。

### 3.2 服务规划

| 服务          | 容器名       | 端口映射（宿主机→容器）                                | 数据卷            | 用途                        |
| :------------ | :----------- | :----------------------------------------------------- | :---------------- | :-------------------------- |
| MySQL 8.0     | `wdgc-mysql` | `3307→3306`                                            | `wdgc-mysql-data` | 业务与权限数据              |
| Redis 7.x     | `wdgc-redis` | `6380→6379`                                            | `wdgc-redis-data` | 会话、缓存、分布式锁、Nonce |
| Nginx（可选） | `wdgc-nginx` | 本机 Linux `network_mode: host`，监听 `127.0.0.1:8080` | 配置挂载          | 本机联调反向代理            |

> MySQL/Redis 使用非默认端口并绑定回环地址，避免与服务器已有服务冲突。Nginx 不使用端口映射或 `host.docker.internal`，详见 3.3。

### 3.3 可选本机 Linux Nginx 联调

`with-nginx` profile **仅用于本机 Linux 开发联调，不是生产配置**。Nginx 容器使用 `network_mode: host`，直接监听 `127.0.0.1:8080`，不配置 `ports` 或 `extra_hosts`。这样容器可以直接访问同样只监听回环地址的后端，无需把后端改为 `0.0.0.0`，也不开放宿主防火墙。

- `/api/` 保留完整 URI 并代理至 `http://127.0.0.1:8001`；后端仍保持 `127.0.0.1:8001`。
- `/platform/` 代理至 `http://127.0.0.1:5173`，保留 `/platform/` 基础路径；`/tenant/` 代理至 `http://127.0.0.1:5174`。
- API 与平台代理使用 HTTP 1.1，并传递 `Upgrade`、`Connection`、Host 和 X-Forwarded 头，分别支持 AI WebSocket 与 Vite HMR，不改变业务路由。
- macOS、Windows 或需要跨主机访问的部署不得套用此配置；生产环境应另行使用隔离网络及明确的回环/内网监听策略。

在用户明确许可 Docker 操作后，本机 Linux 才可执行：

```bash
docker compose -f deploy/dev/docker-compose.yml --profile with-nginx up -d nginx
```

当前仅完成静态配置与 YAML 校验，未启动 Docker，也未实测 Nginx、HMR 或 WebSocket。

---

## 四、工程目录结构

```text
wdgc-supervision-evidence/
├── src/                             # 应用工程（自研代码）
│   ├── backend/                     # FastAPI 后端工程（Python 3.12 + uv）
│   │   ├── pyproject.toml
│   │   ├── uv.lock
│   │   ├── .python-version
│   │   └── app/
│   ├── platform-web/                # 平台管理端（Vue3 + TS）
│   ├── tenant-web/                  # 租户监理工作台（Figma Make React 工程）
│   └── mp-app/                      # 现场移动采集端（UniApp + TS）
├── vendor/                          # 上游基线源码（本地克隆，不纳入版本控制）
│   ├── FastapiAdmin/                # 后端主骨架基线（固定提交 6828ba1）
│   └── RuoYi-FastAPI/               # 文件治理、防重放、多模态 SSE 参考基线（固定提交 7f7c66d）
├── deploy/
│   └── dev/
│       ├── docker-compose.yml       # 项目级 MySQL/Redis/Nginx 隔离环境
│       └── nginx.conf               # 可选反向代理配置
├── docs/                            # 文档与机器可读基线
├── scripts/                         # 生成与校验脚本
├── tests/                           # 跨端契约、集成与验收测试
└── README.md
```

### 4.1 上游基线源码（vendor/）

`vendor/` 保存两个上游开源框架的基线源码，仅作差异比对与能力移植参考，禁止直接修改其中的文件。该目录为本地克隆、不纳入版本控制，首次检出仓库后在根目录执行：

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

后续初始化 `src/backend/` 时，应以上述 `FastapiAdmin` 固定提交的 `backend/` 工程为基线复制改造，而不是直接修改 `vendor/` 内的文件。

---

## 五、环境初始化步骤

### 5.1 前置条件

- Docker Engine 与 Compose 插件由用户手动安装；创建项目容器、网络或卷前必须取得当次明确许可；
- Node.js 满足上游 `package.json` 的 engines 要求；
- `uv`、Python 3.12、pnpm 与所有缓存使用根 README 第 4.2 节的仓库内工具链，不要求全局安装。

### 5.2 启动项目级基础服务

获得用户当次明确许可后，在仓库根目录执行：

```bash
docker compose -f deploy/dev/docker-compose.yml up -d --wait mysql redis
```

### 5.3 初始化后端环境

先按根 README 第 4.2 节在子进程中设置仓库内 `HOME`、XDG、临时目录和包缓存，再执行：

```bash
cd src/backend
uv sync --extra mysql
```

### 5.4 环境自检

```bash
docker compose -f deploy/dev/docker-compose.yml ps
uv run --no-sync python --version
uv run --no-sync python -c "import fastapi, sqlalchemy, redis; print('backend deps ok')"
```

---

## 六、后续基线搭建立即事项

环境确认后，按以下顺序推进：

1. 从固定提交导入 `src/backend/`、`src/platform-web/`、`src/mp-app/`，保留锁文件、测试、配置模板和 MIT 许可；`tenant-web` 继续等待 Figma Make；
2. 完成上游 pytest、pyright、前端类型/测试/lint/构建及真实 MySQL/Redis/登录/页面验收；
3. 原生基线验收通过后，再单独实施 `TenantModelMixin`、`TenantCRUDBase`、`TenantProjectPermission` 与 H-01～H-03 加固；
4. 文件防篡改、接口防重放、离线沙箱与分片续传按架构和 PoC 分阶段验证；
5. 当前阶段不进入 MVP 业务模块开发，后续业务任务须在基线验收后单独下达。

---

> **说明**：本方案只约束开发测试环境，不限制生产环境后续切换为云 RDS、云 Redis、云 OSS 或 Kubernetes 部署。
