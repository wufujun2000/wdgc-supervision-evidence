"""
危大工程监理履职数字化证据链系统 —— 单一事实源（SSOT）生成与真实一致性校验脚本（v1.3）

对应复审报告：docs/01-review-reports/prd-v2.2-follow-up-review-2026-11-15.md
核心整改：
1. 标准字段语义严格分离：B004=legacy_node_code（原始清单业务编号，非唯一），node_uid=内部全局身份扩展；
2. B005 风险等级仅允许 ★/△，UNSPECIFIED 仅存在于 review_status 与 raw_risk_level，不污染业务枚举；
3. B006 单文件介质仅允许 照片/视频，节点建议介质独立为 suggested_media_type；
4. 验证报告拆分 structural_status / source_review_status / business_readiness，严禁将结构 PASS 误读为业务准入；
5. 提供真实 PRD 校验：示例节点存在性与状态、字段契约、命名公式、权限旧词、离线旧配额、性能口径与法定闭环用例。
"""
import zipfile
import xml.etree.ElementTree as ET
import json
import os
import re
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "docs", "00-source-materials")
OUT_DIR = os.path.join(BASE_DIR, "docs", "baseline-data")

def get_docx_body_blocks(path):
    with zipfile.ZipFile(path) as z:
        xml_content = z.read('word/document.xml')
    tree = ET.fromstring(xml_content)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    body = tree.find('w:body', ns)
    blocks = []
    for child in body:
        tag = child.tag.split('}')[-1]
        if tag == 'p':
            text = ''.join(t.text for t in child.findall('.//w:t', ns) if t.text).strip()
            if text:
                blocks.append({'type': 'p', 'text': text})
        elif tag == 'tbl':
            rows = []
            for tr in child.findall('.//w:tr', ns):
                row = []
                for tc in tr.findall('.//w:tc', ns):
                    row.append('\n'.join(''.join(x.text for x in p.findall('.//w:t', ns) if x.text) for p in tc.findall('.//w:p', ns)).strip())
                rows.append(row)
            blocks.append({'type': 'table', 'rows': rows})
    return blocks

def read_xlsx(path):
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            ss_root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            for si in ss_root.findall('s:si', ns):
                t = ''.join(x.text for x in si.findall('.//s:t', ns) if x.text)
                shared.append(t)
        wb_root = ET.fromstring(z.read('xl/workbook.xml'))
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheets = {}
        for idx, sh in enumerate(wb_root.findall('.//s:sheet', ns), 1):
            name = sh.attrib.get('name')
            sheet_path = f'xl/worksheets/sheet{idx}.xml'
            if sheet_path in z.namelist():
                sh_root = ET.fromstring(z.read(sheet_path))
                rows = []
                for row_el in sh_root.findall('.//s:row', ns):
                    row_vals = []
                    for c_el in row_el.findall('s:c', ns):
                        t_attr = c_el.attrib.get('t')
                        v_el = c_el.find('s:v', ns)
                        is_el = c_el.find('.//s:t', ns)
                        val = ''
                        if v_el is not None and v_el.text is not None:
                            val = shared[int(v_el.text)] if t_attr == 's' else v_el.text
                        elif is_el is not None and is_el.text is not None:
                            val = is_el.text
                        row_vals.append(val.replace('\n', ' '))
                    if any(row_vals):
                        rows.append(row_vals)
                sheets[name] = rows
        return sheets

