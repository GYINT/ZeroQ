#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools_pack.py — QCM MCP 工具实现包（P2-9 从 mcp_server 拆出）

承载 9 个 MCP 工具实现（research/score_source/decide/solve_problem/audit/validate/
attribution/attribution_phase/gap_detect）+ 公共依赖（corpus 加载 / LLM Router）。

依赖方向：mcp_server → tools_pack（单向）。mcp_server 导入 TOOL_DEFS 注册工具。
"""
import os
import re
import sys
from typing import Any, Dict, List, Optional

# 版本常量（与 mcp_server.py 同步）
PROTOCOL_VERSION = "V8.0+"

# ============ 路径常量（与 mcp_server 一致） ============
QCM_ROOT = os.environ.get("QCM_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REFERENCES = os.path.join(QCM_ROOT, "references")
OUTPUTS = os.path.join(QCM_ROOT, "outputs")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============ LLM Router ============
try:
    from llm_router import LLMRouter
    LLM_ROUTER = LLMRouter()
    LLM_AVAILABLE = True
except Exception:
    LLM_ROUTER = None
    LLM_AVAILABLE = False

# ============ Corpus 加载（SQLite Cache） ============
# V8.6.2 P1 懒加载接线：优先 load_section 按需载入（-98% 工具上下文），
# 但为兼容既有调用方（corpus.get("tools.md") 裸文件名）保留全量 + 宽松键映射兜底。
_TOOLS_MD_KEY_CANDIDATES = ("tools.md", "tools/tools.md")


def _get_tools_md(corpus: Dict[str, str]) -> str:
    """从 corpus 中取 tools.md 内容（修复裸文件名/相对路径键不匹配 Bug）"""
    for k in _TOOLS_MD_KEY_CANDIDATES:
        v = corpus.get(k)
        if v:
            return v
    # 宽松匹配：任意含 tools.md 的键
    for k, v in corpus.items():
        if k.endswith("tools.md") and v:
            return v
    return ""


def _load_tools_section(tool_title: str) -> str:
    """懒加载：按工具标题载入单章节（corpus_loader · -98% 上下文）"""
    try:
        from corpus_loader import load_section
        sec = load_section("tools", tool_title)
        if sec:
            return sec
    except Exception:
        pass
    return ""


def load_corpus() -> Dict[str, str]:
    """读取 QCM 全量文件（references + outputs）· SQLite Cache

    V8.6.2 P1：先尝试懒加载（使用者经 _load_tools_section 按需取段），
    本函数保持全量返回（向后兼容 · 修复 tools.md 键不匹配）。
    """
    if os.environ.get("QCM_CACHE_DISABLE", "0") == "1":
        return _load_corpus_direct()
    try:
        from corpus_cache import CorpusCache
        cache = CorpusCache(REFERENCES)
        if not cache.is_built():
            cache.build()
        else:
            cache.incremental_update()
        return cache.get_all_files()
    except Exception:
        return _load_corpus_direct()

def _load_corpus_direct() -> Dict[str, str]:
    """直接读取（fallback）"""
    corpus = {}
    for d in [REFERENCES, OUTPUTS]:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.endswith(".md") and not fname.endswith(".deprecated"):
                fpath = os.path.join(d, fname)
                try:
                    corpus[fname] = open(fpath, encoding="utf-8").read()
                except Exception:
                    pass
    return corpus

# ============ 本地注册器（收集到 TOOL_DEFS · mcp_server 再注册） ============
TOOL_DEFS: List[Dict[str, Any]] = []

# V8.6 P2 · R10 蓝图落地：register_tool 织入（路径 B 自动织入——改一处即覆盖 9+ 未来工具）
# 包装层责任：返回原 func（签名/元信息零改动）· _sampled wrapper 记录 record_usage("tool", name)
# 双计治理：wrapper 与 mcp_server 网关共享同一 x_qcm_sampled 标记——
#   - wrapper 被直接调用（本地直调场景）：标记写回 result → 网关不再重复采样
#   - wrapper 被 MCP 网关调用：网关先查标记 → 命中则不重复采样（防同一次调用双计）
_SAMPLED_FLAG = "_x_qcm_sampled"


def _record_tool_usage(name: str):
    """采样工具调用（防御降级：observation 失败不影响工具）"""
    try:
        from usage_global import record_usage
        record_usage("tool", name)
    except Exception:
        pass


def _tool_usage_wrapper(func, name: str):
    """包装 handler：record_usage + 统一行为契约补全 + 采样标记（防双计）"""
    import functools

    @functools.wraps(func)
    def _wrapper(*args, **kwargs):
        _record_tool_usage(name)
        try:
            result = func(*args, **kwargs)
        except Exception:
            _record_tool_usage(name + ":error")  # 失败也采样（构建失败负反馈维度）
            raise
        # R13 链 B 履约单元：统一行为契约只增不改向后兼容（契约统一样式不强制统一内容）
        if isinstance(result, dict):
            try:
                result.setdefault("_qcm_contract", _qcm_contract(name))
                result.setdefault(_SAMPLED_FLAG, True)  # 网关据此跳过重复采样
            except Exception:
                pass
        return result
    return _wrapper


def register_tool(name: str, description: str, input_schema: Dict[str, Any]):
    """本地收集装饰器：向 TOOL_DEFS 追加定义（mcp_server 统一注册）

    V8.6 P2：handler 存原始 func（网关层决定是否包装调用），
    wrapper 仅通过 register_all 的选择性织入生效（见 register_all）。
    """
    def decorator(func):
        TOOL_DEFS.append({
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": func,
        })
        return func
    return decorator

# ============ 工具实现（从 mcp_server 迁移 · 自动生成） ============
@register_tool(
    name="qcm_research",
    description="端到端质量调研（T1-T4 → L1-L4 → 4 形态输出）",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "用户问题/场景描述"},
            "level_hint": {"type": "string", "enum": ["T1", "T2", "T3", "T4"], "description": "输入深度"},
            "context": {"type": "object", "description": "行业/工艺/危机等级等"},
        },
        "required": ["query"],
    },
)
def qcm_research(query: str, level_hint: Optional[str] = None, context: Optional[Dict] = None) -> Dict[str, Any]:
    """端到端调研 · 接入 LLM Router"""
    # T-L 路由（规则保持）
    if level_hint is None:
        n = len(query)
        level_hint = "T1" if n < 50 else ("T2" if n < 150 else ("T3" if n < 400 else "T4"))
    layer_map = {"T1": "L1", "T2": "L2", "T3": "L3", "T4": "L4"}
    layer = layer_map.get(level_hint, "L2")

    # 工具匹配（规则保持 · V8.6.2 修复 tools.md 键不匹配 + 懒加载）
    tools_used = []
    corpus = load_corpus()
    tools_md = _get_tools_md(corpus)
    query_lower = query.lower()
    for m in re.finditer(r"^## ([A-F]\d+)\. (.+)$", tools_md, re.M):
        num, name = m.group(1), m.group(2).strip()
        first_kw = re.split(r"[\s（(]", name)[0].lower()
        if first_kw and first_kw in query_lower:
            tools_used.append(f"{num} {name[:30]}")
            # 懒加载：命中工具 → 载入该工具章节（LLM 语境增强 · -98% 上下文）
            sec = _load_tools_section(name)
            if sec:
                tools_used.append(f"{num}·已载入段落 {len(sec.splitlines())} 行")
            if len(tools_used) >= 5:
                break

    # LLM 增强输出
    if LLM_AVAILABLE and LLM_ROUTER:
        system_prompt = """你是 QCM + 质量管控专家。按 action-orders.md 协议给出 5 段式输出：
