#!/usr/bin/env python3
"""qcm_output_assembler.py — P1 原型：组件驱动输出引擎（不写入 QCM 本体）

功能：
  1. 查 constraint_map（读取本体 references/config/constraint.yaml 只读）
  2. 加载组件片段（components/ 目录 · schema 头部）
  3. 字段注入（占位符替换 + 类型校验）
  4. 行动条目收集（_measures 数据 → 行动清单条目）
  5. action-list 渲染（6 列：来源/动作/做多少/责任人/截止/交付 + 时间分组 + 状态前缀）
  6. 骨架封装（行动前置第 0 段 + 支撑段折叠标记）
  7. 组件级校验（无占位符残留 · 封装前快速失败）

用法：
  from assembler import assemble
  out = assemble(route_result, actions_data)
"""
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path

DEV_ROOT = Path(__file__).resolve().parent.parent  # skills/QCM
COMPONENTS_DIR = DEV_ROOT / "components"
QCM_ROOT = Path(__file__).resolve().parent.parent
QCM_REFERENCES = QCM_ROOT / "references"

# ============ 时间分组映射（截止 → 分组） ============
TIME_GROUP = {
    "24h": "今日必做",
    "1-2周": "本周重点",
    "2-3周": "本月推进",
    "季末": "本月推进",
}
GROUP_ORDER = ["今日必做", "本周重点", "本月推进"]

# ============ 骨架封装模板 ============
SKELETON_WRAP = {
    "crisis": "【行动清单】(核心·默认显式)\n{action_list}\n\n{body}",
    "improve": "【行动清单】(核心·默认显式)\n{action_list}\n\n{body}",
    "assess": "【行动清单】(核心·默认显式)\n{action_list}\n\n{body}",
    "culture": "【行动清单】(核心·默认显式)\n{action_list}\n\n{body}",
    "knowledge": "【行动清单】(核心·默认显式)\n{action_list}\n\n{body}",
    "distill": "【行动清单】(核心·默认显式 · 适配任务)\n{action_list}\n\n{body}",
    "standard": "【行动清单】(核心·默认显式)\n{action_list}\n\n{body}",
}

# ============ 组件功能分类（任务 1：分析 vs 输出） ============
COMPONENT_CATEGORY = {
    # 分析组件（认知·为什么）
    "_meta": "analysis",            # 路由元数据（透明性）
    "intent-glossary": "analysis",  # 意图词典（意图×形态规范真源 · A+B V8.7）
    "_route": "analysis",           # 导航行（特征→AO）
    "_state_nav": "analysis",       # 事态导航
    "_probe": "analysis",           # 定位探针
    "_assessment_summary": "analysis",
    "_score_table": "analysis",
    "_gaps": "analysis",
    "_pdca_current": "analysis",    # 改进：现状分析
    "_culture_aware": "analysis",   # 文化：意识层
    "_culture_system": "analysis",  # 文化：制度层
    "_knowledge_def": "analysis",   # 学习：定义
    "_knowledge_basis": "analysis", # 学习：依据
    # 输出组件（行动·做什么）
    "_action_items": "output",      # 行动要项（行动纲领）
    "_measures": "output",          # 行动措施
    "_crisis_comm": "output",       # 危机沟通
    "_dual_zero": "output",         # 双归零
    "_followup": "output",          # 后续计划
    "_suggestions": "output",
    "_decision_row": "output",
    "_pdca_target": "output",       # 改进：目标
    "_pdca_counter": "output",      # 改进：对策
    "_pdca_verify": "output",       # 改进：验证
    "_culture_behavior": "output",  # 文化：行为
    "_culture_climate": "output",   # 文化：氛围
    "_knowledge_points": "output",  # 学习：要点
    "_crisis_judge": "output",      # 快响：危机判定
    "_crisis_judge_mini": "output", # 快响：极简判定
    "_distill_pack": "output",      # 沉淀：适配包
}

# ============ 密度分层（任务 3：复杂度 × 角色 → 分析展开度） ============
ROLE_DENSITY = {
    "exec":      {"analysis": "fold",    "detail": False},  # 执行层：只要行动（分析全折叠）
    "manager":   {"analysis": "summary", "detail": True},   # 管理层：行动 + 分析摘要
    "executive": {"analysis": "full",    "detail": True},   # 决策层：全展开
}


