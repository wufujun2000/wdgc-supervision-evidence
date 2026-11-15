# 危大工程监理履职证据链系统

危大工程监理履职证据链系统面向监理企业、项目总监、专业监理工程师和现场监理人员，用于支撑危大工程履职过程中的任务驱动采集、现场影像取证、监理审核、隐患整改、停复工、验收签认、档案归集与证据导出。

系统重点解决多企业与多项目并行情况下的租户隔离、项目级权限、原始证据保护、弱网离线采集、履职过程追踪及证据完整性核验问题。

## 一、当前项目状态

当前处于**文档与数据基线已建立、前端原型与真实技术基线并行开发**阶段。

本仓库目前包含需求、架构、原始研究材料、机器可读数据、生成与校验脚本、团队协作与评审记录，以及 `src/backend/` 后端工程骨架（Python 版本与依赖已声明，业务模块待基线搭建）；尚不是包含完整前后端实现的成品仓库。

当前允许开展技术基线、原型和限定范围业务开发。全量上线仍需完成源数据业务校审、真机与云服务 PoC、行为验收及法务合规复核，具体状态见 `docs/04-baseline-data/validation_report.json`。

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

| 顺序 | 文件 | 用途 |
| :--- | :--- | :--- |
| 1 | [`docs/README.md`](docs/README.md) | 完整文档地图、当前版本、逐文件说明和角色阅读路线 |
| 2 | [`docs/02-prd/PRD_v2.3_评审整改中.md`](docs/02-prd/PRD_v2.3_评审整改中.md) | 当前产品需求、角色、功能、数据规则及验收要求 |
| 3 | [`docs/03-architecture/system-architecture-design.md`](docs/03-architecture/system-architecture-design.md) | 技术选型、工程拓扑、多租户与证据链架构 |
| 4 | [`docs/06-collaboration/team-collaboration-and-delivery-workflow.md`](docs/06-collaboration/team-collaboration-and-delivery-workflow.md) | 产品、技术、测试和专家评审团队的协作规则 |
| 5 | [`docs/04-baseline-data/validation_report.json`](docs/04-baseline-data/validation_report.json) | 当前结构、业务校审和开发准入状态 |

**所有文档相关说明统一查看 [`docs/README.md`](docs/README.md)。根 README 只承担项目入口和工程导航职责。**

## 四、仓库结构

```text
wdgc-supervision-evidence/
├── README.md                         # 项目说明与开发 Agent 总入口
├── src/                              # 应用工程（自研代码）
│   ├── backend/                      # FastAPI 后端工程（Python 3.12 + uv）
│   │   ├── pyproject.toml            # 后端依赖与构建声明
│   │   ├── .python-version           # 固定 Python 3.12
│   │   └── app/                      # 后端业务代码（随基线搭建生成）
│   ├── platform-web/                 # 平台管理端（Vue3 + TS）
│   ├── tenant-web/                   # 租户监理工作台（React + TS）
│   └── mp-app/                       # 现场移动采集端（UniApp + TS）
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

## 五、生成与校验

当前脚本仅依赖 Python 3.10+ 标准库：

```bash
python3 scripts/generate_baseline_data.py
python3 scripts/generate_prd_v23.py
python3 scripts/validate_prd_consistency.py
```

生成结果包括：

- `docs/04-baseline-data/hazard_nodes_seed.json`：347 条基线记录及唯一节点身份；
- `docs/04-baseline-data/metadata_and_forms_dictionary.json`：标准字段、内部扩展和表单映射；
- `docs/04-baseline-data/validation_report.json`：结构与业务准入状态；
- `docs/04-baseline-data/prd_consistency_report.json`：实际一致性检查数量与结果（以 `checks_passed/checks_total` 为准）；
- `docs/02-prd/PRD_v2.3_评审整改中.md`：由生成器输出的当前 PRD。

修改原始材料、生成器或字典后，应重新执行上述命令并检查 Git 差异。不要直接手改由脚本生成的 PRD 和基线文件。

## 六、协作与贡献

产品、技术、测试和专家评审团队统一遵循：

- [`docs/06-collaboration/team-collaboration-and-delivery-workflow.md`](docs/06-collaboration/team-collaboration-and-delivery-workflow.md)

开发与上线门禁分离：允许当前阶段并行开发，不代表已经具备全量上线条件。业务规则、数据库、API、原型和测试变更应通过 GitHub 留痕，避免口头变更和跨文档漂移。