1. 行动要项（围堵/消除/纠正/预防）
2. 事态导航（时间线 + 决策点）
3. 危机沟通（ITIL P1-P4）
4. 行动措施（具体步骤 + 责任人）
5. 双归零（技术归零 + 管理归零）
要求：专业、严谨、有数据支撑、引用大师观点。"""

        llm_result = LLM_ROUTER.call(
            prompt=f"问题：{query}\n层级：{layer}\n工具：{', '.join(tools_used[:5]) if tools_used else '默认'}",
            task="research",
            system=system_prompt,
            max_tokens=600,
            temperature=0.3,
        )
        output_md = llm_result["text"]
        confidence = 0.92 if llm_result["mode"] == "real" else 0.75
        llm_meta = {
            "provider": llm_result["provider"],
            "mode": llm_result["mode"],
            "duration_s": llm_result["duration_s"],
        }
    else:
        # fallback（无 LLM Router 时）
        output_md = f"""# QCM 调研输出（{layer}）

## 行动要项
- 围堵遏制（24h）：立即排查 `{query[:40]}...` 主因
- 消除阶段（1-2 周）：落地 PDCA + 8D D1-D4

## 事态导航
- 输入深度：{level_hint}
- 决策层级：{layer}
- 工具落格：{', '.join(tools_used[:5]) if tools_used else 'SPC/FMEA/8D 默认'}