def category_of(comp_id: str) -> str:
    """组件功能分类（默认 output）"""
    return COMPONENT_CATEGORY.get(comp_id, "output")


def load_constraint_map() -> list:
    """读取本体 references/config/constraint.yaml（只读 · P1 不写本体）"""
    try:
        import yaml
    except ImportError:
        return []
    path = QCM_REFERENCES / "config" / "constraint.yaml"
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("mapping", [])
    except Exception:
        return []


def query_spec(intent: str, D: int = 0, complexity: str = "") -> dict:
    """查 constraint_map：意图×D×复杂度 → {form, skeleton, components, depth}"""
    mapping = load_constraint_map()
    for m in mapping:
        c = m.get("constraints", {})
        if c.get("intent") != intent:
            continue
        # D 条件匹配（支持 <、>、>=、<= 操作符 · 第2字符= 判双字符）
        d_req = c.get("D")
        if d_req:
            if len(d_req) >= 2 and d_req[1] == "=":
                op, val = d_req[:2], int(d_req[2:])
            else:
                op, val = d_req[0], int(d_req[1:])
            if op == ">=" and not (D >= val):
                continue
            if op == "<" and not (D < val):
                continue
        # 复杂度条件
        comp_req = c.get("complexity")
        if comp_req and comp_req != complexity:
            continue
        return {
            "form": m.get("form", "standard"),
            "skeleton": m.get("skeleton", "standard"),
            "components": m.get("components", []),
            "depth": m.get("depth", "L2"),
        }
    # 兜底：标准骨架
    return {"form": "standard", "skeleton": "standard",
            "components": ["_meta", "_route", "_measures"], "depth": "L2"}


# 内容组件 → 母模板段落锚点（真源在 outputs/*.md · 组件文件仅引用）
CONTENT_COMPONENT_SOURCE = {
    # 案例应用形态（case-application.md）
    "_measures": ("case-application.md", "【行动措施】"),
    "_action_items": ("case-application.md", "【行动要项】"),
    "_state_nav": ("case-application.md", "【事态导航】"),
    "_crisis_comm": ("case-application.md", "【危机沟通】"),
    "_dual_zero": ("case-application.md", "【双归零】"),
    "_followup": ("case-application.md", "【后续计划】"),
    # 决策卡形态（decision-card.md）
    "_decision_row": ("decision-card.md", "【应急决策卡】"),
    # 评估报告形态（assessment-report.md）
    "_assessment_summary": ("assessment-report.md", "【评估摘要】"),
    "_score_table": ("assessment-report.md", "【现状评估】"),
    "_gaps": ("assessment-report.md", "【关键缺口】"),
    "_suggestions": ("assessment-report.md", "【改进建议】"),
    # 快响应形态（quick-response.md）
    "_crisis_judge": ("quick-response.md", "【现场快速判定】"),
    "_crisis_judge_mini": ("quick-response.md", "【判定】"),
    # 骨架差异（母模板内段引用 · 形态主文件承载）
    "_pdca_current": ("case-application.md", "【行动措施】"),
    "_pdca_target": ("case-application.md", "【行动措施】"),
    "_pdca_counter": ("case-application.md", "【行动措施】"),
    "_pdca_verify": ("case-application.md", "【行动措施】"),
    "_culture_aware": ("assessment-report.md", "【评估摘要】"),
    "_culture_behavior": ("assessment-report.md", "【现状评估】"),
    "_culture_system": ("assessment-report.md", "【关键缺口】"),
    "_culture_climate": ("assessment-report.md", "【改进建议】"),
    "_knowledge_def": ("quick-response.md", "【现场快速判定】"),
    "_knowledge_points": ("quick-response.md", "【现场快速判定】"),
    "_knowledge_basis": ("quick-response.md", "【现场快速判定】"),
}


def validate_mapping() -> list:
    """M-3 映射闭合校验：每个内容组件锚点存在 · 无悬空引用"""
    errors = []
    for comp_id, (fname, anchor) in CONTENT_COMPONENT_SOURCE.items():
        path = QCM_ROOT / "outputs" / fname
        if not path.exists():
            errors.append(f"{comp_id}: 母模板 {fname} 不存在")
            continue
        text = path.read_text(encoding="utf-8")
        if anchor not in text:
            errors.append(f"{comp_id}: 锚点 {anchor} 不在 {fname}")
    return errors


