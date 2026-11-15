# 危大工程监理履职证据链系统 —— 开发测试环境搭建方案（V1.0）

> **文档定位**：作为基线搭建前的开发测试环境统一标准，供研发、测试、评审专家与运维共同遵循。  
> **核心原则**：项目级隔离、可复现、可重建、不污染服务器其他项目、与 FastapiAdmin 原生工程一致。  
> **适用阶段**：基线搭建、MVP 开发、联调测试、限定范围 PoC。

---

## 一、方案总览

本项目采用 **“Python 3.12 + uv + 项目级 Docker Compose”** 的开发测试环境方案：

| 组成部分 | 选型 | 说明 |
| :--- | :--- | :--- |
| **Python 版本** | Python 3.12 | 与 FastapiAdmin 原生要求一致 |
| **包与虚拟环境管理** | `uv` | 项目级 `.venv`，依赖锁定 `uv.lock` |
| **数据库** | MySQL 8.0（Docker 容器） | 项目级独立容器与数据卷 |
| **缓存/会话/锁** | Redis 7.x（Docker 容器） | 项目级独立容器与数据卷 |
| **反向代理** | Nginx（Docker 容器，可选启用） | 联调/演示/测试时启用，生产环境必须启用 |
| **工程目录** | `src/backend/`、`src/platform-web/`、`src/tenant-web/`、`src/mp-app/`、`vendor/FastapiAdmin/`、`vendor/RuoYi-FastAPI/`、`deploy/dev/` | 自研代码集中于 `src/`，上游基线源码集中于 `vendor/`，文档目录与代码目录分离 |

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
- MySQL、Redis、Nginx 容器名称、网络、数据卷均以 `wdgc-supervision-evidence` 为前缀；
- 不与服务器上其他开发项目共用容器或数据卷；
- 环境损坏时允许通过 `docker compose down -v && docker compose up -d` 重建。

### 3.2 服务规划

| 服务 | 容器名 | 端口映射（宿主机→容器） | 数据卷 | 用途 |
| :--- | :--- | :--- | :--- | :--- |
| MySQL 8.0 | `wdgc-mysql` | `3307→3306` | `wdgc-mysql-data` | 业务与权限数据 |
| Redis 7.x | `wdgc-redis` | `6380→6379` | `wdgc-redis-data` | 会话、缓存、分布式锁、Nonce |
| Nginx | `wdgc-nginx` | `8080→80` | 配置挂载 | 联调/演示反向代理 |

> 端口映射使用非默认端口，避免与服务器已有 MySQL/Redis/Nginx 冲突。

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

| 上游仓库 | 固定提交 | 用途 |
| :--- | :--- | :--- |
| `FastapiAdmin` | `6828ba16a5c14fbce8479fe1b09b9e8d6ee540c2` | 后端主骨架（RBAC、代码生成、系统监控、fastapp 移动端） |
| `RuoYi-FastAPI` | `7f7c66d373b6b344899961a42249ff51285cd865` | 文件治理、接口防重放签名、Agno 多模态 SSE 参考 |

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
- 已安装 Docker 与 Docker Compose；
- 已安装 `uv`；
- 已安装 Python 3.12（或由 `uv python install 3.12` 安装）。

### 5.2 启动项目级基础服务

```bash
cd deploy/dev
docker compose up -d
```

### 5.3 初始化后端环境

```bash
cd src/backend
uv python pin 3.12
uv venv
uv sync
```

### 5.4 环境自检

```bash
docker ps | grep wdgc
uv run python --version
uv run python -c "import fastapi, sqlalchemy, redis; print('backend deps ok')"
```

---

## 六、后续基线搭建立即事项

环境确认后，按以下顺序进入基线搭建：
1. 以 `vendor/FastapiAdmin`（固定提交 `6828ba1`）为基线，在 `src/backend/` 初始化后端工程；
2. 建立 `TenantModelMixin`、`TenantCRUDBase`、`TenantProjectPermission`；
3. 实现文件防篡改、接口防重放、离线沙箱与分片续传底层模块；
4. 建立 `src/platform-web/`、`src/tenant-web/`、`src/mp-app/` 工程；
5. 开始 MVP 核心业务闭环开发。

---

> **说明**：本方案只约束开发测试环境，不限制生产环境后续切换为云 RDS、云 Redis、云 OSS 或 Kubernetes 部署。
