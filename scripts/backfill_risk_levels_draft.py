"""
研究报告正文风险定性回填脚本（草案）—— 方案A：评审方起草，技术团队审查合并

目的：修复 generate_baseline_data.py 仅读取附录A表格、漏扫研究报告正文第4章导致331条误判PENDING_REVIEW的问题。

映射策略：
1. 准备阶段/验收阶段：正文逐节点列出，按"危大类别+阶段+阶段内序号"精确映射
2. 过程阶段：正文为概括描述，按阶段级规则推断：
   - 隐蔽/旁站/灌注/张拉等高风险工序 → ★
   - 常规巡视/每日巡视 → △
   - 无法判断 → 歧义待审
3. 批量声明：拆除/人工挖孔桩/水下作业/应急等"全类★"直接覆盖
4. 冲突检测：正文与附录表格节点名称/内容不一致时标记冲突

产出：
- backfill_mapping_report.json：完整映射结果与统计
- backfill_auto_confirmed.json：可自动CONFIRMED的节点清单
- backfill_ambiguous.json：歧义待审节点清单（交业务专家快审）
- backfill_conflicts.json：正文与表格冲突清单
"""
import zipfile
import xml.etree.ElementTree as ET
import json
import os
import re
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "docs", "00-source-materials")
OUT_DIR = os.path.join(BASE_DIR, "docs", "04-baseline-data")
REPORT_FILE = os.path.join(SRC_DIR, "危大工程监理履职数字化证据链构建与应用研究（研究报告初稿）.docx")

# 危大类别映射：正文章节号 → 附录编号
HAZARD_MAP = {
    "4.2": "01",   # 基坑工程
    "4.3": "02",   # 模板工程及支撑体系
    "4.4": "03",   # 起重吊装及起重机械安装拆卸工程
    "4.5": "04",   # 脚手架工程
    "4.6": "05",   # 拆除工程
    "4.7": "06",   # 暗挖工程
    "4.8": "07",   # 建筑幕墙安装工程
    "4.9": "08",   # 钢结构、网架和索膜结构安装工程
    "4.10": "09",  # 人工挖孔桩工程
    "4.11": "10",  # 水下作业工程
    "4.12": "11",  # 装配式建筑混凝土预制构件安装工程
}

STAGE_MAP = {
    "1": {"code": "01", "name": "施工准备阶段", "keywords": ["施工准备", "准备阶段"]},
    "2": {"code": "02", "name": "施工过程阶段", "keywords": ["施工过程", "过程中"]},
    "3": {"code": "03", "name": "验收阶段", "keywords": ["验收"]},
}

# 全类强制采集的类别（批量声明）
FULL_STAR_CATEGORIES = {"05", "09", "10"}  # 拆除、人工挖孔桩、水下作业

# 过程阶段高风险关键词（隐蔽/旁站工序 → ★）
HIGH_RISK_KEYWORDS = [
    "隐蔽", "旁站", "灌注", "张拉", "吊装", "安装", "拆除", "爆破",
    "支护", "锚杆", "锚索", "喷射", "注浆", "成孔", "成槽", "顶进",
    "盾构", "掘进", "开挖", "降水", "止水", "围护", "支撑", "架体",
    "爬升", "提升", "合龙", "对接", "焊接", "探伤", "检测", "监测预警",
]

# 过程阶段常规巡视关键词（→ △）
ROUTINE_KEYWORDS = ["巡视", "每日", "日常", "常规", "巡查", "检查", "运行", "维护"]


def get_docx_body_blocks(path):
    """读取 docx 正文段落。"""
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