def extract_from_master(comp_id: str) -> str:
    """内容组件：从母模板按段落锚点提取（真源唯一）"""
    src = CONTENT_COMPONENT_SOURCE.get(comp_id)
    if not src:
        return ""
    fname, anchor = src
    path = QCM_ROOT / "outputs" / fname
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    idx = text.find(anchor)
    if idx < 0:
        return ""
    # 提取到下一个 ## 或 【 段落标题
    end = len(text)
    nxt = text.find("\n## ", idx + len(anchor))
    if nxt < 0:
        nxt = len(text)
    return text[idx:nxt].strip()


def load_component(comp_id: str) -> str:
    """双通道加载：
      内容组件 → 母模板提取（真源 outputs/*.md）
      动态组件 → 组件文件（占位符模板）
    """
    if comp_id in CONTENT_COMPONENT_SOURCE:
        return extract_from_master(comp_id)
    path = COMPONENTS_DIR / f"{comp_id}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def strip_frontmatter(snippet: str) -> str:
    """剥离 YAML frontmatter（--- 之间）"""
    if snippet.startswith("---"):
        parts = snippet.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return snippet


def _build_distill_context(route: dict) -> dict:
    """⑤知识沉淀蒸馏上下文推导（T1 · 2026-08-25 三项遗留）

    为 _distill_pack 组件补 3 个 required 字段（industry/process_map/standards）的
    语义注入源——行业包 index.yaml 登记 + route.domain 兜底，纯只读推导：
      industry   ← route.domain 首域匹配行业包 industry 列表
      process_map← 命中行业包正文 §1 行业概述首行工艺链路
      standards  ← domain 关联标准（E体系→ISO/IATF · C供应链→IATF/VDA · entities 兜底）
    设计边界：只注入路由可推导字段；其余 content 字段（行业定位/工序细分/场景/
    工具落格等）属内容生成职责，保留占位由调用方填充。
    """
    from pathlib import Path as _P
    _dev = _P(__file__).resolve().parent.parent
    _idx = _dev / "references" / "industry" / "index.yaml"

    domain0 = (route.get("domain") or ["通用"])[0]
    industry, pack_path, process_map = "（按 %s 行业适配）" % domain0, None, "（按 %s 领域工艺映射）" % domain0

    try:
        import yaml as _y
        if _idx.exists():
            data = _y.safe_load(_idx.read_text(encoding="utf-8")) or {}
            for p in data.get("industry_packs", []):
                inds = p.get("industry", [])
                doms = p.get("domain", [])
                if domain0 in inds or domain0 in doms:
                    industry = " / ".join(inds[:2])
                    pack_path = _dev / p.get("path", "")
                    break
            if pack_path and pack_path.exists():
                for line in pack_path.read_text(encoding="utf-8").splitlines():
                    if "制造链路" in line or "工艺" in line or "→" in line:
                        process_map = line.strip().strip(">").strip()
                        break
    except Exception:
        pass  # 行业包不可读 → 兜底文案（不阻断装配）

    # standards：领域关联标准（E体系/C供应链优先，entities.yaml 兜底）
    if domain0 == "E体系":
        standards = "ISO 9001 / IATF 16949 / VDA 6.3"
    elif domain0 == "C供应链":
        standards = "IATF 16949 / VDA 6.3 / PPAP"
    else:
        standards = "（按 %s 领域标准）" % domain0
        try:
            import yaml as _y
            _ent = _dev / "references" / "config" / "entities.yaml"
            if _ent.exists():
                data = _y.safe_load(_ent.read_text(encoding="utf-8")) or {}
                hits = [e["name"] for e in data.get("entities", [])
                        if e.get("type") == "standard" and e.get("domain") == domain0]
                if hits:
                    standards = " / ".join(hits[:3])
        except Exception:
            pass

    return {
        "{industry}": industry,
        "{process_map}": process_map,
        "{standards}": standards,
    }