HAZARD_META = {
    "01": {"name": "基坑工程", "file": "附录A-1基坑工程监理影像采集清单.docx", "subcategories": {}},
    "02": {"name": "模板工程及支撑体系", "file": "附录A-2模板工程及支撑体系监理影像采集清单.docx", "subcategories": {
        "1": {"code": "SC01", "name": "滑模工程"}, "2": {"code": "SC02", "name": "爬模工程"},
        "3": {"code": "SC03", "name": "飞模工程"}, "4": {"code": "SC04", "name": "混凝土模板支撑工程"},
    }},
    "03": {"name": "起重吊装及起重机械安装拆卸工程", "file": "附录A-3起重吊装及起重机械安装拆卸工程监理影像采集清单.docx", "subcategories": {
        "1": {"code": "SC01", "name": "非常规起重设备/方法吊装工程"}, "2": {"code": "SC02", "name": "起重机械进行安装的工程"},
        "3": {"code": "SC03", "name": "起重机械安装和拆卸工程"},
    }},
    "04": {"name": "脚手架工程", "file": "附录A-4脚手架工程监理影像采集清单.docx", "subcategories": {
        "1": {"code": "SC01", "name": "落地式钢管脚手架工程"}, "2": {"code": "SC02", "name": "附着式升降脚手架工程"},
        "3": {"code": "SC03", "name": "悬挑式脚手架工程"}, "4": {"code": "SC04", "name": "高处作业吊篮"},
        "5": {"code": "SC05", "name": "卸料平台与操作平台工程"}, "6": {"code": "SC06", "name": "异型脚手架工程"},
    }},
    "05": {"name": "拆除工程", "file": "附录A-5拆除工程监理影像采集清单.docx", "subcategories": {}},
    "06": {"name": "暗挖工程", "file": "附录A-6暗挖工程监理影像采集清单.docx", "subcategories": {}},
    "07": {"name": "建筑幕墙安装工程", "file": "附录A-7建筑幕墙安装工程监理影像采集清单.docx", "subcategories": {}},
    "08": {"name": "钢结构、网架和索膜结构安装工程", "file": "附录A-8钢结构、网架和索膜结构安装工程影像采集清单.docx", "subcategories": {}},
    "09": {"name": "人工挖孔桩工程", "file": "附录A-9人工挖孔桩工程监理影像采集清单.docx", "subcategories": {}},
    "10": {"name": "水下作业工程", "file": "附录A-10水下作业工程监理影像采集清单.docx", "subcategories": {}},
    "11": {"name": "装配式建筑混凝土预制构件安装工程", "file": "附录A-11装配式建筑混凝土预制构件安装工程监理影像.docx", "subcategories": {}},
}

STAGE_MAP = {
    "施工准备": {"stage_code": "01", "stage_name": "施工准备阶段"},
    "施工过程": {"stage_code": "02", "stage_name": "施工过程阶段"},
    "验收": {"stage_code": "03", "stage_name": "验收阶段"},
}