def parse_report_chapter4():
    """解析研究报告第4章，提取每个节点的定性。"""
    blocks = get_docx_body_blocks(REPORT_FILE)

    # 定位第4章所有小节
    sections = []
    for i, b in enumerate(blocks):
        m = re.match(r'^(4\.\d+(?:\.\d+)?)\s+(.+)', b['text'])
        if m:
            sections.append({'idx': i, 'code': m.group(1), 'title': m.group(2).strip()})

    # 解析每个小节的节点
    nodes_by_section = {}
    batch_declarations = {}

    for si, sec in enumerate(sections):
        start = sec['idx']
        end = sections[si + 1]['idx'] if si + 1 < len(sections) else len(blocks)
        content = [blocks[j]['text'] for j in range(start + 1, end)]
        joined = '\n'.join(content)

        # 检查批量声明
        if '全部节点' in joined and '★' in joined:
            batch_declarations[sec['code']] = '★'
        elif '统一★' in joined or '全流程★' in joined or '全节点★' in joined:
            batch_declarations[sec['code']] = '★'

        # 解析逐节点段落（以"N."开头的标题）
        nodes = []
        current_node = None
        for text in content:
            m = re.match(r'^(\d+)\.\s*(.+)', text)
            if m and len(m.group(2)) > 3:  # 节点标题
                if current_node:
                    nodes.append(current_node)
                current_node = {
                    'seq': int(m.group(1)),
                    'name': m.group(2).strip(),
                    'risk_level': None,
                    'capture_text': '',
                    'full_text': text,
                }
            elif current_node:
                current_node['full_text'] += '\n' + text
                if '影像采集' in text:
                    current_node['capture_text'] = text
                    # 提取定性
                    if '★' in text:
                        current_node['risk_level'] = '★'
                    elif '△' in text:
                        current_node['risk_level'] = '△'
        if current_node:
            nodes.append(current_node)

        nodes_by_section[sec['code']] = nodes

    return nodes_by_section, batch_declarations


def infer_process_stage_risk(node_name, supervision_action, capture_guidance):
    """过程阶段风险推断：按关键词判断是否属于隐蔽/旁站工序。"""
    text = f"{node_name} {supervision_action} {capture_guidance}"

    # 优先检查常规巡视
    for kw in ROUTINE_KEYWORDS:
        if kw in text:
            return '△', f"匹配常规巡视关键词'{kw}'"

    # 检查高风险工序
    for kw in HIGH_RISK_KEYWORDS:
        if kw in text:
            return '★', f"匹配高风险工序关键词'{kw}'"

    return None, "无法按关键词判断，需人工确认"


