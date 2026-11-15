"""
危大工程监理履职证据链系统 —— PRD/架构文档与基线数据真实一致性 CI 校验脚本（v1.4）
实际校验：节点唯一性、标准字段契约、GB/T 50319 表号正确性、PRD 示例真实性与跨字段一致性、命名公式一致性、架构文档旧规则、权限旧词、离线旧配额、性能口径与法定履职验收用例覆盖。
"""
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "docs", "baseline-data")
PRD_PATH = os.path.join(BASE_DIR, "docs", "PRD_v2.3_评审整改中.md")
ARCH_PATH = os.path.join(BASE_DIR, "docs", "system-architecture-design.md")

errors = []
checks = []

def check(name, condition, detail=""):
    checks.append({"check": name, "passed": bool(condition), "detail": detail})
    if not condition:
        errors.append(f"{name}: {detail}")

with open(os.path.join(OUT_DIR, "hazard_nodes_seed.json"), "r", encoding="utf-8") as f:
    seed = json.load(f)
with open(os.path.join(OUT_DIR, "metadata_and_forms_dictionary.json"), "r", encoding="utf-8") as f:
    dictionary = json.load(f)
with open(os.path.join(OUT_DIR, "validation_report.json"), "r", encoding="utf-8") as f:
    validation = json.load(f)
with open(PRD_PATH, "r", encoding="utf-8") as f:
    prd = f.read()
with open(ARCH_PATH, "r", encoding="utf-8") as f:
    arch = f.read()

nodes = seed['nodes']
node_map = {n['node_uid']: n for n in nodes}

# 1. 节点与字段结构校验
check("节点记录总数", len(nodes) == 347, f"实际 {len(nodes)}")
check("node_uid 全局唯一", len(set(node_map.keys())) == len(nodes), "存在重复 node_uid")
check("标准字段数量", len(dictionary['standard_metadata_fields']) == 24, f"实际 {len(dictionary['standard_metadata_fields'])}")
check("内部扩展字段数量", len(dictionary['internal_database_extensions']) == 28, f"实际 {len(dictionary['internal_database_extensions'])}")
check("业务准入状态拆分", all(k in validation for k in ['structural_status', 'source_review_status', 'business_readiness']), "验证报告缺少业务准入状态拆分")

# 2. 标准字段语义分离校验
field_map = {f['field_code']: f for f in dictionary['standard_metadata_fields']}
check("B004 语义为原始业务编号", field_map['B004']['column_name'] == 'legacy_node_code', field_map['B004']['column_name'])
check("B005 风险等级不混入UNSPECIFIED", field_map['B005']['data_type'] == 'CHAR(1)' and '仅允许★强制/△常规' in field_map['B005']['description'], field_map['B005']['description'])
check("B006 单文件介质仅照片/视频", '单个证据文件仅允许照片或视频' in field_map['B006']['description'], field_map['B006']['description'])
check("B301 统一为 file_sha256", field_map['B301']['column_name'] == 'file_sha256', field_map['B301']['column_name'])
check("B304 长度 VARCHAR(512)", field_map['B304']['data_type'] == 'VARCHAR(512)', field_map['B304']['data_type'])
check("B010 长度 VARCHAR(200)", field_map['B010']['data_type'] == 'VARCHAR(200)', field_map['B010']['data_type'])

# 3. GB/T 50319-2013 表号正确性校验（对应复审 P0-01）
form_map = {f['form_family_code']: f for f in dictionary['core_supervision_forms']}
check("F02 旁站记录表号 A.0.6", '表 A.0.6' in form_map['F02']['official_standard_mapping'], form_map['F02']['official_standard_mapping'])
check("F04 方案报审表号 B.0.1（非A.0.1）", '表 B.0.1' in form_map['F04']['official_standard_mapping'], form_map['F04']['official_standard_mapping'])
check("F05 监理通知单 A.0.3", '表 A.0.3' in form_map['F05']['official_standard_mapping'], form_map['F05']['official_standard_mapping'])
check("F05 工程暂停令 A.0.5（非A.0.4）", '表 A.0.5' in form_map['F05']['official_standard_mapping'], form_map['F05']['official_standard_mapping'])
check("F05 监理通知回复单 B.0.9（非B.0.5）", '表 B.0.9' in form_map['F05']['official_standard_mapping'], form_map['F05']['official_standard_mapping'])
# PRD 正文不得再出现旧错误表号组合
old_table_patterns = [
    (r"方案报审 A\.0\.1", "旧方案报审表号 A.0.1"),
    (r"暂停令 A\.0\.4", "旧暂停令表号 A.0.4"),
    (r"回复单 B\.0\.5", "旧回复单表号 B.0.5"),
]
for pattern, name in old_table_patterns:
    check(f"PRD 无残留：{name}", not re.search(pattern, prd), f"发现匹配: {re.findall(pattern, prd)}")