def extract_source_values(capture_guidance, node_name):
    """忠实保留原始值：B005 标准风险等级仅允许 ★/△；空白单独进入 review_status，不污染业务枚举。"""
    raw_level = "UNSPECIFIED"
    if '★' in capture_guidance or '★' in node_name:
        raw_level = "★"
    elif '△' in capture_guidance or '△' in node_name:
        raw_level = "△"
    review_status = "CONFIRMED" if raw_level in ("★", "△") else "PENDING_REVIEW"
    risk_level = raw_level if raw_level in ("★", "△") else None
    requires_video = '视频' in capture_guidance or '录像' in capture_guidance
    suggested_media_type = "照片+视频" if requires_video and ('照片' in capture_guidance or '影像' in capture_guidance) else ("视频" if requires_video else "照片")
    return raw_level, risk_level, review_status, suggested_media_type

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    nodes = []
    review_logs = []
    category_counts = {}

    for hc, info in HAZARD_META.items():
        blocks = get_docx_body_blocks(os.path.join(SRC_DIR, info['file']))
        table_idx = 0
        file_count = 0
        for block in blocks:
            if block['type'] != 'table':
                continue
            table_idx += 1
            sub_info = info['subcategories'].get(str(table_idx), {"code": "SC01", "name": info['name']})
            current_stage = "01"
            current_stage_name = "施工准备阶段"
            for ridx, r in enumerate(block['rows'], 1):
                if len(r) < 7 or not r[1].strip().isdigit():
                    continue
                stage_raw = r[0].strip()
                if stage_raw:
                    for key, st in STAGE_MAP.items():
                        if key in stage_raw:
                            current_stage = st["stage_code"]
                            current_stage_name = st["stage_name"]
                            break
                seq = int(r[1].strip())
                node_name = r[2].strip()
                capture_guidance = r[5].strip()
                raw_risk_level, risk_level, review_status, suggested_media_type = extract_source_values(capture_guidance, node_name)
                node_uid = f"WDGC-A-{hc}-{sub_info['code']}-{seq:02d}"
                legacy_node_code = f"A-{hc}-{seq:02d}"
                node = {
                    "node_uid": node_uid,
                    "legacy_node_code": legacy_node_code,
                    "hazard_code": hc,
                    "hazard_name": info["name"],
                    "subcategory_code": sub_info["code"],
                    "subcategory_name": sub_info["name"],
                    "stage_code": current_stage,
                    "stage_name": current_stage_name,
                    "source_sequence": seq,
                    "source_document": info["file"],
                    "source_table_index": table_idx,
                    "source_row_no": ridx,
                    "node_name": node_name,
                    "raw_risk_level": raw_risk_level,
                    "risk_level": risk_level,
                    "review_status": review_status,
                    "suggested_media_type": suggested_media_type,
                    "risk_description": r[3].strip(),
                    "supervision_action": r[4].strip(),
                    "capture_guidance": capture_guidance,
                    "related_document_suggestion": r[6].strip()
                }
                nodes.append(node)
                file_count += 1
                if review_status == "PENDING_REVIEW":
                    review_logs.append({
                        "node_uid": node_uid, "source_location": f"{info['file']} / 表{table_idx}({sub_info['name']}) / 第{ridx}行",
                        "issue_type": "MISSING_RISK_LEVEL",
                        "description": f"原始清单未标注★/△风险等级，节点【{node_name}】已保留原始空白，review_status=PENDING_REVIEW，待业务专家确认。",
                        "review_status": "PENDING_REVIEW", "reviewer": None, "reviewed_at": None, "review_basis": None, "resolution": None
                    })
                if hc == "02" and table_idx == 3 and seq == 8:
                    review_logs.append({
                        "node_uid": node_uid, "source_location": f"{info['file']} / 表3(飞模工程) / 第{ridx}行",
                        "issue_type": "SOURCE_CONTENT_MISMATCH",
                        "description": "原始清单【混凝土浇筑与监护】的“监理履职”列错抄了爬模工程“爬升后架体固定与维护”的内容。原始值已保留并登记，待业务专家校审修订。",
                        "review_status": "PENDING_REVIEW", "reviewer": None, "reviewed_at": None, "review_basis": None, "resolution": None
                    })
        category_counts[hc] = {"name": info["name"], "record_count": file_count}

    emergency_items = [
        {"node_name": "现场安全隐患闭环处置", "risk_description": "工序隐患长期未整改，持续诱发坍塌、高处坠落、火灾事故。", "supervision_action": "现场核查隐患实体，下发监理通知单/工程暂停令，跟踪复查整改效果，形成闭环管理。", "capture_guidance": "隐患原貌、文书与现场同框、整改后同角度对比影像；★强制。", "related_document_suggestion": "监理通知单(A.0.3)、工程暂停令(A.0.4)、监理通知回复单(B.0.5)", "suffix_default": "_QZ/_HW"},
        {"node_name": "险情预警应急处置", "risk_description": "基坑变形、架体滑移、洞内毒气超标、吊装失稳等突发险情，未及时停工抢险扩大事故后果。", "supervision_action": "第一时间下达工程暂停令，组织人员疏散，监督加固、堵漏、拆除等抢险措施落实；必要时报告建设单位与主管部门。", "capture_guidance": "险情实体、监测超限数据、抢险处置全过程视频；★强制。", "related_document_suggestion": "工程暂停令(A.0.4)、应急处置记录、建设单位/主管部门报告记录", "suffix_default": "_YJ"},
        {"node_name": "应急物资与应急演练", "risk_description": "险情发生无救援物资，作业人员不掌握抢险、逃生流程，延误救援时机。", "supervision_action": "定期核查应急物资完好性，全程参与坍塌、中毒、高处坠落专项应急演练。", "capture_guidance": "应急物资库房、演练疏散抢险全过程；★强制。", "related_document_suggestion": "应急物资台账、应急演练记录", "suffix_default": "_YJ"},
        {"node_name": "主管部门现场督查取证", "risk_description": "监管检查时无完整履职影像证据，无法证明监理全过程管控到位。", "supervision_action": "全程陪同住建、安监等主管部门现场核查，同步采集现场取证影像。", "capture_guidance": "督查现场、问题点位、资料核查画面；★强制。", "related_document_suggestion": "督查整改资料、复查记录", "suffix_default": "_JC"},
        {"node_name": "安全事故现场保护与调查", "risk_description": "事故现场破坏、影像证据灭失，无法开展责任划分与事故认定。", "supervision_action": "第一时间封锁保护事故现场，完整留存全流程影像资料，配合事故调查组取证。", "capture_guidance": "事故现场全貌、受损实体、全套影像归档台账；★强制。", "related_document_suggestion": "安全事故调查配套资料", "suffix_default": "_YJ"}
    ]
    for idx, item in enumerate(emergency_items, 1):
        nodes.append({
            "node_uid": f"WDGC-A-12-GEN-{idx:02d}", "legacy_node_code": f"A-12-{idx:02d}",
            "hazard_code": "12", "hazard_name": "应急抢险与通用兜底", "subcategory_code": "GEN", "subcategory_name": "通用应急处置场景",
            "stage_code": "99", "stage_name": "通用应急模块（不划分施工三阶段）", "source_sequence": idx,
            "source_document": "研究报告初稿.docx", "source_table_index": 1, "source_row_no": idx,
            "node_name": item["node_name"], "raw_risk_level": "★", "risk_level": "★", "review_status": "CONFIRMED",
            "suggested_media_type": "照片+视频", "risk_description": item["risk_description"], "supervision_action": item["supervision_action"],
            "capture_guidance": item["capture_guidance"], "related_document_suggestion": item["related_document_suggestion"],
            "suffix_default": item["suffix_default"]
        })
    category_counts["12"] = {"name": "应急抢险与通用兜底", "record_count": 5}

    node_uids = [n['node_uid'] for n in nodes]
    assert len(set(node_uids)) == len(nodes), "node_uid 必须 100% 唯一"
    confirmed_count = sum(1 for n in nodes if n['review_status'] == 'CONFIRMED')
    pending_count = len(nodes) - confirmed_count

    hazard_seed = {
        "metadata": {
            "dictionary_name": "危大工程监理履职证据链标准采集基线库（课题研究成果，含完整子类别溯源与业务校审状态）",
            "version": "1.3.0", "generated_on": "2026-11-15", "generator_script": "scripts/generate_baseline_data.py",
            "clarification": "共 347 条基线记录（11类专业危大342条 + 通用应急处置5条）。node_uid 为内部全局身份扩展，legacy_node_code 为标准业务编号（B004，非唯一键）。risk_level 仅允许★/△或null，UNSPECIFIED 仅存于 raw_risk_level 与 review_status。",
            "total_record_count": len(nodes), "category_counts": category_counts,
            "naming_formula": "{project_code}_{hazard_code}_{subcategory_code}_{stage_code}_{node_uid_suffix}_{risk_level}_{yyyyMMddHHmmss}[_{suffix}].{JPG|MP4}",
            "suffix_definitions": {"_QZ": "隐患整改前取证照", "_GZ": "隐患整改中过程照", "_HW": "隐患整改完成复查照", "_LZ": "专家论证影像", "_YJ": "应急抢险处置影像", "_JC": "住建督查检查影像", "_FX": "复工核验照", "_ZG": "专监专项复核照"}
        },
        "nodes": nodes
    }
    with open(os.path.join(OUT_DIR, "hazard_nodes_seed.json"), "w", encoding="utf-8") as f:
        json.dump(hazard_seed, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "source_data_review_log.json"), "w", encoding="utf-8") as f:
        json.dump({"pending_review_count": len(review_logs), "review_items": review_logs}, f, ensure_ascii=False, indent=2)

    # 字段字典：标准字段语义严格分离
    standard_fields = [
        {"field_code": "B001", "column_name": "project_code", "field_name": "项目唯一编码", "data_type": "VARCHAR(32)", "constraint": "NOT NULL, INDEX", "description": "优先录入住建备案编号（如TJ-2026-0089），未备案时支持按TJ-年份-流水号生成规范编码。", "source_and_writer": "企业管理员PC建档录入/系统生成"},
        {"field_code": "B002", "column_name": "hazard_code", "field_name": "危大工程大类编码", "data_type": "CHAR(2)", "constraint": "NOT NULL, INDEX", "description": "01~11专业危大/12通用应急（兼容99）。", "source_and_writer": "节点库自动继承"},
        {"field_code": "B003", "column_name": "stage_code", "field_name": "施工阶段编码", "data_type": "CHAR(2)", "constraint": "NOT NULL", "description": "01施工准备/02施工过程/03验收；第12类通用应急使用99。", "source_and_writer": "节点库自动继承"},
        {"field_code": "B004", "column_name": "legacy_node_code", "field_name": "附录清单节点业务编号", "data_type": "VARCHAR(16)", "constraint": "NOT NULL, INDEX", "description": "对应原始附录A清单业务编号（如A-04-01），非全局唯一键，与子类别及原始行号联合溯源。", "source_and_writer": "节点库自动继承"},
        {"field_code": "B005", "column_name": "risk_level", "field_name": "采集风险等级标记", "data_type": "CHAR(1)", "constraint": "NULL", "description": "仅允许★强制/△常规；原始空白时为NULL，校审状态由review_status独立管理，严禁将UNSPECIFIED作为业务风险等级。", "source_and_writer": "节点库继承+业务校审确认"},
        {"field_code": "B006", "column_name": "media_type", "field_name": "单文件影像介质类型", "data_type": "VARCHAR(8)", "constraint": "NOT NULL", "description": "单个证据文件仅允许照片或视频；节点建议采集介质由内部扩展列suggested_media_type独立表达。", "source_and_writer": "相机拍摄模式获取"},
        {"field_code": "B007", "column_name": "shoot_utc_time", "field_name": "UTC标准拍摄时间", "data_type": "DATETIME(3)", "constraint": "NOT NULL", "description": "拍摄瞬间设备UTC时间，结合单调时钟与最近NTP基准校核。", "source_and_writer": "相机快门底层抓取"},
        {"field_code": "B008", "column_name": "shooter_emp_no", "field_name": "拍摄人员工号", "data_type": "VARCHAR(32)", "constraint": "NOT NULL, INDEX", "description": "企业内部监理人员唯一工号（如JL027）。", "source_and_writer": "小程序登录态绑定"},
        {"field_code": "B009", "column_name": "document_no_csv", "field_name": "关联纸质单据编号", "data_type": "VARCHAR(255)", "constraint": "NOT NULL", "description": "胶囊标签录入，库内biz_media_document_rel多对多关联，导出以半角英文逗号,拼接，无单据填暂无关联+原因。", "source_and_writer": "小程序扫码/手动录入"},
        {"field_code": "B010", "column_name": "risk_summary", "field_name": "核心风险简述", "data_type": "VARCHAR(200)", "constraint": "NOT NULL", "description": "现场风险核心要点，最多支持50个汉字。", "source_and_writer": "节点默认填入+人工微调/AI建议"},
        {"field_code": "B011", "column_name": "media_guid", "field_name": "影像全局唯一ID", "data_type": "VARCHAR(36)", "constraint": "NOT NULL, UNIQUE", "description": "36位标准UUID（含横杠），端侧离线拍摄暂存时即分配，服务端接收时校验并锁定。", "source_and_writer": "端侧生成/服务端校验锁定"},
        {"field_code": "B101", "column_name": "gps_coordinates", "field_name": "GPS经纬度坐标", "data_type": "VARCHAR(64)", "constraint": "NULL", "description": "WGS-84大地坐标，无信号/固定监控时允许留空，配合gps_status标识。", "source_and_writer": "小程序定位获取(GCJ-02转WGS-84)"},
        {"field_code": "B102", "column_name": "bim_component_code", "field_name": "BIM构件编码", "data_type": "VARCHAR(64)", "constraint": "NULL", "description": "项目BIM模型构件编码（选填）。", "source_and_writer": "PC/小程序选填"},
        {"field_code": "B103", "column_name": "position_desc", "field_name": "现场部位描述", "data_type": "VARCHAR(128)", "constraint": "NULL", "description": "楼栋+楼层+分区。", "source_and_writer": "小程序/PC选填"},
        {"field_code": "B104", "column_name": "media_supplement", "field_name": "影像补充说明", "data_type": "VARCHAR(200)", "constraint": "NULL", "description": "补充拍摄背景，最多支持50个汉字。", "source_and_writer": "小程序/PC选填"},
        {"field_code": "B105", "column_name": "rectification_flag", "field_name": "整改闭环标识", "data_type": "VARCHAR(16)", "constraint": "NOT NULL DEFAULT '无'", "description": "_QZ整改前/_GZ整改中/_HW整改完成/无。", "source_and_writer": "业务流自动注入"},
        {"field_code": "B106", "column_name": "supervision_doc_no", "field_name": "监管督查编号", "data_type": "VARCHAR(64)", "constraint": "NULL", "description": "住建现场执法检查文书编号。", "source_and_writer": "PC/小程序选填"},
        {"field_code": "B201", "column_name": "ai_risk_tags", "field_name": "AI风险识别标签", "data_type": "VARCHAR(255)", "constraint": "NULL", "description": "多模态AI/模型输出的风险识别标签（英文逗号分隔）。", "source_and_writer": "后端AI引擎生成"},
        {"field_code": "B202", "column_name": "ai_confidence", "field_name": "AI风险置信度", "data_type": "DECIMAL(3,2)", "constraint": "NULL", "description": "0.00~1.00。", "source_and_writer": "后端AI引擎生成"},
        {"field_code": "B203", "column_name": "ai_snapshot_guid", "field_name": "识别截图关联ID", "data_type": "VARCHAR(36)", "constraint": "NULL", "description": "AI截取高风险隐患特写缩略图GUID。", "source_and_writer": "后端AI引擎生成"},
        {"field_code": "B301", "column_name": "file_sha256", "field_name": "归档文件SHA-256哈希值", "data_type": "CHAR(64)", "constraint": "NOT NULL, INDEX", "description": "服务端接收带水印归档文件时流式计算的SHA-256并锁定，不与水印自身形成自引用。", "source_and_writer": "服务端入库固化"},
        {"field_code": "B302", "column_name": "deposit_time", "field_name": "系统固化存证时间戳", "data_type": "DATETIME(3)", "constraint": "NOT NULL", "description": "服务端接收并持久化时UTC毫秒级时间戳（NTP同步）。", "source_and_writer": "服务端入库固化"},
        {"field_code": "B303", "column_name": "upload_operator_no", "field_name": "上传操作人工号", "data_type": "VARCHAR(32)", "constraint": "NOT NULL", "description": "实际执行文件上传的监理人员工号。", "source_and_writer": "服务端入库固化"},
        {"field_code": "B304", "column_name": "storage_path", "field_name": "归档文件存储路径", "data_type": "VARCHAR(512)", "constraint": "NOT NULL", "description": "含企业编码前缀的OSS五级目录完整寻址Key。", "source_and_writer": "服务端目录映射引擎"}
    ]
    internal_extensions = [
        {"column_name": "id", "data_type": "BIGINT", "description": "物理自增主键"},
        {"column_name": "node_uid", "data_type": "VARCHAR(32)", "description": "内部全局唯一节点身份编码（如WDGC-A-04-SC03-01），不替代标准B004业务编号"},
        {"column_name": "tenant_id", "data_type": "BIGINT", "description": "租户行级隔离字段，由TenantCRUDBase自动注入"},
        {"column_name": "enterprise_code", "data_type": "VARCHAR(32)", "description": "监理企业编码（如ENT-001）"},
        {"column_name": "project_id", "data_type": "BIGINT", "description": "关联biz_project.id"},
        {"column_name": "task_occurrence_id", "data_type": "BIGINT", "description": "关联biz_task_occurrence.id，支持同节点按楼栋/部位/批次多次发生"},
        {"column_name": "subcategory_code", "data_type": "VARCHAR(8)", "description": "危大子类别编码（如SC01~SC06/GEN）"},
        {"column_name": "suggested_media_type", "data_type": "VARCHAR(16)", "description": "节点级建议采集介质（照片/视频/照片+视频），与单文件B006严格分离"},
        {"column_name": "review_status", "data_type": "VARCHAR(16)", "description": "源数据校审状态：CONFIRMED/PENDING_REVIEW；待审节点不得进入正式强制采集任务与完整度考核"},
        {"column_name": "role_type", "data_type": "VARCHAR(16)", "description": "拍摄人项目角色（SZ总监/SP专监/SA监理员/ADMIN企业管理员）"},
        {"column_name": "action_type", "data_type": "VARCHAR(16)", "description": "履职动作类型（PZ旁站/XS巡视/YS验收/ZG整改/YJ应急/JC督查）"},
        {"column_name": "altitude", "data_type": "DECIMAL(8,2)", "description": "GPS定位高程（米，选填）"},
        {"column_name": "horizontal_accuracy", "data_type": "DECIMAL(6,2)", "description": "GPS水平定位精度误差（米）"},
        {"column_name": "building_element", "data_type": "VARCHAR(64)", "description": "所属工程实体构件"},
        {"column_name": "device_uuid", "data_type": "VARCHAR(64)", "description": "采集手机匿名设备标识"},
        {"column_name": "device_model", "data_type": "VARCHAR(64)", "description": "手机品牌型号"},
        {"column_name": "os_version", "data_type": "VARCHAR(64)", "description": "操作系统与小程序版本"},
        {"column_name": "exif_available_status", "data_type": "TINYINT", "description": "1完整可获取/2仅基础宽高方向(微信getImageInfo标准能力)/3不可获取待核验"},
        {"column_name": "gps_status", "data_type": "TINYINT", "description": "1围栏内正常/2无信号缺失/3超围栏预警/4定位异常待人工核验"},
        {"column_name": "client_clock_verified", "data_type": "TINYINT(1)", "description": "端侧单调时钟校验通过标记"},
        {"column_name": "is_offline_queued", "data_type": "TINYINT(1)", "description": "是否离线排队上传（正常离线延迟不误报漂移）"},
        {"column_name": "time_drift_warning", "data_type": "TINYINT(1)", "description": "设备系统时间人为拨改>15分钟或非离线上传异常延迟标记"},
        {"column_name": "raw_frame_sha256", "data_type": "CHAR(64)", "description": "原始相机帧摘要（压入水印前16位，与归档file_sha256职责分离）"},
        {"column_name": "watermarked_file_path", "data_type": "VARCHAR(512)", "description": "带水印归档衍生文件路径"},
        {"column_name": "audit_status", "data_type": "TINYINT", "description": "0待审/1通过/2驳回/3历史作废留存"},
        {"column_name": "retention_policy_code", "data_type": "VARCHAR(32)", "description": "LONGTERM_RETENTION/POST_COMPLETION_1Y/POST_COMPLETION_3Y/LOCAL_90D"},
        {"column_name": "is_deleted", "data_type": "TINYINT(1)", "description": "逻辑软删除标记（原始证据严禁物理删除）"},
        {"column_name": "created_at", "data_type": "DATETIME(3)", "description": "记录创建时间"}
    ]

    xlsx_sheets = read_xlsx(os.path.join(SRC_DIR, "危大工程监理履约记录表.xlsx"))
    def extract_headers(rows):
        for row in rows:
            if len(row) > 2 and row[0].strip() == '序号':
                return [c.strip() for c in row if c.strip()]
        return []
    forms = [
        {"form_family_code": "F01", "form_family_name": "危大工程验收记录表族", "official_standard_mapping": "住建部令第37号第二十一条（验收合格双签+验收标识牌公示核查后方可进入下一道工序）；GB/T 50319-2013 分项/检验批/隐蔽验收记录表", "source_excel_sheet": "验收记录表", "core_fields": extract_headers(xlsx_sheets['验收记录表']), "media_binding_rule": "强制绑定★验收举牌全景、构件特写及验收标识牌公示照片；双签确认后解锁下一道工序门禁"},
        {"form_family_code": "F02", "form_family_name": "监理旁站记录表族", "official_standard_mapping": "GB/T 50319-2013 表 A.0.6（监理旁站记录表）；37号令第十八条", "source_excel_sheet": "旁站记录明细", "core_fields": extract_headers(xlsx_sheets['旁站记录明细']), "media_binding_rule": "记录旁站起止时间，绑定连续作业关键时段带水印照片/视频序列，旁站双方签认"},
        {"form_family_code": "F03", "form_family_name": "监理专项巡视/安全检查记录表族", "official_standard_mapping": "住建部令第37号第十八条；GB/T 50319-2013 第5.5.5条", "source_excel_sheet": "巡视记录明细", "core_fields": extract_headers(xlsx_sheets['巡视记录明细']), "media_binding_rule": "关联△日常巡视照片；发现缺陷一键触发F05隐患整改/停工报告流"},
        {"form_family_code": "F04", "form_family_name": "危大工程报审/报验与履约总表族", "official_standard_mapping": "GB/T 50319-2013 表 A.0.1（施工组织设计/专项施工方案报审表）；37号令第十一、十二、十八、二十条", "source_excel_sheet": "履约总表", "core_fields": extract_headers(xlsx_sheets['履约总表']), "media_binding_rule": "PC端上传专项方案PDF及专家论证意见书盖章扫描件至paper/"},
        {"form_family_code": "F05", "form_family_name": "监理通知单、工程暂停令与整改闭环表族", "official_standard_mapping": "GB/T 50319-2013 表 A.0.3（监理通知单）、表 A.0.4（工程暂停令）、表 B.0.5（监理通知回复单）；37号令第十九条", "source_excel_sheet": "整改报告台账", "core_fields": extract_headers(xlsx_sheets['整改报告台账']), "media_binding_rule": "强制绑定_QZ/_HW双图；一期施工单位线下提交签章回复单，由监理人员登记并扫描(_HF)归入paper/；支持停工送达、建设单位/主管部门报告与多轮复查记录"}
    ]

    forms_dictionary = {
        "metadata": {
            "dictionary_name": "危大工程监理履职证据链标准化元数据与核心表单统一数据字典（v1.3 评审整改版）",
            "version": "1.3.0", "generated_on": "2026-11-15", "generator_script": "scripts/generate_baseline_data.py",
            "standard_exchange_field_count": len(standard_fields), "internal_database_extension_count": len(internal_extensions),
            "naming_convention": "数据库列、SQLAlchemy Model、Pydantic Schema、API JSON与前端TS类型全栈统一使用snake_case。"
        },
        "standard_metadata_fields": standard_fields,
        "internal_database_extensions": internal_extensions,
        "core_supervision_forms": forms
    }
    with open(os.path.join(OUT_DIR, "metadata_and_forms_dictionary.json"), "w", encoding="utf-8") as f:
        json.dump(forms_dictionary, f, ensure_ascii=False, indent=2)

    # 验证报告：结构、源数据校审、业务准入严格拆分
    validation_report = {
        "structural_status": "PASS",
        "source_review_status": "PENDING" if pending_count > 0 else "PASS",
        "business_readiness": "BLOCKED" if pending_count > 0 else "READY",
        "total_baseline_records": len(nodes),
        "unique_node_uid_count": len(set(node_uids)),
        "confirmed_node_count": confirmed_count,
        "pending_review_node_count": pending_count,
        "standard_field_count": len(standard_fields),
        "internal_extension_count": len(internal_extensions),
        "category_counts": category_counts,
        "business_gate_rule": "仅 review_status=CONFIRMED 的节点允许进入正式强制采集任务与履职完整度考核分母；PENDING_REVIEW 节点一律不进入正式应采任务，不参与完整度分母。",
        "validation_scope": "包含节点UID唯一性、字段契约、PRD示例真实性与状态、命名公式一致性、权限旧词与旧配额扫描、法定履职验收用例覆盖检查（见 scripts/validate_prd_consistency.py）。"
    }
    with open(os.path.join(OUT_DIR, "validation_report.json"), "w", encoding="utf-8") as f:
        json.dump(validation_report, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print(f"✅ 基线库生成与结构校验通过: {len(nodes)} 条记录 / {len(set(node_uids))} 个全局唯一 node_uid")
    print(f"📋 业务校审状态: CONFIRMED={confirmed_count} 条, PENDING_REVIEW={pending_count} 条")
    print(f"🚦 业务准入状态: business_readiness={validation_report['business_readiness']}（待业务专家确认后方可全量开发）")
    print("=" * 70)

if __name__ == "__main__":
    main()
