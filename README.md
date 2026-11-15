# 危大工程监理履职数字化证据链系统（wdgc-supervision-evidence）

> **仓库定位**：危大工程监理履职数字化证据链系统的**文档与机器可读数据基线仓库**，用于产品、架构、第三方评审专家协同评审与版本追溯。当前以文档先行、单一事实源（SSOT）驱动为核心，支撑后续 AI Agent Vibe Coding 开发。

---

## 一、仓库目录结构

```text
wdgc-supervision-evidence/
├── docs/
│   ├── 00-source-materials/                 # 课题原始材料（研究报告、附录A-1~A-11、附录B/C、履约记录表.xlsx）
│   ├── 01-review-reports/                   # 第三方专家各轮可行性审查与复审报告
│   ├── baseline-data/                       # 由脚本自动生成的机器可读种子字典与校验报告
│   │   ├── hazard_nodes_seed.json           # 347 条课题标准采集基线记录（347 个唯一 node_uid）
│   │   ├── metadata_and_forms_dictionary.json # 24 个标准编号字段 + 28 个内部扩展列 + F01~F05 表单映射
│   │   ├── source_data_review_log.json      # 原始材料待业务校审登记台账
│   │   ├── validation_report.json           # 结构/源数据校审/业务准入三态验证报告
│   │   ├── prd_consistency_report.json      # PRD 与基线数据 91 项 CI 一致性校验报告
│   ├── temp/                                # 面向产品负责人的决策过程与评审溯源沟通文档
│   ├── PRD_v1.0_正式版.md                    # 原始 PRD（历史版本，完整保留）
│   ├── PRD_v2.0_架构对齐版.md                # 架构对齐版（历史版本，完整保留）
│   ├── PRD_v2.1_评审闭环版.md                # 首次评审整改版（历史版本，完整保留）
│   ├── PRD_v2.2_评审整改中.md                # 节点唯一身份与原始数据溯源整改版（历史版本，完整保留）
│   ├── PRD_v2.3_评审整改中.md                # 当前最新：真实 SSOT 驱动 + 业务准入状态拆分 + 法定履职全闭环验收用例
│   ├── system-architecture-design.md        # 总体技术架构与基线融合设计说明书（v1.3 评审整改中版本）
│   ├── document-feasibility-review-2026-11-12.md # 第三方首次可行性审查报告
│   └── rbac-framework-comparison-report.md  # RuoYi-FastAPI vs FastapiAdmin 源码级架构对比报告
└── scripts/
    ├── generate_baseline_data.py            # 从原始 Word/Excel 生成机器可读种子字典与验证报告
    ├── generate_prd_v23.py                  # 从字典自动生成 PRD v2.3 字段表、真实示例与法定履职验收用例
    └── validate_prd_consistency.py          # 真实 CI 一致性校验（37 项断言）
```

---

## 二、当前文档与数据基线状态

| 维度 | 当前状态 | 说明 |
| :--- | :--- | :--- |
| **结构校验（structural_status）** | ✅ PASS | 347 条基线记录 / 347 个全局唯一 `node_uid` / 24 个标准编号字段 / 28 个内部扩展列 |
| **PRD 与字典一致性校验** | ✅ 91/91 项通过 | 见 `docs/baseline-data/prd_consistency_report.json` |
| **源数据业务校审（source_review_status）** | ⏳ PENDING | CONFIRMED=16 条，PENDING_REVIEW=331 条（原始清单风险等级空白及 1 条内容错配，待业务专家确认） |
| **业务开发准入（business_readiness）** | 🚦 BLOCKED | 未经业务校审的节点严禁进入正式强制采集任务与完整度考核分母 |
| **真机技术 PoC** | ⏳ 待启动 | 离线容量、重启恢复、后台续传、全文件 SHA-256、OSS WORM 组合验证 |
| **法务与隐私专项复核** | ⏳ 待复核 | 个人信息保护影响评估（PIPIA）与法务专项复核 |

> **重要说明**：本仓库中的 `docs/PRD_v2.3_评审整改中.md` 与 `docs/system-architecture-design.md` 当前定位为 **“评审整改中版本”**，在完成源数据业务校审、真机 PoC 与法务复核前，不作为全量开发的唯一契约。

---

## 三、如何复现与校验（供评审专家使用）

本仓库仅依赖 **Python 3.10+ 标准库**（无需额外 pip 安装依赖）：

```bash
# 1. 从原始 Word/Excel 材料重新生成机器可读种子字典与验证报告
python3 scripts/generate_baseline_data.py

# 2. 从字典自动生成 PRD v2.3（字段表、真实示例、法定履职验收用例）
python3 scripts/generate_prd_v23.py

# 3. 执行 PRD 与基线数据的真实 CI 一致性校验（91 项断言）
python3 scripts/validate_prd_consistency.py
```

执行完成后，请核对以下输出文件：

- `docs/baseline-data/hazard_nodes_seed.json`：347 条记录 / 347 个唯一 `node_uid`；
- `docs/baseline-data/validation_report.json`：`structural_status=PASS`，`source_review_status=PENDING`，`business_readiness=BLOCKED`；
- `docs/baseline-data/prd_consistency_report.json`：37 项一致性断言全部通过。

---

## 四、评审与协作约定

1. **历史版本完整保留**：`docs/PRD_v1.0_正式版.md`、`docs/PRD_v2.0_架构对齐版.md`、`docs/PRD_v2.1_评审闭环版.md`、`docs/PRD_v2.2_评审整改中.md` 均不删除，便于逐版本追溯偏移原因；
2. **原始材料不篡改**：`docs/00-source-materials/` 下的课题 Word/Excel 原件作为唯一溯源依据，任何原始空白或内容错误仅登记至 `docs/baseline-data/source_data_review_log.json`，由业务专家确认后修订；
3. **评审意见留痕**：第三方各轮审查与复审报告统一归档至 `docs/01-review-reports/`；
4. **分支与提交规范**：后续整改请在特性分支上修改并提交 Pull Request，便于评审专家逐条批注与复核。

---

> 本文档随仓库版本同步维护。如需了解完整选型与多租户架构决策过程，请参阅 `docs/rbac-framework-comparison-report.md`、`docs/system-architecture-design.md` 及 `docs/temp/` 下的沟通说明文档。