# 4. PRD 示例节点真实性与跨字段一致性校验
example_uids = re.findall(r'"node_uid":\s*"(WDGC-A-[^"]+)"', prd)
check("PRD 示例节点均真实存在", all(uid in node_map for uid in example_uids), f"不存在节点: {[u for u in example_uids if u not in node_map]}")
for uid in example_uids:
    node = node_map[uid]
    pattern = rf'"node_uid":\s*"{re.escape(uid)}".*?"review_status":\s*"([^"]+)"'
    m = re.search(pattern, prd, re.S)
    if m:
        check(f"示例 {uid} review_status 与种子库一致", m.group(1) == node['review_status'], f"PRD={m.group(1)}, seed={node['review_status']}")
    # 跨字段一致性：storage_path 必须包含节点真实 hazard_code 与 stage_code
    path_m = re.search(rf'"node_uid":\s*"{re.escape(uid)}".*?"storage_path":\s*"([^"]+)"', prd, re.S)
    if path_m:
        storage_path = path_m.group(1)
        check(f"示例 {uid} storage_path 包含真实 hazard_code={node['hazard_code']}", f"/{node['hazard_code']}_" in storage_path, storage_path)
        check(f"示例 {uid} storage_path 包含真实 stage_code={node['stage_code']}", f"/{node['stage_code']}_" in storage_path, storage_path)
    # 示例哈希必须显式标记为演示值，不得伪装为真实空字节串哈希
    check(f"示例 {uid} 哈希显式标记为演示值", 'demo_raw_frame_sha256_placeholder_not_real' in prd and 'demo_archive_file_sha256_placeholder_not_real' in prd, "示例哈希未显式标记为演示值")

# 5. 命名公式一致性校验
check("种子库命名公式包含 subcategory 与 node_uid_suffix", 'subcategory_code' in seed['metadata']['naming_formula'] and 'node_uid_suffix' in seed['metadata']['naming_formula'], seed['metadata']['naming_formula'])
check("PRD 命名公式与种子库一致", '{subcategory_code}' in prd and '{node_uid_suffix}' in prd, "PRD 命名公式缺少 subcategory_code 或 node_uid_suffix")

# 6. 架构文档一致性校验（对应复审 P0-02）
check("架构文档扩展列数量与字典一致(28)", '28 个内部扩展' in arch, "架构文档仍写25个扩展列")
check("架构文档使用 biz_task_occurrence 模型", 'biz_task_occurrence' in arch, "架构文档缺少 biz_task_occurrence")
check("架构文档无旧 biz_task_instance 核心任务模型", 'biz_task_instance' not in arch, "架构文档仍残留 biz_task_instance")
check("架构文档超管不得代替法定责任人签字", '超管不得代替法定责任人签字' in arch or '不得代替法定责任人' in arch, "架构文档仍保留超管代办法定审批能力")
check("架构文档命名使用 legacy_node_code 与 file_sha256", 'legacy_node_code' in arch and 'file_sha256' in arch, "架构文档仍使用旧 node_code/sha256_hash")

# 7. 权限旧词与离线旧配额残留扫描（排除第0章整改说明中的历史引用）
prd_body = prd[prd.find("# 第1章 文档说明"):]
legacy_patterns = [
    (r"PC端管理后台 \+ 微信小程序", "超管旧设备描述"),
    (r"放行全量", "超管全库放行旧规则"),
    (r"代管二次授权后终审", "超管代办法定终审旧规则"),
    (r"50张照片或5段", "离线旧配额"),
    (r"50 张照片或 5 段", "离线旧配额"),
    (r"PRJ-ENT001", "旧项目编码"),
    (r"法定永久保存", "绝对化保存期限"),
    (r"平台存证公信力声明", "绝对化公信力声明"),
]
for pattern, name in legacy_patterns:
    check(f"无残留：{name}", not re.search(pattern, prd_body), f"发现匹配: {re.findall(pattern, prd_body)}")

# 8. 法定履职验收用例覆盖校验
for tc in ['TC-REV-05', 'TC-REV-06', 'TC-REV-07', 'TC-REV-08']:
    check(f"法定履职验收用例 {tc} 存在", tc in prd, f"缺少 {tc}")
check("验收双签与下一道工序门禁用例", '验收双签' in prd and '下一道工序' in prd, "缺少验收门禁用例")
check("严重隐患停工与报告主管部门用例", '工程暂停令' in prd and '住建主管部门' in prd, "缺少严重隐患报告用例")

# 9. 非功能指标统一性校验
check("水印性能统一口径", '≤ 800ms / ≤ 1500ms' in prd, "水印性能指标未统一")
check("离线配额统一为150MB", '150MB' in prd_body, "缺少150MB字节配额")
check("EXIF 诚实建模", '不承诺完整相机厂商/焦距/快门' in prd, "仍承诺完整EXIF")
check("定位异常诚实建模", 'gps_status=4' in prd and '不虚构 100% 自动拦截 Fake GPS' in prd, "仍存在绝对化FakeGPS拦截承诺")

# 10. 隐私合规专节校验
check("个人信息保护专节存在", '## 7.7 个人信息保护与数据安全合规专节' in prd, "缺少7.7节")
check("PIPIA 与法务复核要求", '个人信息保护影响评估' in prd and '法务专项复核' in prd, "缺少PIPIA要求")

# 输出校验报告
result = {
    "structural_status": "PASS" if not errors else "FAIL",
    "checks_passed": sum(1 for c in checks if c['passed']),
    "checks_total": len(checks),
    "errors": errors,
    "checks": checks
}
with open(os.path.join(OUT_DIR, "prd_consistency_report.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("=" * 70)
print(f"PRD/架构文档与基线数据一致性 CI 校验: {result['checks_passed']}/{result['checks_total']} 项通过")
if errors:
    print("❌ 校验失败项:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("✅ 全部一致性校验通过！")
print("=" * 70)