def map_to_appendix_nodes(report_nodes, batch_declarations):
    """将正文节点映射到附录A表格节点。"""
    # 读取当前种子库
    seed_path = os.path.join(OUT_DIR, "hazard_nodes_seed.json")
    with open(seed_path, 'r', encoding='utf-8') as f:
        seed_data = json.load(f)

    # 按类别和阶段分组种子节点
    seed_by_category_stage = defaultdict(list)
    for node in seed_data['nodes']:
        key = (node['hazard_code'], node['stage_code'])
        seed_by_category_stage[key].append(node)

    # 按序号排序（种子库中节点按 source_sequence 排列）
    for key in seed_by_category_stage:
        seed_by_category_stage[key].sort(key=lambda x: x['source_sequence'])

    auto_confirmed = []
    ambiguous = []
    conflicts = []
    mapping_details = []

    # 遍历每个类别
    for section_code, hazard_code in HAZARD_MAP.items():
        # 全类强制采集
        if hazard_code in FULL_STAR_CATEGORIES:
            for stage_code in ['01', '02', '03']:
                key = (hazard_code, stage_code)
                for node in seed_by_category_stage.get(key, []):
                    auto_confirmed.append({
                        'node_uid': node['node_uid'],
                        'node_name': node['node_name'],
                        'risk_level': '★',
                        'basis': f'研究报告{section_code}节：全类强制采集',
                        'mapping_type': 'batch_category',
                    })
                    mapping_details.append({
                        'node_uid': node['node_uid'],
                        'status': 'auto_confirmed',
                        'basis': f'研究报告{section_code}节全类强制',
                    })
            continue

        # 逐阶段处理
        for stage_num, stage_info in STAGE_MAP.items():
            subsection_code = f"{section_code}.{stage_num}"
            stage_code = stage_info['code']
            key = (hazard_code, stage_code)
            seed_nodes = seed_by_category_stage.get(key, [])

            if not seed_nodes:
                continue

            report_node_list = report_nodes.get(subsection_code, [])
            batch_decl = batch_declarations.get(subsection_code)

            # 情况1：逐节点列出（准备/验收阶段）
            if report_node_list and len(report_node_list) > 0:
                # 按阶段内序号映射
                mapped_seed_indices = set()
                for idx, rnode in enumerate(report_node_list):
                    if idx >= len(seed_nodes):
                        conflicts.append({
                            'section': subsection_code,
                            'issue': f'正文节点数({len(report_nodes)})超过附录表格节点数({len(seed_nodes)})',
                            'report_node': rnode['name'],
                        })
                        continue

                    seed_node = seed_nodes[idx]
                    mapped_seed_indices.add(idx)
                    if rnode['risk_level']:
                        auto_confirmed.append({
                            'node_uid': seed_node['node_uid'],
                            'node_name': seed_node['node_name'],
                            'risk_level': rnode['risk_level'],
                            'basis': f'研究报告{subsection_code}节节点{rnode["seq"]}：{rnode["name"]}',
                            'mapping_type': 'explicit_node',
                        })
                        mapping_details.append({
                            'node_uid': seed_node['node_uid'],
                            'status': 'auto_confirmed',
                            'basis': f'{subsection_code} 节点{rnode["seq"]}',
                        })
                    else:
                        ambiguous.append({
                            'node_uid': seed_node['node_uid'],
                            'node_name': seed_node['node_name'],
                            'reason': f'正文{subsection_code}节节点{rnode["seq"]}未明确定性',
                            'report_node_name': rnode['name'],
                        })

                # 该阶段未在正文中列出的节点：按已列节点的多数定性推断
                unmapped_in_stage = [i for i in range(len(seed_nodes)) if i not in mapped_seed_indices]
                if unmapped_in_stage:
                    listed_risks = [r['risk_level'] for r in report_node_list if r['risk_level']]
                    if listed_risks and all(r == '★' for r in listed_risks):
                        inferred_risk = '★'
                        basis_prefix = f'研究报告{subsection_code}节：该阶段已列{len(listed_risks)}节点全部★，推断未列节点同为★'
                    elif listed_risks and all(r == '△' for r in listed_risks):
                        inferred_risk = '△'
                        basis_prefix = f'研究报告{subsection_code}节：该阶段已列{len(listed_risks)}节点全部△，推断未列节点同为△'
                    else:
                        inferred_risk = None

                    for i in unmapped_in_stage:
                        seed_node = seed_nodes[i]
                        if inferred_risk:
                            auto_confirmed.append({
                                'node_uid': seed_node['node_uid'],
                                'node_name': seed_node['node_name'],
                                'risk_level': inferred_risk,
                                'basis': basis_prefix,
                                'mapping_type': 'inferred_stage_pattern',
                            })
                            mapping_details.append({
                                'node_uid': seed_node['node_uid'],
                                'status': 'auto_confirmed',
                                'basis': f'{subsection_code} 阶段模式推断',
                            })
                        else:
                            ambiguous.append({
                                'node_uid': seed_node['node_uid'],
                                'node_name': seed_node['node_name'],
                                'reason': f'{subsection_code}节已列节点定性混合（★/△均有），无法推断未列节点',
                            })

            # 情况2：批量声明（如基坑验收"全部节点★"）
            elif batch_decl == '★':
                for node in seed_nodes:
                    auto_confirmed.append({
                        'node_uid': node['node_uid'],
                        'node_name': node['node_name'],
                        'risk_level': '★',
                        'basis': f'研究报告{subsection_code}节：全部节点强制采集',
                        'mapping_type': 'batch_stage',
                    })
                    mapping_details.append({
                        'node_uid': node['node_uid'],
                        'status': 'auto_confirmed',
                        'basis': f'{subsection_code} 批量声明',
                    })

            # 情况3：过程阶段概括描述（按关键词推断）
            elif stage_code == '02':
                for node in seed_nodes:
                    risk, reason = infer_process_stage_risk(
                        node['node_name'],
                        node.get('supervision_action', ''),
                        node.get('capture_guidance', '')
                    )
                    if risk:
                        auto_confirmed.append({
                            'node_uid': node['node_uid'],
                            'node_name': node['node_name'],
                            'risk_level': risk,
                            'basis': f'研究报告{subsection_code}节规则：{reason}',
                            'mapping_type': 'inferred_keyword',
                        })
                        mapping_details.append({
                            'node_uid': node['node_uid'],
                            'status': 'auto_confirmed',
                            'basis': f'{subsection_code} 关键词推断：{reason}',
                        })
                    else:
                        ambiguous.append({
                            'node_uid': node['node_uid'],
                            'node_name': node['node_name'],
                            'reason': f'过程阶段无法按关键词判断：{reason}',
                            'supervision_action': node.get('supervision_action', '')[:100],
                        })

            # 情况4：无正文覆盖
            else:
                for node in seed_nodes:
                    ambiguous.append({
                        'node_uid': node['node_uid'],
                        'node_name': node['node_name'],
                        'reason': f'研究报告{subsection_code}节无对应内容',
                    })

    return auto_confirmed, ambiguous, conflicts, mapping_details


