# PRD v2.3 业务校审与技术 PoC 清单复查报告

| 项目 | 内容 |
| :--- | :--- |
| 报告编号 | WDGC-BUSINESS-POC-CHECKLIST-REVIEW-20261115 |
| 呈送对象 | 产品负责人、技术负责人、业务校审负责人、测试负责人 |
| 评审仓库 | `wufujun2000/wdgc-supervision-evidence` |
| 本轮产品提交 | `a31f710beaa0649ef560842a824ec7febca15783`、`ab8c8d9e3ac5d2c84683bb0edcc5ff0c42e16042` |
| 对照评审提交 | `36f7a7bb8aeae5e412921921164952df46fdb911` |
| 复查日期 | 2026-11-15 |
| 总体结论 | **静态文档与示例整改通过；校审/PoC 清单作为工作模板通过；校审结果持久化与综合准入门控尚未通过，继续维持 BLOCKED。** |

---

## 一、复查范围与实测结果

本轮包含两次产品提交：

1. 完成示例命名、CI 和文档收尾；
2. 新增《源数据业务校审工作清单》和《真机与云服务质量属性 PoC 验证清单》。

本次实际重跑：

```bash
python3 scripts/generate_baseline_data.py
python3 scripts/generate_prd_v23.py
python3 scripts/validate_prd_consistency.py
```

实测结果：

- 347 条基线记录、347 个唯一 `node_uid`；
- **93/93 项一致性校验通过**；
- 重跑后产品文件无 Git 差异；
- 示例哈希、合成数据标识、待审文件标记及隔离状态规则已形成；
- 业务校审和 PoC 清单覆盖角色、步骤、完成标准、证据及报告模板。

需要明确：两份清单目前都是**待执行模板**，表格和签认栏为空，不能据此认定业务校审、真机测试、PoC 或法务复核已经完成。

---

## 二、上一轮剩余项核销

| 上轮事项 | 本轮判定 | 说明 |
| :--- | :--- | :--- |
| 待审示例使用 UNSPECIFIED 文件名 | **已闭环** | 新增独立 `risk_file_token=PENDING` 与 `QUARANTINED` 隔离状态 |
| 示例合成属性表述 | **已闭环** | 标题及字段均明确为 SYNTHETIC |
| CI 无效 UID 导致变量误用 | **已闭环** | 无效 UID 后直接记录错误并跳过当前示例 |
| 校验成功提示为失败文案 | **已闭环** | 成功时输出对应检查名称 |
| README/架构旧校验数量 | **形式修正，仍需维护方式改进** | 37 已改为 91，但实际报告已为 93，建议不再硬编码数量 |
| 业务校审工作指引 | **模板已建立** | 尚无实际专家签认结果 |
| 真机与 PoC 工作指引 | **模板已建立** | 尚无实际测试记录与证据 |

---

## 三、P0：执行校审前必须修复

### P0-01：重跑生成脚本会覆盖专家校审结果

**位置：**

- `docs/verification/business-source-review-checklist.md` 第 89～92、134 行；
- `scripts/generate_baseline_data.py` 第 154、173、182～195、234～237 行。

校审清单要求：

> 将审核结果回填 `source_data_review_log.json`，再重新运行生成与校验脚本。

但当前生成脚本每次都会：

1. 从原始 Word 重新计算 `PENDING_REVIEW`；
2. 重建 `review_logs`；
3. 将 `reviewer/reviewed_at/review_basis/resolution` 全部置为 `null`；
4. 覆盖写入 `source_data_review_log.json`。

脚本没有读取或合并既有审核结果。因此按当前清单操作，**专家确认结果可能被重跑覆盖，不能形成持久化校审闭环。**

**整改建议：**

- 将 `source_data_review_log.json` 定义为派生输出，不直接手工编辑；
- 新增独立、受版本控制的 `source_review_decisions.json` 作为人工决策输入；
- 以 `(node_uid, issue_type, source_fingerprint)` 关联审核决定；
- 生成器读取并合并人工决定，输出“待审/已确认/已驳回”完整台账；
- 原始内容变化导致指纹变化时，应使旧审核失效并重新校审；
- 增加“回填一条测试决定→重跑→决定仍保留”的回归测试。

### P0-02：综合业务准入门控目前只检查待审数量

**位置：**`scripts/generate_baseline_data.py` 第 325～338 行。

当前逻辑为：

