"""
危大工程监理履职证据链系统 —— PRD v2.3 生成器（真实 SSOT 驱动）
从 docs/baseline-data/ 的机器可读字典自动生成全部字段表、节点表、真实示例与法定履职验收用例。
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "docs", "baseline-data")

with open(os.path.join(OUT_DIR, "hazard_nodes_seed.json"), "r", encoding="utf-8") as f:
    hazard_seed = json.load(f)
with open(os.path.join(OUT_DIR, "metadata_and_forms_dictionary.json"), "r", encoding="utf-8") as f:
    dictionary = json.load(f)
with open(os.path.join(OUT_DIR, "validation_report.json"), "r", encoding="utf-8") as f:
    validation = json.load(f)

nodes = hazard_seed['nodes']
node_map = {n['node_uid']: n for n in nodes}
confirmed_node = next(n for n in nodes if n['review_status'] == 'CONFIRMED' and n['hazard_code'] != '12')
pending_node = next(n for n in nodes if n['review_status'] == 'PENDING_REVIEW')

# 真实示例 1：已确认节点（CONFIRMED + ★）—— 所有分类、阶段、目录、文件名与部位均由同一节点派生
n1 = confirmed_node
example1 = {
    "tenant_id": 1001, "enterprise_code": "ENT-001", "project_code": "TJ-2026-0089",
    "hazard_code": n1['hazard_code'], "subcategory_code": n1['subcategory_code'], "stage_code": n1['stage_code'],
    "legacy_node_code": n1['legacy_node_code'], "node_uid": n1['node_uid'],
    "risk_level": n1['risk_level'], "review_status": n1['review_status'],
    "media_type": "照片", "suggested_media_type": n1['suggested_media_type'],
    "shoot_utc_time": "2026-10-14 14:32:18", "shooter_emp_no": "JL027",
    "risk_summary": n1['risk_description'], "media_guid": "8f42d17c-903e-471a-b9c4-2d58f3107961",
    "gps_coordinates": "117.2136,39.0872", "gps_status": 1, "position_desc": None,
    "client_clock_verified": 1, "is_offline_queued": 0, "time_drift_warning": 0,
    "example_data_status": "SYNTHETIC",
    "raw_frame_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "file_sha256": "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
    "deposit_time": "2026-10-14 14:32:20.128", "upload_operator_no": "JL027",
    "storage_path": f"ENT-001/TJ-2026-0089/{n1['hazard_code']}_{n1['hazard_name']}/{n1['stage_code']}_{n1['stage_name']}/20261014/photo/TJ-2026-0089_{n1['hazard_code']}_{n1['subcategory_code']}_{n1['stage_code']}_{n1['source_sequence']:02d}_{n1['risk_level']}_20261014143218.JPG"
}

# 真实示例 2：待校审节点（PENDING_REVIEW，风险等级为 null，不参与正式强制采集与完整度考核）
n2 = pending_node
example2 = {
    "tenant_id": 1001, "enterprise_code": "ENT-001", "project_code": "TJ-2026-0089",
    "hazard_code": n2['hazard_code'], "subcategory_code": n2['subcategory_code'], "stage_code": n2['stage_code'],
    "legacy_node_code": n2['legacy_node_code'], "node_uid": n2['node_uid'],
    "risk_level": n2['risk_level'], "review_status": n2['review_status'],
    "media_type": "照片", "suggested_media_type": n2['suggested_media_type'],
    "shoot_utc_time": "2026-10-14 16:15:00", "shooter_emp_no": "JL014",
    "media_guid": "7b19a334-82fe-4912-a7d1-1d54e928f610",
    "gps_coordinates": None, "gps_status": 2,
    "is_offline_queued": 1, "client_clock_verified": 1, "time_drift_warning": 0,
    "example_data_status": "SYNTHETIC",
    "raw_frame_sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
    "file_sha256": "9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedcba",
    "storage_path": f"ENT-001/TJ-2026-0089/{n2['hazard_code']}_{n2['hazard_name']}/{n2['stage_code']}_{n2['stage_name']}/20261014/photo/TJ-2026-0089_{n2['hazard_code']}_{n2['subcategory_code']}_{n2['stage_code']}_{n2['source_sequence']:02d}_UNSPECIFIED_20261014161500.JPG",
    "business_gate_note": "该节点原始风险等级未标注，review_status=PENDING_REVIEW，不得进入正式强制采集任务与履职完整度考核分母，需业务专家确认后方可启用。"
}

# 分类节点统计表
category_table = "| 分类编码 | 危大工程类别名称 | 原始课题文件/来源 | 基线记录数 | 说明 |\n|:---:|:---|:---|:---:|:---|\n"
for hc, info in hazard_seed['metadata']['category_counts'].items():
    note = "通用应急模块（不划分施工三阶段，stage_code=99）" if hc == '12' else "专业危大工序采集记录"
    category_table += f"| **{hc}** | {info['name']} | 附录 A-{int(hc) if hc != '12' else '12（研究报告4.13节）'} | **{info['record_count']}** | {note} |\n"
category_table += f"| **合计** | **12 大类全周期覆盖** | - | **{len(nodes)} 条** | 11 类专业危大 342 条 + 通用应急处置 5 条 |\n"

# 标准字段表
field_table = "| 标准编号 | 标准名称 | 数据库物理列名 | 数据类型与长度 | 约束 | 业务规则与数据源定义 |\n|:---:|:---|:---|:---|:---|:---|\n"
for f in dictionary['standard_metadata_fields']:
    field_table += f"| **{f['field_code']}** | {f['field_name']} | `{f['column_name']}` | `{f['data_type']}` | {f['constraint']} | {f['description']}（{f['source_and_writer']}） |\n"

ext_table = "| 内部扩展列名 | 数据类型 | 业务与工程用途说明 |\n|:---|:---|:---|\n"
for ext in dictionary['internal_database_extensions']:
    ext_table += f"| `{ext['column_name']}` | `{ext['data_type']}` | {ext['description']} |\n"

forms_table = "| 表单族编号 | 表单族名称 | 正式法规/标准表号映射 | 对应原始 Excel 工作表 | 核心填报角色 | 关联影像存证动作与规则 |\n|:---:|:---|:---|:---:|:---|:---|\n"
for form in dictionary['core_supervision_forms']:
    forms_table += f"| **{form['form_family_code']}** | {form['form_family_name']} | {form['official_standard_mapping']} | `{form['source_excel_sheet']}` | 专监/监理员/总监按项目角色 | {form['media_binding_rule']} |\n"

prd = f"""---
文档名称：危大工程监理履职数字化证据链系统 产品需求文档（PRD）
系统版本：v2.3 评审整改中版本（真实 SSOT 驱动 + 业务准入状态拆分 + 法定履职全闭环验收用例）
当前文档状态：评审整改中（结构校验通过，源数据业务校审与真机 PoC 尚未完成，暂不作为全量开发基线）
前序版本：docs/PRD_v2.2_评审整改中.md / docs/PRD_v2.1_评审闭环版.md / docs/PRD_v2.0_架构对齐版.md / docs/PRD_v1.0_正式版.md（历史版本完整保留）
复审依据：docs/01-review-reports/prd-v2.2-follow-up-review-2026-11-15.md
原始材料溯源目录：docs/00-source-materials/
机器可读数据字典与校验报告：docs/baseline-data/
更新时间：2026-11-15
编制原则：真实单一事实源（SSOT）驱动、原始数据忠实可溯源、结构验证与业务准入严格分离、法定监理职责全闭环
密级：内部受限（机密）
---