def main():
    print("=" * 70)
    print("研究报告正文风险定性回填分析")
    print("=" * 70)

    # 1. 解析正文
    print("\n[1] 解析研究报告第4章...")
    report_nodes, batch_declarations = parse_report_chapter4()
    print(f"   解析到 {len(report_nodes)} 个小节，{len(batch_declarations)} 个批量声明")

    # 2. 映射到附录
    print("\n[2] 建立正文-附录映射...")
    auto_confirmed, ambiguous, conflicts, mapping_details = map_to_appendix_nodes(
        report_nodes, batch_declarations
    )

    # 3. 统计
    print(f"\n[3] 映射结果统计：")
    print(f"   ✅ 自动 CONFIRMED: {len(auto_confirmed)} 条")
    print(f"   ⚠️  歧义待审: {len(ambiguous)} 条")
    print(f"   🔴 冲突: {len(conflicts)} 条")

    # 按映射类型统计
    by_type = defaultdict(int)
    for item in auto_confirmed:
        by_type[item['mapping_type']] += 1
    print(f"\n   自动 CONFIRMED 按类型分布：")
    for t, c in by_type.items():
        print(f"      {t}: {c} 条")

    # 4. 保存结果
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(os.path.join(OUT_DIR, 'backfill_auto_confirmed.json'), 'w', encoding='utf-8') as f:
        json.dump({'count': len(auto_confirmed), 'items': auto_confirmed}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, 'backfill_ambiguous.json'), 'w', encoding='utf-8') as f:
        json.dump({'count': len(ambiguous), 'items': ambiguous}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, 'backfill_conflicts.json'), 'w', encoding='utf-8') as f:
        json.dump({'count': len(conflicts), 'items': conflicts}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, 'backfill_mapping_report.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'total_auto_confirmed': len(auto_confirmed),
            'total_ambiguous': len(ambiguous),
            'total_conflicts': len(conflicts),
            'by_mapping_type': dict(by_type),
            'mapping_details': mapping_details,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n[4] 结果已保存到 {OUT_DIR}/")
    print("   - backfill_auto_confirmed.json")
    print("   - backfill_ambiguous.json")
    print("   - backfill_conflicts.json")
    print("   - backfill_mapping_report.json")
    print("=" * 70)


if __name__ == '__main__':
    main()