## 危机沟通
- D 总分估算：基于 query 长度 {len(query)} 推断 = 3
- ITIL P：P3 Medium

## 行动措施
- T1：5 字段快响
- T2：13 字段标准应答
- T3：17 字段深度分析
- T4：22 字段完整输入

## 双归零
- 技术归零：变异消除 + 流程锁定
- 管理归零：体系审核 + 责任追溯
"""
        confidence = 0.78 if tools_used else 0.55
        llm_meta = {"provider": "v0.1-rule", "mode": "fallback"}

    return {
        "version": f"QCM {PROTOCOL_VERSION} V8.3.0",
        "form": "case-application",
        "layer": layer,
        "input_level": level_hint,
        "tools_used": tools_used,
        "output_markdown": output_md,
        "confidence": confidence,
        "llm_meta": llm_meta,
        "protocol_reference": "action-orders.md §1-§7",
    }


# ---------- Tool 2: qcm_score_source ----------
@register_tool(
    name="qcm_score_source",
    description="5 维评分（主题30% + 可信40% + 时效20% + 完整10%）",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "content": {"type": "string"},
            "domain": {"type": "string", "description": "行业/工艺/工具域"},
        },
        "required": ["url", "content"],
    },
)
def qcm_score_source(url: str, content: str, domain: Optional[str] = None) -> Dict[str, Any]:
    """5 维评分（规则版）"""
    # 主题一致性（domain 命中关键词）
    domain_score = 60.0
    if domain:
        domain_kws = ["汽车", "电子", "航空", "医疗", "SPC", "FMEA", "8D", "DMAIC"]
        if any(k in domain for k in domain_kws):
            domain_score = 85.0

    # 来源可信度（基于 URL 域名）
    trusted_domains = ["iso.org", "asq.org", "aiag.org", "vda-qmc.de", "iattf.com", "as9100"]
    url_score = 30.0
    for td in trusted_domains:
        if td in url.lower():
            url_score = 95.0
            break
    if "github.com" in url.lower():
        url_score = max(url_score, 70.0)
    if "wikipedia.org" in url.lower():
        url_score = max(url_score, 60.0)

    # 时效性
    freshness = 70.0  # 默认 30-90 天 ×0.9
    # 完整度
    completeness = min(100.0, len(content) / 50.0)

    score = (
        domain_score * 0.30
        + url_score * 0.40
        + freshness * 0.20
        + completeness * 0.10
    )

    tier = 4
    if score >= 80: tier = 1
    elif score >= 65: tier = 2
    elif score >= 50: tier = 3

    gate = "核心自动采集" if score >= 70 else ("需确认" if score >= 40 else "过滤")

    return {
        "score": round(score, 1),
        "tier": tier,
        "gate": gate,
        "breakdown": {
            "主题一致性": round(domain_score, 1),
            "来源可信度": round(url_score, 1),
            "时效性": round(freshness, 1),
            "完整度": round(completeness, 1),
        },
        "domain": domain or "未指定",
        "url": url,
    }


# ---------- Tool 3: qcm_decide ----------
@register_tool(
    name="qcm_decide",
    description="T-L 路由决策（T1-T4 → L1-L4 + 工具 + 大师）",
    input_schema={
        "type": "object",
        "properties": {
            "problem_text": {"type": "string"},
            "urgency": {"type": "string", "enum": ["紧急", "重要", "常规", "例行"]},
        },
        "required": ["problem_text"],
    },
)
def qcm_decide(problem_text: str, urgency: Optional[str] = None) -> Dict[str, Any]:
    """T-L 路由决策（规则版）"""
    # 紧急度 → T 层映射
    urgency_t = {"紧急": "T1", "重要": "T2", "常规": "T3", "例行": "T4"}
    level = urgency_t.get(urgency or "常规", "T2")
    layer_map = {"T1": "L1", "T2": "L2", "T3": "L3", "T4": "L4"}
    layer = layer_map[level]

    # 工具匹配（关键词 · V8.6.2 修复 tools.md 键不匹配）
    corpus = load_corpus()
    tools_md = _get_tools_md(corpus)
    matched = []
    for m in re.finditer(r"^## ([A-F]\d+)\. (.+)$", tools_md, re.M):
        num, name = m.group(1), m.group(2).strip()
        first_kw = re.split(r"[\s（(]", name)[0]
        if first_kw and first_kw in problem_text:
            matched.append(num)
            if len(matched) >= 3:
                break

    # 默认工具集
    if not matched:
        if "变异" in problem_text or "波动" in problem_text:
            matched = ["A01", "F01", "F03"]
        elif "客诉" in problem_text or "投诉" in problem_text:
            matched = ["F01", "F07", "D23"]
        elif "焊接" in problem_text:
            matched = ["A01", "B01", "F01"]
        else:
            matched = ["A01", "B01", "F01"]

    return {
        "level": level,
        "layer": layer,
        "tools": matched,
        "masters": ["戴明", "克劳士比"],
        "rationale": f"urgency={urgency} → {level} → {layer}（围堵/消除/纠正/预防 主维度）",
        "protocol_reference": "action-orders.md §3 决策路由",
    }


# ---------- Tool 4: qcm_solve_problem ----------
@register_tool(
    name="qcm_solve_problem",
    description="5 段式输出 + 双归零判据（行动/导航/沟通/措施/双归零）",
    input_schema={
        "type": "object",
        "properties": {
            "problem_dict": {"type": "object", "description": "T-L 全字段输入"},
            "context": {"type": "object"},
        },
        "required": ["problem_dict"],
    },
)
def qcm_solve_problem(problem_dict: Dict, context: Optional[Dict] = None) -> Dict[str, Any]:
    """5 段式输出（规则版）"""
    pd = problem_dict
    query = pd.get("query", "未知问题")
    return {
        "form": "case-application",
        "version": f"QCM {PROTOCOL_VERSION}",
        "five_section_output": {
            "1_行动要项": f"围堵（24h）：{query[:60]} 立即遏制",
            "2_事态导航": f"输入={pd.get('level', 'T2')} 决策层级={pd.get('layer', 'L2')}",
            "3_危机沟通": "D 总分=3 / ITIL P3 Medium",
            "4_行动措施": "T1-T4 输入框架 + 5 段式 + 双归零",
            "5_双归零": "技术归零 + 管理归零（系统链 + 责任追溯）",
        },
        "protocol_reference": "action-orders.md §6 围堵消除",
    }


# ---------- Tool 5: qcm_audit ----------
@register_tool(
    name="qcm_audit",
    description="字段校验 + 引用追溯 + 五维风险评估",
    input_schema={
        "type": "object",
        "properties": {
            "decision_output": {"type": "object"},
        },
        "required": ["decision_output"],
    },
)
def qcm_audit(decision_output: Dict) -> Dict[str, Any]:
    """审计决策输出（规则版）"""
    warnings = []
    errors = []
    suggestions = []

    # 字段校验
    required = ["query", "level", "layer", "tools_used"]
    for r in required:
        if r not in decision_output:
            errors.append(f"必填字段缺失: {r}")

    # 引用追溯
    if "protocol_reference" not in decision_output:
        warnings.append("protocol_reference 缺失")

    # 五维风险
    risk_dimensions = {
        "覆盖": 95 if "tools_used" in decision_output else 60,
        "有效性": 88,
        "可追溯": 92 if "protocol_reference" in decision_output else 65,
        "可重复": 85,
        "可持续": 80,
    }
    avg_score = sum(risk_dimensions.values()) / 5

    if avg_score < 80:
        suggestions.append("补充数据来源 + 案例引用")

    return {
        "audit_score": round(avg_score, 1),
        "passed": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "suggestions": suggestions,
        "risk_dimensions": risk_dimensions,
        "protocol_reference": "action-orders.md §12 五维风险",
    }


# ---------- Tool 6: qcm_validate ----------
@register_tool(
    name="qcm_validate",
    description="4 形态 × 10 项 = 40 检查矩阵",
    input_schema={
        "type": "object",
        "properties": {
            "output_text": {"type": "string"},
            "form": {"type": "string", "enum": ["case-application", "decision-card", "assessment-report", "quick-response"]},
        },
        "required": ["output_text", "form"],
    },
)
def qcm_validate(output_text: str, form: str) -> Dict[str, Any]:
    """4 形态合规校验（规则版 · 10 项 × 4 = 40 检查）"""
    checks = []

    if form == "case-application":
        items = [
            ("5 段式完整", all(s in output_text for s in ["行动要项", "事态导航", "危机沟通", "行动措施", "双归零"])),
            ("数据说话", "数据" in output_text or "实测" in output_text or "评分" in output_text),
            ("双归零判据", "归零" in output_text or "复发" in output_text),
            ("工具编号", bool(re.search(r"[A-F]\d{2}", output_text))),
            ("大师引用", any(m in output_text for m in ["戴明", "朱兰", "克劳士比", "石川", "田口"])),
            ("三链闭环", "发生链" in output_text or "流出链" in output_text or "系统链" in output_text),
            ("治理层级", any(g in output_text for g in ["工序级", "现场级", "车间级", "部门级", "公司级"])),
            ("标准引用", any(s in output_text for s in ["ISO", "IATF", "AS", "VDA", "AIAG"])),
            ("危机等级", "P1" in output_text or "P2" in output_text or "P3" in output_text or "P4" in output_text or "D" in output_text),
            ("可追溯", "action-orders" in output_text or "cases" in output_text or "§" in output_text),
        ]
    elif form == "decision-card":
        items = [
            ("3 行精简", len(output_text.split("\n")) <= 5),
            ("工具明确", bool(re.search(r"[A-F]\d{2}", output_text))),
            ("责任清晰", "责任" in output_text or "责任人" in output_text),
            ("数据支撑", any(c.isdigit() for c in output_text)),
            ("风险标识", "风险" in output_text or "D" in output_text),
            ("治理层级", any(g in output_text for g in ["工序级", "现场级", "车间级", "部门级", "公司级"])),
            ("24h 围堵", "24" in output_text or "围堵" in output_text),
            ("可执行", "做" in output_text or "执行" in output_text or "启动" in output_text),
            ("标准引用", any(s in output_text for s in ["ISO", "IATF", "AS", "VDA"])),
            ("合规", "合规" in output_text or "通过" in output_text),
        ]
    elif form == "assessment-report":
        items = [
            ("4 层 × 25 分", "25 分" in output_text or "100" in output_text),
            ("趋势分析", "趋势" in output_text or "环比" in output_text),
            ("根因分析", "根因" in output_text),
            ("治理水平", "治理" in output_text),
            ("标准对齐", any(s in output_text for s in ["ISO", "IATF", "AS", "VDA"])),
            ("文化评估", "文化" in output_text),
            ("可持续", "可持续" in output_text or "持续" in output_text),
            ("可对比", "对比" in output_text or "基线" in output_text),
            ("数据源", "来源" in output_text or "数据" in output_text),
            ("可审计", "audit" in output_text.lower() or "审计" in output_text),
        ]
    else:  # quick-response
        items = [
            ("30 秒判定", len(output_text) < 200),
            ("D 总分", "D" in output_text or "总分" in output_text),
            ("应急动作", "应急" in output_text or "立即" in output_text),
            ("责任人", "责任" in output_text or "人" in output_text),
            ("上报路径", "上报" in output_text or "路径" in output_text),
            ("复盘", "复盘" in output_text),
            ("预防", "预防" in output_text),
            ("工具", bool(re.search(r"[A-F]\d{2}", output_text))),
            ("标准", any(s in output_text for s in ["ISO", "IATF", "AS"])),
            ("合规", "合规" in output_text or "通过" in output_text),
        ]

    passed = sum(1 for _, ok in items if ok)
    failed = [name for name, ok in items if not ok]

    return {
        "form": form,
        "checks_passed": passed,
        "checks_total": len(items),
        "score": round(passed / len(items) * 100, 1),
        "failures": failed,
        "protocol_reference": "outputs/ 4 形态 × 10 项 = 40 检查",
    }


# ---------- Tool 7: qcm_attribution（§8 归因 + §8.5 三级降级）----------
try:
    from infoseek_bridge import qcm_attribution as _bridge_attribution
    from infoseek_bridge import qcm_attribution_phase as _bridge_phase
    from gap_detector import QCMGapDetector
    INFOSEEK_BRIDGE_AVAILABLE = True
except ImportError:
    INFOSEEK_BRIDGE_AVAILABLE = False
    _bridge_attribution = None
    _bridge_phase = None

_GAP_DETECTOR = QCMGapDetector() if 'QCMGapDetector' in dir() else None


@register_tool(
    name="qcm_attribution",
    description="QCM-Infoseek 归因（§8 协议 · 5 维触发 ≥2 → 调研 → 4 形态路由）· Infoseek 未安装时三级降级（L1 本地/L2 Web/L3 协议）",
    input_schema={
        "type": "object",
        "properties": {
            "unparsed_query": {"type": "string", "description": "用户原始问题/场景描述"},
            "qcm_failure_dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "5 维触发信号：行业/危机类型/工具/标准/大师（'ok' 或失败描述）",
            },
            "industry_hint": {"type": "string", "description": "行业提示（可选）"},
            "mds_fields": {"type": "object", "description": "MDS 输入字段（可选）"},
        },
        "required": ["unparsed_query", "qcm_failure_dimensions"],
    },
)
def qcm_attribution(unparsed_query: str, qcm_failure_dimensions: List[str],
                    industry_hint: Optional[str] = None,
                    mds_fields: Optional[Dict] = None) -> Dict[str, Any]:
    """§8 QCM-Infoseek 归因协议 + §8.5 三级降级"""
    if not INFOSEEK_BRIDGE_AVAILABLE:
        # 桥接模块缺失（异常环境）→ 本地兜底
        from infoseek_bridge import qcm_attribution
        return qcm_attribution(unparsed_query, qcm_failure_dimensions,
                               industry_hint, mds_fields)
    return _bridge_attribution(unparsed_query, qcm_failure_dimensions,
                               industry_hint, mds_fields)


# ---------- Tool 8: qcm_attribution_phase（§13.3 3 阶段混合策略）----------
@register_tool(
    name="qcm_attribution_phase",
    description="QCM-Infoseek 3 阶段混合策略（§13.3）· Phase 1 浅层锚点 / Phase 2 research_v3 / Phase 3 research_stream 流式",
    input_schema={
        "type": "object",
        "properties": {
            "unparsed_query": {"type": "string", "description": "用户原始问题"},
            "qcm_failure_dimensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "5 维触发信号（'ok' 或失败描述）",
            },
            "phase": {"type": "integer", "enum": [1, 2, 3], "description": "指定阶段（默认自动判断）"},
            "user_explicit": {"type": "boolean", "default": False, "description": "用户显式深度调研"},
            "industry_hint": {"type": "string", "description": "行业提示"},
        },
        "required": ["unparsed_query", "qcm_failure_dimensions"],
    },
)
def qcm_attribution_phase(unparsed_query: str, qcm_failure_dimensions: List[str],
                          phase: Optional[int] = None,
                          user_explicit: bool = False,
                          industry_hint: Optional[str] = None) -> Dict[str, Any]:
    """§13.3 混合策略 3 阶段触发"""
    if not INFOSEEK_BRIDGE_AVAILABLE:
        from infoseek_bridge import qcm_attribution_phase
        return qcm_attribution_phase(unparsed_query, qcm_failure_dimensions,
                                     phase, user_explicit, industry_hint)
    return _bridge_phase(unparsed_query, qcm_failure_dimensions,
                         phase, user_explicit, industry_hint)


# ---------- Tool 9: qcm_gap_detect（§13 缺口暴露驱动）----------
@register_tool(
    name="qcm_gap_detect",
    description="QCM 5 维缺口暴露驱动（§13）· 行业/工艺/工具/标准/大师缺口评分 + 触发计划 + 层级映射",
    input_schema={
        "type": "object",
        "properties": {
            "case": {
                "type": "object",
                "description": "案例：{industry, process, tools[], standards[], masters[]}",
            },
        },
        "required": ["case"],
    },
)
def qcm_gap_detect(case: Dict[str, Any]) -> Dict[str, Any]:
    """§13 5 维缺口检测 + 触发计划 + 层级映射"""
    if _GAP_DETECTOR is None:
        from gap_detector import QCMGapDetector
        det = QCMGapDetector()
    else:
        det = _GAP_DETECTOR
    scores = det.detect(case)
    plan = det.trigger_plan(scores)
    return {
        "gap_scores": scores,
        "trigger_plan": plan,
        "protocol_reference": "action-orders.md §13",
    }


# ---------- Tool 10: qcm_guardian（§多平台 · 守卫中心跨平台触发入口）----------
@register_tool(
    name="qcm_guardian",
    description="QCM 守卫中心跨平台触发入口（M0 多生态平台适用）。在 MCP 侧暴露 guardian 守卫运行能力，"
                "使非 WorkBuddy 生态（CI / 其他 skill / 外部 MCP 客户端）也能直接触发 QCM 守卫定时器逻辑。"
                "支持 phase=register(注册缺口核验)/decision(决策校准环)/nightrun(夜巡决策环)；"
                "可选 guard 单守卫精确定位。只读检测（不写回词库）——写回由 qcm_nightrun 夜巡脚本专门段负责。",
    input_schema={
        "type": "object",
        "properties": {
            "phase": {
                "type": "string",
                "enum": ["register", "decision", "nightrun"],
                "description": "守卫相位：register=注册缺口归一化核验 / decision=决策校准环(含 g017 反向族) / nightrun=夜巡决策环",
            },
            "guard": {
                "type": "string",
                "description": "单守卫 ID 精确定位（如 g019_runtime_cache / g020_file_homology），缺省跑该 phase 全部守卫",
            },
        },
        "required": ["phase"],
    },
)
def qcm_guardian(phase: str, guard: Optional[str] = None) -> Dict[str, Any]:
    """跨平台守卫触发（路径 B）：转发 guardian.py 运行，返回结构化结果

    安全边界：仅运行检测（只读），不触发写回（写回由 word_evolution.sh 专门段负责），
    避免 MCP 客户端误触发词库/语料写操作。
    """
    import subprocess
    try:
        from paths import QCM_ROOT
    except Exception:
        QCM_ROOT = os.environ.get("QCM_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    py = os.environ.get("QCM_PYTHON", "python3")
    cmd = [py, os.path.join(QCM_ROOT, "core", "guardian.py")]
    if phase == "nightrun":
        cmd.append("--nightrun")
    else:
        cmd += ["--phase", phase]
    if guard:
        cmd += ["--guard", guard]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120)
        text = (out.stdout or "") + (out.stderr or "")
        # 粗略解析严重/警告计数（guardian 输出末行格式：严重 N · 警告 M）
        sev = warn = 0
        for ln in text.splitlines():
            m = re.search(r"严重\s*(\d+)", ln)
            if m: sev = int(m.group(1))
            m = re.search(r"警告\s*(\d+)", ln)
            if m: warn = int(m.group(1))
        return {
            "phase": phase,
            "guard": guard or "all",
            "exit_code": out.returncode,
            "severe": sev,
            "warning": warn,
            "passed": out.returncode == 0 and sev == 0,
            "output_tail": "\n".join(text.splitlines()[-20:]),
            "protocol_reference": "guardian.yaml · 守卫中心归一化",
        }
    except Exception as e:
        return {
            "phase": phase,
            "guard": guard or "all",
            "exit_code": -1,
            "severe": -1,
            "warning": -1,
            "passed": False,
            "error": str(e),
            "protocol_reference": "guardian.yaml · 守卫中心归一化",
        }


# ---------- Tool 11: qcm_corpus_read（M0.a · 热度层捕获感知语料读取）----------
@register_tool(
    name="qcm_corpus_read",
    description="读取 QCM 大语料单个章节（capture 感知 · 走 load_section 埋点）。"
                "MCP 形态下优先于直接 Read references/** —— 其访问会被 ref_heat 月度回灌采集，"
                "用于校准 M3 同根阈值。stem 为语料名（如 tools / masters / knowledge/iso）；"
                "title 为章节标题（支持模糊匹配），为空则返回首个有效章节（若语料索引含锚点）。",
    input_schema={
        "type": "object",
        "properties": {
            "stem": {"type": "string", "description": "语料 stem，如 tools / masters / knowledge/iso（非 references/ 路径）"},
            "title": {"type": "string", "description": "章节标题（模糊匹配）；为空取首个锚点章节", "default": ""},
        },
        "required": ["stem"],
    },
)
def qcm_corpus_read(stem: str, title: Optional[str] = "") -> Dict[str, Any]:
    """capture 感知语料读取：包装已埋点的 load_section（D7/M0.a）。失败安全。"""
    try:
        from corpus_loader import load_section, CORPUS_FILES
        if stem not in CORPUS_FILES:
            # 宽松提示：列出可用 stem，便于 Agent 改正调用（不静默失败）
            avail = sorted(CORPUS_FILES.keys())
            return {
                "stem": stem,
                "title": title or "",
                "section_text": "",
                "found": False,
                "available_stems": avail,
                "note": "stem 不在 CORPUS_FILES；MCP 形态请用 qcm_corpus_read 而非直读",
                "protocol_reference": "corpus_loader.load_section（capture 感知）",
            }
        sec = load_section(stem, title or "")
        return {
            "stem": stem,
            "title": title or "",
            "section_text": sec,
            "found": bool(sec),
            "protocol_reference": "corpus_loader.load_section（capture 感知）",
        }
    except Exception as e:
        return {
            "stem": stem,
            "title": title or "",
            "section_text": "",
            "found": False,
            "error": str(e),
            "protocol_reference": "corpus_loader.load_section（capture 感知）",
        }


# ---------- Tool 12: qcm_corpus_search（M0.a · 热度层捕获感知语料搜索）----------
@register_tool(
    name="qcm_corpus_search",
    description="跨 QCM 大语料关键词搜索（capture 感知 · 走 search_corpus 埋点）。"
                "MCP 形态下优先于直接 Grep references/** —— 命中语料的访问会被 ref_heat 采集。"
                "返回 [{file, line, text}] 片段（非全量，防上下文爆炸）；tier 感知排序。",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "关键词"},
            "max_hits": {"type": "integer", "default": 5, "description": "最多返回命中数"},
        },
        "required": ["query"],
    },
)
def qcm_corpus_search(query: str, max_hits: int = 5) -> Dict[str, Any]:
    """capture 感知语料搜索：包装已埋点的 search_corpus（D7/M0.a）。失败安全。

    D4 修复后 search_corpus 对「命中语料 stem」逐一埋点（检索命中即引用），
    故本工具即复活 search_corpus 死路径 + 补全其余 references/** 的捕获。
    """
    try:
        from corpus_loader import search_corpus
        results = search_corpus(query, max_hits=int(max_hits))
        return {
            "query": query,
            "hits": results,
            "count": len(results),
            "protocol_reference": "corpus_loader.search_corpus（capture 感知）",
        }
    except Exception as e:
        return {
            "query": query,
            "hits": [],
            "count": 0,
            "error": str(e),
            "protocol_reference": "corpus_loader.search_corpus（capture 感知）",
        }


# ============ JSON-RPC 协议处理 ============

# ============ 工具注册辅助（mcp_server 调用） ============
# V8.6 P3 · R13 蓝图落地：统一行为契约 _qcm_contract（链 B 履约单元）
# 契约映射表（9 工具一次性成本 · intent/domain/form/objects_used 静态声明）
# 目的：统一出口语义——每次工具调用 = 一个契约实例；采样/登记/分发全部消费契约
CONTRACT_MAP: Dict[str, Dict[str, Any]] = {
    "qcm_research":          {"intent": "④知识学习", "domain": ["通用"],    "form": "quick_response",    "objects_used": ["corpus", "llm_router"]},
    "qcm_score_source":      {"intent": "③评估审计", "domain": ["通用"],    "form": "assessment_report", "objects_used": ["corpus"]},
    "qcm_decide":            {"intent": "①危机处置", "domain": ["通用"],    "form": "case_application",  "objects_used": ["router"]},
    "qcm_solve_problem":     {"intent": "①危机处置", "domain": ["通用"],    "form": "case_application",  "objects_used": ["assembler"]},
    "qcm_audit":             {"intent": "③评估审计", "domain": ["通用"],    "form": "assessment_report", "objects_used": ["corpus", "router"]},
    "qcm_validate":          {"intent": "③评估审计", "domain": ["通用"],    "form": "assessment_report", "objects_used": ["assembler"]},
    "qcm_attribution":       {"intent": "⑤知识沉淀", "domain": ["通用"],    "form": "case_application",  "objects_used": ["router", "assembler"]},
    "qcm_attribution_phase": {"intent": "⑤知识沉淀", "domain": ["通用"],    "form": "case_application",  "objects_used": ["router"]},
    "qcm_gap_detect":        {"intent": "③评估审计", "domain": ["通用"],    "form": "assessment_report", "objects_used": ["gap_detector"]},
    "qcm_guardian":          {"intent": "③评估审计", "domain": ["通用"],    "form": "assessment_report", "objects_used": ["guardian"]},
    "qcm_corpus_read":      {"intent": "④知识学习", "domain": ["通用"],    "form": "quick_response",    "objects_used": ["corpus_loader"]},
    "qcm_corpus_search":    {"intent": "④知识学习", "domain": ["通用"],    "form": "quick_response",    "objects_used": ["corpus_loader"]},
}
CONTRACT_VERSION = "1.0"


def _qcm_contract(name: str, **extra) -> Dict[str, Any]:
    """构造统一行为契约实例（R13 链 B 履约单元 · 只增不改向后兼容）

    {intent, domain, form, objects_used} + version + 调用方附加字段（llm_meta 等）
    """
    base = dict(CONTRACT_MAP.get(name, {}))
    base.setdefault("intent", "④知识学习")   # 未映射工具保守归学习意图（可扩展登记）
    base.setdefault("domain", ["通用"])
    base.setdefault("form", "quick_response")
    base.setdefault("objects_used", [])
    base["version"] = CONTRACT_VERSION
    for k, v in extra.items():
        base[k] = v
    return base


def register_all(target_registry: Dict[str, Dict[str, Any]], wrap: bool = True):
    """把 TOOL_DEFS 注册进目标注册表（mcp_server.TOOL_REGISTRY）

    V8.6 P2：wrap=True 时把 handler 替换为 _tool_usage_wrapper 织入采样——
      本地直调场景（不经 MCP 网关）也能采样；网关场景由 x_qcm_sampled 防双计。
    """
    for d in TOOL_DEFS:
        entry = dict(d)
        if wrap:
            entry["handler"] = _tool_usage_wrapper(d["handler"], d["name"])
        target_registry[d["name"]] = entry
    return len(TOOL_DEFS)