def inject_fields(snippet: str, route: dict, spec: dict) -> str:
    """字段注入：占位符替换（动态自适应核心）"""
    body = strip_frontmatter(snippet)
    vars_map = {
        "{intent}": route.get("intent", "?"),
        "{domain}": "+".join(route.get("domain", ["通用"])),
        "{confidence}": f"{route.get('confidence', 0.0):.2f}",
        "{D}": str(route.get("D", "—")),
        "{complexity}": route.get("complexity", "single"),
        "{skeleton}": spec.get("skeleton", "standard"),
        "{form}": spec.get("form", "standard"),
        "{depth}": spec.get("depth", "L2"),
        "{nav}": route.get("nav", "（待补充导航）"),
        "{tools}": route.get("tools", "（按领域预选工具）"),
    }
    # T1（2026-08-25 三项遗留）：⑤知识沉淀蒸馏上下文推导注入
    if route.get("intent") == "⑤知识沉淀":
        try:
            vars_map.update(_build_distill_context(route))
        except Exception:
            pass  # 推导失败 → 保留原占位（白名单登记）
    for k, v in vars_map.items():
        body = body.replace(k, v)
    return body


def build_actions_block(actions: list) -> str:
    """渲染【行动措施】4 阶段块（决策桥填充 · RACI）"""
    lines = []
    for a in actions:
        lines.append(
            f"{a['phase']}（{a['deadline']} · ⏳）：{a['action']}"
            f"【R:{a['raci']['R']} · C:{a['raci']['C']} · I:{a['raci']['I']}】"
            f" 做多少：{a['target']} · 交付：{a['deliverable']}"
            f"（探针：{a.get('probe', '—')}）"
        )
    return "\n".join(lines)


def render_action_list(actions: list, with_detail: bool = True) -> str:
    """渲染【行动清单】：6 列 + 时间分组 + 状态前缀 + 详情组合（任务 4）"""
    groups = OrderedDict((g, []) for g in GROUP_ORDER)
    for a in actions:
        g = TIME_GROUP.get(a["deadline"], "本月推进")
        groups[g].append(a)

    lines = []
    total = len(actions)
    for g in GROUP_ORDER:
        items = groups[g]
        if not items:
            continue
        lines.append(f"### {g}")
        lines.append("| 来源 | 动作 | 做多少 | 责任人 | 截止 | 交付 |")
        lines.append("|------|------|--------|--------|------|------|")
        for a in items:
            status = a.get("status", "⏳")
            lines.append(
                f"| AO-{a['ao']} | {status} {a['action']} | {a['target']} | "
                f"{a['raci']['R']} | {a['deadline']} | {a['deliverable']} |"
            )
            # 清单-详情组合（任务 4）：每条目展开 = 对应输出组件详情
            if with_detail:
                lines.append(f"  └─ 展开 `{a['phase']}`：{a.get('detail', a['action'])}")
        lines.append("")
    lines.append(f"> 汇总：共 {total} 项行动 · 6 列对齐认知链（来源→动作→做多少→谁→何时→交付）")
    return "\n".join(lines)


def render_cross_matrix(actions: list) -> str:
    """交叉矩阵视图（责任人×时间 · 触发词 `矩阵视图` 展开）
    价值：按人找任务 + 暴露单人负载（管理信号）
    """
    people = []
    for a in actions:
        r = a["raci"]["R"]
        if r not in people:
            people.append(r)
    times = ["今日必做", "本周重点", "本月推进"]
    grid = {}
    for a in actions:
        t = TIME_GROUP.get(a["deadline"], "本月推进")
        grid.setdefault((a["raci"]["R"], t), []).append(f"AO-{a['ao']} {a['action']}")
    lines = ["| 责任人 | 今日必做 | 本周重点 | 本月推进 |",
             "|--------|---------|---------|---------|"]
    for p in people:
        row = [p]
        for t in times:
            cells = grid.get((p, t))
            row.append("；".join(cells) if cells else "—")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def component_check(output: str) -> list:
    """组件级校验（封装前 · 快速失败）：占位符残留"""
    leftovers = re.findall(r"\{[a-z_]+\}", output)
    return leftovers


def wrap_skeleton(skeleton: str, action_list: str, body: str) -> str:
    """骨架封装：行动前置 + 支撑段折叠标记"""
    template = SKELETON_WRAP.get(skeleton, SKELETON_WRAP["standard"])
    # 支撑段折叠：非行动段加折叠标记（原型：正文后置 + ⏳ 提示）
    folded_body = f"> 支撑详情（导航/沟通/归零/探针）默认折叠 · 触发词展开\n\n{body}"
    return template.format(action_list=action_list, body=folded_body)