```python
business_readiness = "BLOCKED" if pending_count > 0 else "READY"
```

这意味着只要 331 条节点全部确认，即使 PoC、法务、隐私和一致性验证没有完成，脚本也会自动输出 `READY`。这与 README、PRD 和两份清单所声明的综合准入条件不一致。

**整改建议：**分别维护并汇总以下门禁：

- `source_review_status`；
- `static_consistency_status`；
- `technical_poc_status`；
- `compliance_review_status`；
- `behavioral_acceptance_status`。

只有全部明确通过后，综合 `business_readiness` 才能为 `READY`。在缺少实测证据时应保持 `BLOCKED` 或 `PENDING_EVIDENCE`，不得仅由节点数量推导就绪。

---

## 四、P1：契约与测试设计需要补充

### P1-01：示例新增字段尚未进入字段契约

两个示例新增：

- `risk_file_token`；
- `evidence_admission_status`。

但 `metadata_and_forms_dictionary.json` 的 24 个标准字段和 28 个内部扩展列均未定义这两个字段。当前 CI 只检查示例字段值，没有检查示例字段是否属于已知契约。

建议明确：

- 若为数据库持久化字段，应加入内部扩展字典并同步数量、ER 和架构；
- 若为服务端派生/API 字段，应新增 `api_response_fields` 或“派生只读字段”分组，不必强行增加数据库列；
- `example_data_status`、`business_gate_note` 可声明为文档注释字段，不应误存入证据表；
- CI 增加“示例字段均已分类登记”的检查。

### P1-02：驳回节点的风险等级规则存在冲突

校审清单第 16、70 行允许 `REJECTED_WITH_REASON`，但第 66 行又要求每条记录不得留空，只能填 ★/△。

对于“一期不适用”或“驳回”的节点，合理规则应是：

- `review_status=REJECTED_WITH_REASON`；
- `risk_level=null`；
- 不进入正式应采任务与完整度分母；
- 必须填写驳回理由、审核人和依据。

不应为了满足字段非空而给驳回节点强行分配风险等级。

### P1-03：哈希篡改用例与 WORM 保护用例需要隔离

PoC 清单第 89～100 行要求：

- 在 OSS 中修改已入库照片 1 个字节，再验证哈希告警；
- 同时对 ★强制影像启用 WORM，验证无法覆盖。

WORM 保护生效时，覆盖/修改操作本身应被阻止，可能无法进入后续哈希比对流程。建议拆分：

1. **完整性测试：**在非 WORM 测试桶、测试副本或本地取证样本中修改字节，验证全文件哈希检测；
2. **不可变性测试：**在真实 WORM 对象上执行覆盖/删除，验证 OSS 拒绝；
3. 记录两种测试各自证明的能力，不把“存储拒绝篡改”和“系统检测篡改”混为一个用例。

---

## 五、P2：减少人工维护校验数量

当前实际报告为 93/93，但 README 和架构仍写 91。该问题已连续出现，说明硬编码数量不适合持续协作。

建议统一写为：

> 一致性校验全部通过，具体数量以 `docs/baseline-data/prd_consistency_report.json` 的 `checks_passed/checks_total` 为准。

如确需展示数字，应由脚本生成 README 摘要，避免每次新增断言后再次产生文档漂移。

---

## 六、下一阶段执行顺序

1. **先修校审持久化与综合准入门控**，否则专家工作和准入状态不可靠；
2. 明确新增示例字段是数据库列、API 派生字段还是文档注释；
3. 修正驳回节点风险规则和 WORM/哈希测试隔离；
4. 由业务专家实际完成目标 MVP 最小节点集校审并签认；
5. 按 PoC 清单执行真机、双租户、OSS/WORM、离线和行为级测试，提交原始证据；
6. 完成法务、隐私和档案复核后，再申请综合开发准入复审。

---

## 七、最终复查意见

**本轮静态文档整改和两份工作清单的编制质量可以认可，上一轮局部示例及 CI 问题已基本闭环。**

当前不应再把主要精力放在 PRD 文字修订上，但也不能直接开始按清单回填数据：必须先解决“校审结果会被生成器覆盖”和“待审归零即自动 READY”两个执行阻断问题。

建议状态继续保持：

- `structural_status=PASS`；
- `static_consistency_status=PASS`；
- `source_review_status=PENDING`；
- `technical_poc_status=PENDING`；
- `compliance_review_status=PENDING`；
- `business_readiness=BLOCKED`。
