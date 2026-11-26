# AGENTS.md — 工程代码仓双仓协同与操作规则

> **特别授权留痕**：本规则由第三方专家评审经项目负责人 **2026-11-27 一次性特别授权**增补。此后非经项目负责人再次明确授权，第三方专家评审不得擅自修改本文件或任何仓库规则。

---

## 一、双仓分工与访问边界

本项目实行**工程代码仓与跨团队协同仓分离**管理：

1. **本仓库（`wdgc-supervision-evidence`｜工程代码仓）**
   - **访问角色**：仅限**技术开发团队**与**第三方专家评审团队**（**产品团队不访问本仓库**）。
   - **承载内容**：后端（`src/backend/`）、平台端（`src/platform-web/`）、租户端（后续）、移动端（`src/mp-app/`）、数据库迁移、自动化测试、技术 ADR（`docs/03-architecture/`）、代码/安全专题评审报告（`docs/01-review-reports/`）及工程生成校验脚本。

2. **独立协同仓库（`wdgc-supervision-evidence-collab`｜三方协作唯一事实来源 SSOT）**
   - **仓库地址**：`git@github.com:wufujun2000/wdgc-supervision-evidence-collab.git`（本地常规同级目录 `../wdgc-supervision-evidence-collab`）。
   - **访问角色**：**产品团队、技术开发团队、第三方专家评审团队**。
   - **承载内容**：PRD 文档（`product/prd/`）、交互原型源码（`product/prototype/`）、三方多轮评审回复（`reviews/<模块>/`）、全局协作看板（`STATUS.md`）、已拍板权威业务口径与跨团队决策（`baseline/`）。

---

## 二、进入本仓库的 Agent 必须遵守的跨仓铁律

1. **需求与业务口径以协同仓为唯一真值**：
   - 技术开发或技术评审在读取最新 PRD、交互原型、业务规则与跨团队拍板结论时，**必须先同步并读取 `wdgc-supervision-evidence-collab`**，并严格遵循协同仓 `AGENTS.md` §3 的优先级（`baseline/` → `product/` → `reviews/` 最新 `open` 轮次）。
   - 本仓库 `docs/02-prd/` 下的历史版本（如 PRD v2.4）与 `docs/temp/` 下的旧离线产品交接包仅作历史留档，**不得再作为当前需求依据**。

2. **跨团队协同统一在协同仓落盘**：
   - 技术团队对产品 PRD/原型的工程可行性评估、接口/数据约束回复、业务澄清提问与看板更新，以及第三方评审向产品发布的评审结论与口径沉淀，**一律在协同仓按其 `AGENTS.md` 宪章执行**（严格遵守目录权限：严禁修改 `product/`、`reviews/` 仅只追加 `r*-tech.md` / `r*-expert.md`、遵循中文前缀 commit 与 `git pull --rebase` 规范）。

3. **废止线下文件包流转**：
   - 不再通过 `docs/temp/` 线下传包向产品团队流转需求或评审意见。

4. **本仓库既有工程与评审红线继续有效**：
   - 禁止直接修改 `vendor/`；严禁污染宿主系统环境（禁止 `apt`/`sudo`/全局装包，依赖与缓存隔离至 `tmp/` 或各自 `.venv`/`node_modules`，详见 `README.md` 与 `docs/development-environment-setup.md`）；
   - 第三方专家评审在本仓库坚持只读审查、不擅改业务实现代码；**未经项目负责人再次明确授权，不得修改本文件或仓库规则**。