# 危大工程监理履职数字化证据链系统 产品需求文档（PRD v2.3 评审整改中版本）

> **文档状态与边界声明**：本版本针对第三方《PRD v2.2 重新复审报告》（`WDGC-PRD-V22-FOLLOWUP-20261115`）进行了严格整改。本文档的字段表、节点统计、示例数据与验收用例全部由 `scripts/generate_baseline_data.py` 与 `scripts/generate_prd_v23.py` 从 `docs/00-source-materials/` 自动生成，并受 `scripts/validate_prd_consistency.py` 真实校验。  
> **业务准入状态（真实拆分）**：
> - `structural_status = {validation['structural_status']}`（347 条记录 / 347 个全局唯一 `node_uid` / 24 个标准字段 / 28 个内部扩展列）；
> - `source_review_status = {validation['source_review_status']}`（CONFIRMED={validation['confirmed_node_count']} 条，PENDING_REVIEW={validation['pending_review_node_count']} 条，待业务专家逐条确认）；
> - `business_readiness = {validation['business_readiness']}`（**未经业务校审的节点严禁进入正式强制采集任务与完整度考核分母**，待源数据校审与真机 PoC 完成后方可申请全量开发基线复审）。

---

## 全书宏观目录（Table of Contents）

- [第0章 v2.3 整改说明与真实校验边界](#第0章-v23-整改说明与真实校验边界)
- [第1章 文档说明](#第1章-文档说明)
- [第2章 项目背景与问题定义](#第2章-项目背景与问题定义)
- [第3章 用户与角色分析（平台域与租户域两级解耦体系）](#第3章-用户与角色分析)
- [第4章 系统总体设计（一后端三前端与 FastapiAdmin+RuoYi 融合架构）](#第4章-系统总体设计)
- [第5章 功能需求详述（一期六大业务中心与法定履职闭环）](#第5章-功能需求详述一期)
- [第6章 数据规范与存储规则（24项标准字段+内部扩展与五级目录）](#第6章-数据规范与存储规则)
- [第7章 非功能性需求与个人信息保护合规专节](#第7章-非功能性需求)
- [第8章 原型页面清单与交互说明（平台端3页 + 租户端11页 + 小程序9页）](#第8章-原型页面清单与交互说明)
- [第9章 验收标准与测试要点（含法定履职全闭环用例）](#第9章-验收标准与测试要点)
- [第10章 附录（标准对照、映射矩阵与修订说明）](#第10章-附录标准对照映射矩阵与修订说明)

---

# 第0章 v2.3 整改说明与真实校验边界

## 0.1 真实整改内容（对应 v2.2 复审报告）

1. **标准字段语义严格分离**：`B004` 恢复为原始附录清单业务编号 `legacy_node_code`（非唯一键），内部全局身份 `node_uid` 作为独立扩展列；`B005` 风险等级仅允许 `★/△`，原始空白仅通过 `review_status` 与 `raw_risk_level` 表达；`B006` 单文件介质仅允许“照片/视频”，节点建议介质独立为 `suggested_media_type`。
2. **验证状态真实拆分**：`validation_report.json` 分别输出 `structural_status`、`source_review_status`、`business_readiness`，杜绝将结构 PASS 误读为业务准入。
3. **真实示例与一致性校验**：PRD 示例全部由种子库真实节点生成，风险状态与种子库严格一致；`scripts/validate_prd_consistency.py` 实际校验字段契约、示例 UID、命名公式、权限旧词、离线配额与法定履职用例。
4. **法定履职全闭环验收用例**：补齐严重隐患停工送达、建设单位/主管部门报告、多轮复查、复工审查、验收双签与下一道工序门禁的完整测试用例。
5. **非功能与隐私合规口径统一**：统一水印、上传、原图加载性能指标，诚实建模 EXIF 可获取范围与定位异常状态，新增第 7.7 节个人信息保护合规专节。

---

# 第1章 文档说明

## 1.1 文档目的与适用范围
本文档为「危大工程监理履职数字化证据链系统」一期产品的需求规格说明书（PRD），用于明确一期 MVP 的功能范围、统一产品/研发/测试团队认知、指导原型与开发，并作为功能验收的依据。

## 1.2 名词与缩略语表
| 名词/缩写 | 全称/解释 |
|----------|---------|
| **危大工程** | 危险性较大的分部分项工程，依住建部令第37号定义；本系统采用 11 类专业危大课题清单 + 1 个通用应急兜底模块的采集基线结构 |
| **数字化证据链** | 在危大工程全生命周期中，证明监理单位按法规与合同履职的完整证据集合体 |
| **node_uid** | 节点内部全局唯一身份编码（如 `WDGC-A-04-SC03-01`），与标准业务编号 `legacy_node_code` 分离 |
| **review_status** | 源数据校审状态：`CONFIRMED`（已确认）/ `PENDING_REVIEW`（待业务校审） |
| **WORM** | Write Once, Read Many，对象存储合规保留策略（1~25,550 天） |
| **Impersonation** | 超级管理员在平台端发起的受控代管穿透，默认只读并强制审计 |
| **RBAC** | Role-Based Access Control，基于角色的权限访问控制 |

---

# 第2章 项目背景与问题定义

## 2.1 行业背景与政策依据
危险性较大的分部分项工程（危大工程）是建筑施工安全事故的高发领域。依据住建部令第37号及建办质〔2018〕31号，监理单位需履行方案审查、专项巡视、旁站监理、隐患整改、验收签认及档案管理等法定职责。本系统采用 **“11 类专业危大课题清单 + 1 个通用应急兜底模块”** 的采集基线结构，共 347 条基线记录。

> **核心认知**：“做了，但没有形成有效记录，在法律和监管意义上等同于没做。”

## 2.2 现状痛点分析
基于对天津市 5 家骨干监理企业、10 个在建危大项目的调研（发放问卷 120 份，回收有效问卷 108 份，深度访谈 20 人），发现“何时拍、拍什么、怎么命名、如何关联单据、如何证明未篡改”缺乏统一标准。

## 2.3 数字化证据链核心概念
数字化证据链 = 在危大工程全生命周期中，由企业租户、可信时间、地理坐标、人员身份、原始多媒体与业务单据组成的完整证据集合体，用于增强履职证据的真实性、关联性、完整性与举证支持能力。

## 2.4 一期目标与边界
一期目标是在首批试点监理单位的真实危大项目上跑通 **“企业入驻 → 项目配置 → 清单驱动采集 → 审核闭环 → 证据链归档出证”** 完整闭环。一期不包含区块链上链、政府平台对接等二期/三期功能，AI 自动识别仅保留可选扩展字段，不作为核心流程依赖。

---

# 第3章 用户与角色分析

## 3.1 平台域与租户域两级解耦角色体系

系统采用 **“一后端三前端”物理分离架构**：
- **平台管理端（`platform-web`）**：服务系统管理员与超级管理员，仅负责企业租户开通、课题标准节点基线库维护与全局审计；
- **租户监理工作台（`tenant-web`）**：服务企业管理员、项目总监与专业监理工程师，承载项目配置、任务分派、审核、表单与出证；
- **现场移动采集端（`mp-app`，微信小程序）**：服务现场监理员、专监移动端与总监移动端，是全系统唯一合法现场拍照/录像取证入口。

## 3.2 角色详细描述

### 3.2.1 现场监理员（项目级角色 `SA`）
在微信小程序查看本人待办任务，按节点指引实时拍摄带水印影像，补充关联单据编号，支持离线缓存与网络恢复续传。

### 3.2.2 专业监理工程师（项目级角色 `SP`）
可同时负责同一项目下的多类危大工程（`01~12`），在 PC 端与小程序端审核所管辖危大类别下的任务与影像，下发隐患整改并复查闭环。

### 3.2.3 项目总监（项目级角色 `SZ`）
负责全项目履职把控、审批与终审；在手机端查看红黄灯告警与移动审批，在 PC 端导出结构化证据包。

### 3.2.4 企业管理员（企业级角色 `ADMIN`）
负责本企业项目建档、人员账号管理、项目成员指派与专监多危大绑定，查阅企业级履职台账。

### 3.2.5 系统管理员（平台级角色 `SYSADMIN`）
负责监理企业租户开通、课题标准采集节点基线库维护与平台运行监控，不查看企业实际业务影像。

### 3.2.6 超级管理员（平台级角色 `SUPERADMIN`）
仅在平台端发起受控代管穿透（Impersonation），通过一次性短效授权码进入目标租户工作台；**默认只读**，导出与督查督办需单独二次授权，**原始取证影像与哈希记录严禁修改或物理删除**。法定签字与终审权由项目实际委派的总监/专监行使，超管不得代替法定责任人签字。

## 3.3 角色权限矩阵（v2.3 统一版）

| 功能模块 / 操作权限 | 监理员(SA) | 专监(SP) | 总监(SZ) | 企业管理员(ADMIN) | 系统管理员(SYSADMIN) | 超级管理员(SUPERADMIN) | 终端说明 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| 企业租户开通与初始化 | ❌ | ❌ | ❌ | ❌ | ✅（全局租户） | ✅（平台端） | 仅 platform-web |
| 课题标准节点基线库维护 | ❌ | ❌ | ❌ | ❌ | ✅（全局共享） | ✅（平台端） | 仅 platform-web |
| 项目创建与危大类型配置 | ❌ | ❌ | ❌ | ✅（本企业） | ❌ | 👁（代管只读） | tenant-web |
| 项目成员与角色绑定 | ❌ | ❌ | 📝（调配建议） | ✅（本企业） | ❌ | 👁（代管只读） | tenant-web |
| 查看采集任务清单 | 📝（本人待办） | 📝（所管危大） | ✅（全项目） | 👁（企业概览） | ❌ | 👁（代管只读） | 小程序 + tenant-web |
| 现场影像防篡改采集与上传 | ✅ | ✅ | 👁（可查不可拍） | ❌ | ❌ | ❌（不参与现场拍照） | 仅限微信小程序 |
| 影像合规性审核（通过/驳回） | ❌ | ✅（所管危大） | ✅（全项目复核） | ❌ | ❌ | 👁（代管只读） | 小程序 + tenant-web |
| 核心节点与关键指令审批 | ❌ | 📝（初审） | ✅（终审批准） | ❌ | ❌ | ❌（不得代替法定责任人签字） | 小程序 + tenant-web |
| 隐患下发与整改复查 | 📝（现场复查拍照） | ✅（发起与审核） | ✅（重大隐患督办） | 👁（本企业） | ❌ | 👁（代管只读） | 小程序+tenant-web |
| 履职证据包结构化导出 | ❌ | ❌ | ✅（项目级） | ✅（企业级） | ❌ | 📝（代管二次授权后导出） | tenant-web |

---

# 第4章 系统总体设计

## 4.1 核心设计原则
1. 法定合规与证据有效原则；
2. 轻量多租户与严格隔离原则（共享 MySQL + `tenant_id` 行级隔离 + OSS 企业前缀逻辑隔离）；
3. 轻量便携与减负增效原则（微信小程序即开即用，元数据自动获取）；
4. 架构稳健与标准先行原则（机器可读字典作为唯一事实源）；
5. 离线容错与断网续传原则；
6. 演进兼容原则（预留电子签章、企业计费与区块链存证扩展槽位）。

## 4.2 多租户与三维权限机制
- **数据库隔离**：所有租户业务表包含 `tenant_id`，由 `TenantCRUDBase` 在 SQL 执行层强制注入 `AND tenant_id = :current_tenant_id`，无全库放行旁路；
- **对象存储隔离**：OSS 按 `{{enterprise_code}}/{{project_code}}/...` 进行路径前缀逻辑隔离，并由服务端进行对象级签名鉴权；
- **项目级权限**：根据用户在当前激活项目（`X-Project-Id`）中的角色（`SZ/SP/SA`）与专监危大绑定关系自动过滤；
- **超级管理员受控代管**：仅在 `platform-web` 发起 Impersonation，通过一次性短效授权码换取短期目标租户会话，默认只读并全程写入 `plat_privilege_audit_log`。

## 4.3 已锁定技术基线与“一后端三前端”融合架构

| 终端工程目录 | 终端名称 | 锁定技术栈与工程来源 | 承载页面范围 |
|:---|:---|:---|:---|
| `frontend/platform-web` | 平台运营总控台 | Vue3 + Vite + TypeScript + Element Plus（延用 FastapiAdmin 自带前端） | P-PC-01~03 及系统监控 |
| `frontend/tenant-web` | 租户监理工作台 | React 18 + Vite + TypeScript + Tailwind + shadcn/ui（直接采用 Figma Make 产出工程） | P-PC-04~14 |
| `frontend/mp-app` | 现场移动采集端 | UniApp + Vue3 + 全量 TypeScript + Wot Design Uni v2 + Alova（FastapiAdmin fastapp） | P-MP-01~09 |

后端以 `FastapiAdmin`（固定提交 `6828ba16a5c14fbce8479fe1b09b9e8d6ee540c2`）为主骨架，借鉴 `RuoYi-FastAPI`（固定提交 `7f7c66d373b6b344899961a42249ff51285cd865`）文件防篡改治理、接口防重放签名与 Agno 多模态 SSE 设计思想构建自研增强模块。

## 4.4 数字化证据链构建与防篡改核心机制
- **五维一体绑定**：企业租户 + 可信时间 + 地理坐标 + 人员身份 + 原始多媒体 + 关联业务单据；
- **双哈希分离模型**：水印压印 `media_guid` + 原始帧摘要 `raw_frame_sha256` 前 16 位；归档文件最终摘要 `file_sha256`（B301）由服务端流式计算并锁定；
- **调阅与出证全文件校验**：执行全文件 SHA-256 比对，不使用 ETag/CRC64 或抽样哈希替代；
- **PDF 二维码**：承载 `doc_guid` + 表单结构化内容摘要与核验标识，最终 PDF 文件摘要独立写入校验清单。

---

# 第5章 功能需求详述（一期）

## 5.1 企业租户与多项目管理中心
- 平台管理员在 `platform-web` 开通监理企业租户（企业编码 `ENT-001`），初始化企业管理员账号；
- 企业管理员在 `tenant-web` 创建项目、录入住建备案编号（B001）、圈定电子围栏并勾选危大类型；
- 项目成员指派支持同一员工在不同项目担任不同角色，专监绑定多类危大超过 3 类时弹出履职风险提示。

## 5.2 标准节点库与任务驱动中心
- 系统内置 **“11 类专业危大课题清单（342 条）+ 1 个通用应急兜底模块（5 条）”共 347 条课题标准采集基线记录**，唯一事实来源为 `docs/baseline-data/hazard_nodes_seed.json`；
- **业务准入门禁**：仅 `review_status=CONFIRMED` 的节点允许进入正式强制采集任务与履职完整度考核分母；`PENDING_REVIEW` 节点一律不进入正式应采任务，不参与完整度分母；
- 支持按楼栋/部位/施工批次创建任务发生实例（`biz_task_occurrence`），同一节点可在不同楼栋或批次重复发生；
- 支持不适用申请与总监审批，剔除不适用与未到工序时点项。

## 5.3 现场防篡改移动采集中心（微信小程序端专属）
- **唯一合法取证入口**：现场拍照/录像仅限微信小程序原生相机实时摄录，PC 端严禁拍照取证与上传现场照片；
- **水印与元数据**：压印项目编码、危大类别、节点身份、UTC+8 时间、工号、WGS-84 经纬度及 `media_guid` + 原始帧摘要前缀；
- **EXIF 诚实建模**：`uni.getImageInfo` 仅承诺返回宽高、方向、类型等基础信息，不承诺完整相机厂商/焦距/快门，按 `exif_available_status` 三态建模；
- **离线沙箱**：严格采用 **150MB 字节硬红线（预留 50MB 系统余量，最多 40 张照片或 3 段离线短视频）**，避免触及微信 200MB 本地存储限制；
- **断点续传**：超过 20MB 视频采用固定 5MB 分片（OSS Multipart），失败按 1s/2s/4s 指数退避重试；
- **单调时钟防漂移**：区分正常离线排队与设备系统时间人为拨改，正常离线数小时上传不误报为时钟漂移。

## 5.4 监理审核流转与法定履职闭环中心
- 专监对所管辖危大类别下的影像进行合格通过或驳回（选择标准驳回原因并通知监理员）；
- 隐患流程支持一般隐患通知单（A.0.3）与严重隐患工程暂停令（A.0.5）、送达/拒收记录、报告建设单位/住建主管部门、多轮复查、复工审查；
- 验收合格须经施工单位技术负责人及总监双签，并拍摄验收标识牌公示照片，完成后解锁下一道工序门禁。

## 5.5 核心监理表单管理中心
一期落地 F01~F05 五大核心表单族，严格对齐《危大工程监理履约记录表.xlsx》与 GB/T 50319-2013 标准表号（旁站 A.0.6、通知单 A.0.3、暂停令 A.0.5、回复单 B.0.9、方案报审 B.0.1）。支持在线填报、关联影像插入、GB/T 50319 版式还原与矢量 PDF 导出。

## 5.6 证据链检索调阅与合规出证中心
- 按危大分类、施工阶段、风险等级、单据编号、人员工号、日期范围进行四维检索；
- 五级树形目录调阅：`{{enterprise_code}}/{{project_code}}/{{危大类}}/{{阶段}}/{{日期}}/photo|video|paper`；
- 一键异步打包导出结构化证据包，包含《影像元数据总台账.xlsx》、《SHA-256防篡改指纹校验清单.csv》及离线校验工具（`verify_evidence.py`、`verify_tool.html`）。

---

# 第6章 数据规范与存储规则

## 6.1 核心数据实体关系与任务发生实例模型

```mermaid
erDiagram
    plat_enterprise ||--o{{ biz_tenant_user : "拥有企业员工"
    plat_enterprise ||--o{{ biz_project : "拥有多个项目"
    plat_hazard_node_base ||--o{{ biz_tenant_node_ext : "派生企业扩展节点"
    biz_project ||--o{{ biz_hazard_entity : "危大实体/楼栋/部位实例"
    biz_project ||--o{{ biz_project_member : "项目成员角色(SZ/SP/SA)"
    biz_project_member ||--o{{ biz_project_member_hazard : "专监绑定多类危大"
    plat_hazard_node_base ||--o{{ biz_task_occurrence : "派生任务发生实例"
    biz_hazard_entity ||--o{{ biz_task_occurrence : "按楼栋/批次实例化"
    biz_task_occurrence ||--o{{ biz_media_evidence : "采集生成证据"
    biz_media_evidence }}o--o{{ biz_document : "图单多对多关联"
    biz_media_evidence ||--o{{ biz_hazard_rectification : "隐患_QZ/_HW双图"
    biz_hazard_rectification ||--o{{ biz_stop_work_order : "严重隐患停工令(A.0.5)"
    biz_stop_work_order ||--o{{ biz_document_delivery_record : "送达/拒收记录"
    biz_hazard_rectification ||--o{{ biz_authority_report_record : "建设单位/主管部门报告"
    biz_hazard_rectification ||--o{{ biz_rectification_review_round : "多轮复查记录"
    biz_hazard_rectification ||--o{{ biz_resumption_review : "复工申请与审查"
    biz_task_occurrence ||--o{{ biz_acceptance_signoff : "验收双签与标识公示"
    biz_acceptance_signoff ||--o{{ biz_process_gate_rule : "下一道工序门禁"
```

### 6.1.1 任务发生实例（Occurrence）与完整度计算规则
- `biz_task_occurrence` 包含 `occurrence_id`、`tenant_id`、`project_id`、`hazard_entity_id`、`node_uid`、`node_version_snapshot`、`scheme_version_snapshot`、`building_zone`、`batch_no`、`applicable_status`、`planned_due_at`、`assignee_id`、`workflow_status`；
- **完整度公式**：`已进入施工时点且已审核闭环的任务发生实例数 ÷ 当前已进入施工时点的应采任务发生实例总数 × 100%`（剔除“不适用”“未到工序时点”及全部 `PENDING_REVIEW` 待校审节点）。

## 6.2 标准化文件命名规则（全链路统一版）
- **影像命名公式**：`{{project_code}}_{{hazard_code}}_{{subcategory_code}}_{{stage_code}}_{{node_uid_suffix}}_{{risk_level}}_{{yyyyMMddHHmmss}}[_{{suffix}}].{{JPG|MP4}}`；
  - 示例：`TJ-2026-0089_04_SC03_01_01_★_20260612143218_QZ.JPG`
- **单据命名公式**：`{{project_code}}_{{hazard_code}}_{{subcategory_code}}_{{stage_code}}_{{node_uid_suffix}}_{{doc_code}}[_{{suffix}}].pdf`；
- 严禁中文空格、特殊符号与非唯一业务编号替代 `node_uid_suffix`。

## 6.3 分级分类存储周期与到期处置规则
- ★强制影像与隐患/应急影像执行课题/企业强制长期留存策略，配合 OSS WORM（1~25,550 天）合规保留与离线光盘归档；
- △常规巡视照片工程竣工后 1 年、视频工程竣工后 3 年，到期经销毁审批后执行脱敏清理并留存哈希封存记录；
- 原始取证文件与哈希记录严禁任何角色（含超管）修改或物理删除。

---

# 第7章 非功能性需求

## 7.1 性能与响应指标（统一口径版）
| 场景 | 指标项 | 达标阈值（P95，良好网络/中端测试机） |
|:---|:---|:---|
| 小程序冷启动 | 打开至待办首页 | ≤ 1.5 秒 |
| 小程序热启动 | 后台唤醒 | ≤ 0.5 秒 |
| 任务列表刷新 | 单页 20 条多维过滤 | ≤ 0.8 秒 |
| 水印合成 | 中端机 / 低端机 | ≤ 800ms / ≤ 1500ms |
| 单图上传 | 2~5MB 照片（4G良好） | ≤ 2.0 秒 |
| 原图加载 | 2~5MB 高清原图 | ≤ 2.5 秒 |
| 视频分片上传 | 60MB 视频（5MB分片，4G良好） | ≤ 20 秒 |
| 证据包异步打包 | 800MB 专项包 / 4GB 全项目包 | ≤ 60 秒 / ≤ 5 分钟 |

## 7.2 弱网、离线与高可用指标
- 纯离线业务可用度 100%，本地沙箱 150MB 字节硬配额；
- 大视频 5MB 分片断点续传，网络恢复自动 FIFO 排队；
- 全年系统可用率 ≥ 99.9%，核心业务 MTTR ≤ 30 分钟。

## 7.3 数据完整性与安全指标
- 入库、调阅、出证执行全文件 SHA-256 校验；
- OSS 对 ★强制与隐患闭环影像开启 WORM 合规保留策略；
- 服务器接入 NTP 授时，区分正常离线排队与设备时钟异常；
- 审计日志采用 Append-Only + 哈希链校验并定期归档至 OSS WORM。

## 7.4 网络安全与多租户越权防护
- 全站强制 HTTPS / TLS 1.2+，重要接口携带 Timestamp/Nonce/HMAC-SHA256 签名；
- 普通用户篡改 `project_id` 或 `media_guid` 时由 `TenantCRUDBase` 强制拦截并返回 403；
- 登录接口限流 10 次/分钟，普通查询 60 次/分钟。

## 7.5 微信小程序端专项体验指标
- 主包体积 ≤ 1.5MB，表单/历史调阅/看板拆分为独立分包；
- 连续拍摄内存峰值 ≤ 350MB，核心按钮高度 ≥ 48px，支持高对比度工地强光 UI。

## 7.7 个人信息保护与数据安全合规专节
1. **处理目的与最小必要**：仅收集与监理履职直接相关的工号、姓名、项目角色、拍摄时间、WGS-84 经纬度及必要设备环境信息，严禁采集无关通讯录、相册或后台持续定位；
2. **告知与授权**：首次登录展示《隐私政策与履职采集告知书》，明确采集目的、范围、保存期限与云服务委托处理关系，取得明示同意后调用相机与定位权限；
3. **保存期限与权利响应**：项目竣工或员工离职后按档案留存期限执行归档、脱敏或匿名化，个人权利请求通过企业管理员登记并留存处理轨迹；
4. **委托处理与跨主体调阅**：云服务委托处理签署数据处理协议，超管代管穿透必须填写授权依据、目的与范围，默认只读并全程审计；
5. **脱敏与泄露处置**：手机号、证件号、定位坐标在展示、日志与导出中按权限脱敏，异常访问立即冻结会话并启动安全事件响应；
6. **个人信息保护影响评估（PIPIA）**：试点上线前完成评估与法务专项复核，作为验收交付物之一。

---

# 第8章 原型页面清单与交互说明

## 8.1 页面架构与终端布局总览
| 序号 | 页面编码 | 页面名称 | 终端 | 核心功能定位 |
|:---:|:---|:---|:---|:---|
| 1 | P-MP-01 | 登录与租户/项目切换页 | 微信小程序 | 微信手机号授权登录、项目切换 |
| 2 | P-MP-02 | 现场采集待办工作台 | 微信小程序 | 清单化任务引导、★/△标记、离线同步条幅 |
| 3 | P-MP-03 | 节点详情与拍摄指引卡 | 微信小程序 | 拍摄要求、风险提示、范例照片 |
| 4 | P-MP-04 | 原生相机实时取证页 | 微信小程序 | 禁相册、双哈希水印、150MB字节配额拦截 |
| 5 | P-MP-05 | 元数据补充与提交页 | 微信小程序 | 单据胶囊标签(扫码/手动)、风险简述 |
| 6 | P-MP-06 | 专监移动审核与驳回页 | 微信小程序 | 原图预览、五维数据核验、审核/驳回 |
| 7 | P-MP-07 | 现场隐患发起与整改复查 | 微信小程序 | 隐患_QZ、复查_HW、双图同屏比对 |
| 8 | P-MP-08 | 总监移动审批与红黄灯看板 | 微信小程序 | 移动审批、停复工指令、逾期督办 |
| 9 | P-MP-09 | 弱网离线缓存与同步管理 | 微信小程序 | 150MB字节配额进度条、待传队列、断点重试 |
| 10 | P-PC-01 | 监理企业租户管理页 | platform-web | 企业入驻开通、ENT编码分配、状态控制、超管代管入口 |
| 11 | P-PC-02 | 课题标准采集节点基线库管理 | platform-web | 347条基线记录维护、源数据校审队列、版本管理 |
| 12 | P-PC-03 | 系统运行与审计日志总台账 | platform-web | 全局及代管审计日志检索、哈希链校验 |
| 13 | P-PC-04 | 本企业工程项目管理页 | tenant-web | 项目建档、B001编码、挂载危大类型 |
| 14 | P-PC-05 | 项目组织与成员配置页 | tenant-web | 指定总监、专监多危大绑定、成员调配 |
| 15 | P-PC-06 | 企业人员与账号管理页 | tenant-web | 账号开通、重置密码、工号绑定 |
| 16 | P-PC-07 | 危大节点任务发生实例看板 | tenant-web | 按楼栋/批次分派、进度横道图、时限调整 |
| 17 | P-PC-08 | 影像资料审核工作台 | tenant-web | 高清看图器、元数据核查、批量通过/驳回 |
| 18 | P-PC-09 | 隐患整改闭环台账管理 | tenant-web | 双图同屏比对、停工/报告/复工/多轮复查 |
| 19 | P-PC-10 | 核心监理表单填报与台账 | tenant-web | F01~F05填报、扫描件附件绑定 |
| 20 | P-PC-11 | 监理表单详情与打印导出 | tenant-web | GB/T 50319版式还原、二维码防伪、PDF导出 |
| 21 | P-PC-12 | 证据链完整度综合研判看板 | tenant-web | 应采/实采/缺项、★强制合规率、时效分析 |
| 22 | P-PC-13 | 四维证据链检索与目录调阅 | tenant-web | 四维穿透检索、五级目录树、SHA256印章核验 |
| 23 | P-PC-14 | 合规证据包导出与离线备份 | tenant-web | 全量导出ZIP包、SHA-256清单、光盘备份 |

## 8.2 微信小程序端底部导航栏（TabBar）结构规范
采用 **3 Tab 极简布局**：①【工作台】待办/采集；②【消息】提醒/告警；③【我的】资质/离线/项目切换。

---

# 第9章 验收标准与测试要点

## 9.1 功能验收用例（含法定履职全闭环）

| 用例编号 | 验收场景 | 预期输出与合格标准 | 优先级 |
|:---|:---|:---|:---:|
| TC-SYS-01 | 多租户入驻与路径隔离 | 所有业务表自动写入 `tenant_id`，OSS 按企业编码前缀逻辑隔离，跨租户访问返回 403 | P0 |
| TC-SYS-04 | 超级管理员受控代管穿透与只读审计 | 超管仅在 platform-web 发起代管，默认只读，原始证据禁改删，全程写入 `plat_privilege_audit_log` | P0 |
| TC-MOB-01 | 原生相机调用与彻底禁用相册 | 直接调用底层相机，无任何相册/本地文件导入入口 | P0 |
| TC-MOB-02 | 双哈希水印硬编码合成 | 水印包含 `media_guid` 与 `raw_frame_sha256` 前16位，归档 `file_sha256` 由服务端独立计算并锁定 | P0 |
| TC-OFF-02 | 本地沙箱 150MB 字节配额饱和拦截 | 达到 150MB 字节配额时阻断新拍摄，不触及微信 200MB 硬限制 | P0 |
| TC-SEC-01 | 文件字节被篡改（1-bit 翻转试验） | 全文件 SHA-256 比对不一致，展示红色【证据失效】印章并写入安全告警 | P0 |
| TC-SEC-04 | 定位异常与虚拟定位环境核验 | 记录定位精度、围栏距离与端侧状态，异常标记 `gps_status=4` 并高亮待人工核验，不虚构 100% 自动拦截 Fake GPS | P0 |
| **TC-REV-05** | **严重隐患停工令签发与送达** | 总监签发工程暂停令（A.0.5），明确停工范围，记录送达方式、签收/拒收凭据及时间戳 | P0 |
| **TC-REV-06** | **建设单位与住建主管部门报告闭环** | 情节严重时及时报告建设单位；拒不整改/拒不停工时独立报告住建主管部门，登记文号、附件与签收凭据 | P0 |
| **TC-REV-07** | **多轮复查与复工审查** | 支持多轮复查意见与 `_HW` 影像；停工状态下必须录入复工申请与条件核验，经总监审查后方可复工 | P0 |
| **TC-REV-08** | **验收双签、标识公示与下一道工序门禁** | 验收合格经施工单位技术负责人及总监双签并拍摄标识牌公示照片后，自动解锁下一道工序任务实例 | P0 |
| TC-EXP-02 | 证据包离线校验工具与清单 | ZIP 包含元数据台账.xlsx、SHA-256清单.csv、`verify_evidence.py` 与 `verify_tool.html`，支持纯离线校验 | P0 |

## 9.2 源数据业务校审验收
- `review_status=PENDING_REVIEW` 的节点不得进入正式强制采集任务与完整度考核分母；
- 每条校审记录必须包含审核人、审核依据、审核时间、处理结论与版本号；
- 原始内容错配（如附录 A-2 飞模表第 8 行）必须经业务专家确认后方可修订。

## 9.3 UAT 用户验收测试准入与准出标准
- P0/P1 缺陷 100% 清零，P2 缺陷解决率 ≥ 95%；
- 试点工程连续 30 天，已激活应采任务实例履职完整度 ≥ 95%，★强制节点履职率 100%；
- 离线数据网络恢复后同步成功率 100%，证据包第三方独立哈希校验匹配率 100%；
- 完成真机 PoC（离线容量、重启恢复、后台续传、全文件 SHA-256、OSS WORM 组合验证）与法务/隐私专项复核。

---

# 第10章 附录（标准对照、映射矩阵与修订说明）

## 10.1 附录一：危大工程 12 大分类与精确基线记录对照表（脚本复算版）

{category_table}

## 10.2 附录二：5 大核心监理表单族（F01~F05）与原始 Excel/GB/T 50319 映射对照表

{forms_table}

## 10.3 附录三：系统元数据 24 个标准编号字段与数据库物理字段映射全览表（SSOT 驱动版）

{field_table}

### 10.3.2 数据库内部扩展管理列（不占用 B 系列标准编号）

{ext_table}

## 10.4 附录四：典型影像元数据真实 JSON 示例（由种子库真实节点生成）

### 示例 1：已确认节点（CONFIRMED + ★）完整元数据（合成演示数据，example_data_status=SYNTHETIC）
```json
{json.dumps(example1, ensure_ascii=False, indent=2)}
```

### 示例 2：待校审节点（PENDING_REVIEW，不参与正式强制采集与完整度考核）
```json
{json.dumps(example2, ensure_ascii=False, indent=2)}
```

## 10.5 附录五：PRD 文档修订记录与全生命周期版本历史

| 版本 | 日期 | 核心修订内容 | 状态 |
|:---:|:---|:---|:---|
| v1.0 | 2026-10-19 | 原始 PRD 正式版 | 历史保留 |
| v2.0 | 2026-11-12 | 架构对齐版（平台/租户分离、Figma Make 衔接） | 历史保留 |
| v2.1 | 2026-11-13 | 首次评审整改版 | 历史保留 |
| v2.2 | 2026-11-15 | 节点唯一身份与原始数据溯源整改版 | 历史保留 |
| **v2.3** | **2026-11-15** | **真实 SSOT 驱动、业务准入状态拆分、法定履职全闭环验收用例与真实一致性校验** | **评审整改中** |

---

> **文档结束。**
"""

out_path = os.path.join(BASE_DIR, "docs", "PRD_v2.3_评审整改中.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(prd)
print(f"Successfully generated {out_path}: {len(prd.splitlines())} lines, {len(prd.encode('utf-8'))} bytes")