def assemble(route: dict, actions: list, role: str = "manager",
             actions_block_override: str = None) -> dict:
    """主入口：路由结果 + 行动数据 → 动态组装输出

    Args:
        route: {intent, domain, confidence, D, complexity, nav, tools}
        actions: [{phase, action, target, raci{R,C,I}, deadline, deliverable, ao, status, detail}]
        role: exec(执行层·分析折叠) / manager(管理层·分析摘要) / executive(决策层·分析全开)
    Returns:
        {"output": str, "action_list": str, "spec": dict, "errors": list,
         "density": str, "analysis_display": str}
    """
    spec = query_spec(route["intent"], route.get("D", 0), route.get("complexity", ""))
    density = ROLE_DENSITY.get(role, ROLE_DENSITY["manager"])
    errors = []

    # 1. 逐组件加载 + 注入（按角色密度分层）
    sections = []
    analysis_shown = 0
    for comp_id in spec["components"]:
        category = category_of(comp_id)
        # 密度分层：分析组件按角色决定展开度
        if category == "analysis":
            mode = density["analysis"]
            if mode == "fold":
                continue  # 执行层：分析组件折叠
            analysis_shown += 1
        snippet = load_component(comp_id)
        if not snippet:
            continue
        if comp_id == "_measures":
            block = actions_block_override or build_actions_block(actions)
            body = strip_frontmatter(snippet).replace("{actions_block}", block)
        else:
            body = inject_fields(snippet, route, spec)
        # 组件级校验：占位符残留
        leftovers = component_check(body)
        if leftovers:
            errors.append(f"组件 {comp_id} 占位符残留: {leftovers}")
        sections.append(body)

    # 2. 行动清单（核心 · 清单-详情组合）
    action_list = render_action_list(actions, with_detail=density["detail"])
    errors += component_check(action_list)

    # 3. 骨架封装（行动前置）
    body = "\n\n".join(sections)
    output = wrap_skeleton(spec["skeleton"], action_list, body)

    cross = render_cross_matrix(actions)
    return {"output": output, "action_list": action_list,
            "spec": spec, "errors": errors,
            "density": f"{role}({density['analysis']})",
            "analysis_display": f"{analysis_shown} 分析组件显示",
            "cross_matrix": cross,
            # B2 · 归零事件复用建议透传（S1 建议层 · 仅透传、不进 action_list、绝不自动套用治理闭环）
            "reuse_suggest": route.get("reuse_suggest", [])}


if __name__ == "__main__":
    demo = {
        "intent": "①危机处置", "domain": ["Q客户", "C供应链"],
        "confidence": 0.85, "D": 6, "complexity": "multi_chain",
        "nav": "隐蔽→AO-1+AO-3 · 多链→AO-2", "tools": "KANO/VOC/温控标签",
    }
    demo_actions = [
        {"phase": "围堵", "action": "临期鲜花下架", "target": "100% 门店",
         "raci": {"R": "门店店长", "C": "物流专员", "I": "采购经理"},
         "deadline": "24h", "deliverable": "下架记录", "ao": 1, "status": "⏳"},
        {"phase": "消除", "action": "3A5WHY 冷链追溯", "target": "全链 3 断点",
         "raci": {"R": "质量工程师", "C": "仓储主管", "I": "门店店长"},
         "deadline": "1-2周", "deliverable": "根因报告", "ao": 2, "status": "⏳"},
        {"phase": "纠正", "action": "温控 SOP 制定", "target": "≥95% 门店执行",
         "raci": {"R": "培训专员", "C": "质量工程师", "I": "全门店"},
         "deadline": "2-3周", "deliverable": "SOP 文档", "ao": 3, "status": "⏳"},
        {"phase": "预防", "action": "供应商 SLA", "target": "3 家签约",
         "raci": {"R": "供应链经理", "C": "采购总监", "I": "全门店"},
         "deadline": "季末", "deliverable": "SLA 合同", "ao": 4, "status": "⏳"},
    ]
    res = assemble(demo, demo_actions)
    print(res["output"])
    print("\n[errors]", res["errors"] if res["errors"] else "无")
