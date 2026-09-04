#!/usr/bin/env python3
"""qcm_router.py — QCM 场景路由（action-orders §14 · 词库归一化）

意图 6 × 领域 8 双维路由：
  - 词库单一真源：references/keyword.yaml（静态 + 热词 + 歧义 + 同义词）
  - 协议规则：action-orders §14（路由流程/置信度/矩阵/形态）
  - 动态热词：keyword.yaml level=hot（§11 生命周期）
  - 降级：hotword_level 标注（L0 完整 / L3[no-external-source]）
  - 深层实时：need_research 标记 + suggest_research 接口（置信度门控）

用法：
  from router import route
  result = route("CNC 镗孔椭圆 0.002mm 怎么办")
"""
import os
from paths import KEYWORD_YAML, ENTITIES_YAML, REF_CONFIG
import re
from typing import Dict, List, Optional

# ============ 词库加载（单一真源 · keyword.yaml） ============
KEYWORD_PATH = os.environ.get(
    "QCM_KEYWORDS", str(KEYWORD_YAML))

INTENT_KEYWORDS: Dict[str, List[str]] = {}
DOMAIN_KEYWORDS: Dict[str, List[str]] = {}
AMBIGUOUS_TERMS: List[str] = []
OPTIMIZE_VERBS: List[str] = []
SYNONYM_MAP: Dict[str, str] = {}  # 同义词 → 主词
_load_state = {"loaded": False, "level": "L0", "capacity_warn": []}

# ============ 路由阈值配置（V8.4 · router.yaml 外置 · 缺失用默认值兜底） ============
DEFAULT_THRESHOLDS = {
    "high_score_base": 0.8, "high_score_step": 0.05, "high_score_cap": 0.99,
    "low_score_base": 0.5, "low_score_step": 0.1, "fallback": 0.2,
    "score_high": 3, "score_low": 1, "clarify": 0.3,
}
THRESHOLDS = dict(DEFAULT_THRESHOLDS)
ROUTER_CFG_PATH = os.environ.get("QCM_ROUTER_CFG", str(REF_CONFIG / "router.yaml"))
_threshold_loaded = False


def load_thresholds() -> dict:
    """加载路由阈值配置（router.yaml · 配置驱动 §14.4）

    缺失/解析失败 → 内置默认值（防御性降级，等价现状）。
    """
    global _threshold_loaded
    if _threshold_loaded:
        return THRESHOLDS
    _threshold_loaded = True
    if not os.path.exists(ROUTER_CFG_PATH):
        return THRESHOLDS
    try:
        import yaml
        data = yaml.safe_load(open(ROUTER_CFG_PATH, encoding="utf-8")) or {}
        for k, v in (data.get("thresholds") or {}).items():
            if k in THRESHOLDS and isinstance(v, (int, float)):
                THRESHOLDS[k] = v
    except Exception:
        pass  # 配置失败 → 默认值
    return THRESHOLDS


# ============ 置信度阈值矩阵（MDS 动态自适应 · L2+M3 · router.yaml clarify_matrix） ============
CLARIFY_MATRIX = {}
_CLARIFY_MATRIX_LOADED = False


def load_clarify_matrix() -> dict:
    """加载置信度阈值矩阵（clarify_matrix · 配置驱动 · 缺失用默认 0.3 兜底）

    与 load_thresholds 同构：一次性加载、防御性降级。
    effective_floor = max(intent_overrides[intent], domain_overrides[domain],
                           crisis_overrides[F24], default)，再由 M3 与 F13 耦合。
    """
    global _CLARIFY_MATRIX_LOADED
    if _CLARIFY_MATRIX_LOADED:
        return CLARIFY_MATRIX
    _CLARIFY_MATRIX_LOADED = True
    if not os.path.exists(ROUTER_CFG_PATH):
        return CLARIFY_MATRIX
    try:
        import yaml
        data = yaml.safe_load(open(ROUTER_CFG_PATH, encoding="utf-8")) or {}
        cm = data.get("clarify_matrix") or {}
        if isinstance(cm, dict):
            CLARIFY_MATRIX.update({
                "default": float(cm.get("default", 0.3)),
                "intent_overrides": dict(cm.get("intent_overrides") or {}),
                "domain_overrides": dict(cm.get("domain_overrides") or {}),
                "crisis_overrides": dict(cm.get("crisis_overrides") or {}),
            })
    except Exception:
        pass  # 配置失败 → 默认矩阵
    return CLARIFY_MATRIX


# ============ 归零事件复用建议配置（H2 接线 · router.yaml zero_event_hint · 缺失 disabled 兜底） ============
ZE_HINT = {"enabled": False, "trigger_intents": [], "match_on": [], "min_sim": 0.5, "operator": "", "hint": ""}
_ZE_HINT_LOADED = False


def load_zero_event_hint() -> dict:
    """加载归零事件复用建议配置（zero_event_hint · 配置驱动 · 缺失用默认 disabled 兜底）

    与 load_thresholds 同构：一次性加载、防御性降级；enabled=false 时 route() 不触发建议。
    """
    global _ZE_HINT_LOADED
    if _ZE_HINT_LOADED:
        return ZE_HINT
    _ZE_HINT_LOADED = True
    if not os.path.exists(ROUTER_CFG_PATH):
        return ZE_HINT
    try:
        import yaml
        data = yaml.safe_load(open(ROUTER_CFG_PATH, encoding="utf-8")) or {}
        h = data.get("zero_event_hint") or {}
        ZE_HINT.update({
            "enabled": bool(h.get("enabled", False)),
            "trigger_intents": list(h.get("trigger_intents") or []),
            "match_on": list(h.get("match_on") or []),
            "min_sim": float(h.get("min_sim", 0.5)),
            "operator": h.get("operator", ""),
            "hint": h.get("hint", ""),
        })
    except Exception:
        pass  # 配置失败 → 默认 disabled
    return ZE_HINT


def _effective_floor(intent: str, domains: list, mds: dict, th: dict) -> float:
    """计算自适应置信度门槛（MDS 动态自适应核心）

    - 矩阵：default → intent_overrides(直接覆盖·允许低于 default 给低风险意图)
            → domain_overrides / crisis_overrides(F24) / F13(只抬不降·风险加性)
    - 耦合：MDS F13 输入自报置信度（低自报→抬高门槛）
    - 安全夹取 [0.05, 0.95]
    """
    cm = load_clarify_matrix()
    floor = float(cm.get("default") or th.get("clarify", 0.3))
    # 意图：直接覆盖（低风险意图可低于 default，如 ⑤知识沉淀 0.2）
    io = cm.get("intent_overrides") or {}
    if intent in io and io[intent] is not None:
        floor = float(io[intent])
    # 领域：只抬（风险域加性）
    if domains:
        do = cm.get("domain_overrides") or {}
        if domains[0] in do and do[domains[0]] is not None:
            floor = max(floor, float(do[domains[0]]))
    # 危机等级：只抬
    if isinstance(mds, dict) and mds.get("F24"):
        co = cm.get("crisis_overrides") or {}
        cv = co.get(str(mds["F24"]))
        if cv is not None:
            floor = max(floor, float(cv))
    # F13 输入自报置信度：低自报只抬
    if isinstance(mds, dict) and isinstance(mds.get("F13"), (int, float)):
        f13 = max(0.0, min(1.0, float(mds["F13"])))
        f13_floor = 0.6 - 0.4 * f13   # F13=0.9→0.24 / F13=0.3→0.48 / F13=0.1→0.56
        floor = max(floor, f13_floor)
    return max(0.05, min(0.95, floor))


def _build_clarify_prompt(intent: str, domains: list, mds: dict) -> str:
    """消费 need_clarify 信号 → 生成 F1-F4 最小必要集澄清问句（M2 · 不复用 5Why）"""
    try:
        from clarify_input import generate_clarify
        return generate_clarify({"intent": intent, "domain": domains}, mds)
    except Exception:
        return "为精准路由，请补充最小必要信息：F1 场景描述 / F2 涉及范围 / F3 影响对象 / F4 期望产出"


# ============ 实体索引加载（V8.4 P1 · entities.yaml） ============
ENTITIES: List[Dict] = []
ENTITY_PATH = os.environ.get("QCM_ENTITIES", str(ENTITIES_YAML))
_entity_loaded = False


def load_entities() -> List[Dict]:
    """加载实体索引（entities.yaml · 标准/大师 等）

    返回实体列表；缺失时返回空列表（实体为可选增强，不影响基础路由）。
    """
    global _entity_loaded
    if _entity_loaded:
        return ENTITIES
    _entity_loaded = True
    if not os.path.exists(ENTITY_PATH):
        return ENTITIES
    try:
        import yaml
        data = yaml.safe_load(open(ENTITY_PATH, encoding="utf-8")) or {}
        ENTITIES.extend(data.get("entities", []))
    except Exception:
        pass  # 实体层失败不影响路由（防御性降级）
    return ENTITIES


def match_entities(text: str) -> List[Dict]:
    """实体匹配：实体名/别名命中 → 返回命中的实体（含 type/domain/intent）

    V8.4 A3 修复：函数自包含——text 统一小写（此前依赖 route 预先 lower，
    外部直接调用大写 text 恒不匹配）。
    M1.0 ②：命中实体时记录正向命中热度（record_entity_hit）→ 实体级使用事实校准输入。
    """
    if not load_entities():
        return []
    text_low = text.lower()
    hits = []
    for e in ENTITIES:
        names = [e.get("name", "")] + list(e.get("aliases", []))
        for n in names:
            if n and n.lower() in text_low:
                hits.append(e)
                break
    # 实体正向命中观测（M1.0 ② · 失败静默降级，不影响路由）
    if hits:
        try:
            from hit_tracker import record_entity_hit
            for e in hits:
                record_entity_hit(e.get("name", ""))
        except Exception:
            pass
    return hits


def load_keywords() -> str:
    """加载归一化词库（keyword.yaml · 单一真源）

    返回降级等级：
      L0 = 词库加载完整（静态 + 热词）
      L3 = 词库缺失（[no-external-source] · 内置最小词表兜底）
    V8.6.2 P0：冷启动词头索引可观测（keyword_head_index 供 SKILL 上下文裁剪指引）
    """
    if _load_state["loaded"]:
        return _load_state["level"]
    # P0 词头索引：冷启动首载标记（供懒加载观测/指引）
    _load_state["head_loaded_first"] = _load_state.get("head_loaded_first", 0) + 1

    path = os.environ.get("QCM_KEYWORDS", KEYWORD_PATH)
    if not os.path.exists(path):
        # L3 降级：内置最小词表（制造业核心 · 防路由完全失效）
        _load_state["level"] = "L3[no-external-source]"
        # 降级保底词表（词库文件缺失时的最小可用集 · 高频基础词）
        INTENT_KEYWORDS.update({"①危机处置": ["失效", "缺陷", "客诉", "裂纹", "椭圆", "超差", "异常"],
                                "②流程优化": ["优化", "改善", "提升"],
                                "③评估审计": ["评估", "审核"],
                                "④知识学习": ["什么是", "是什么", "标准"],
                                "⑤知识沉淀": ["新行业", "适配"]})
        DOMAIN_KEYWORDS.update({"A制造": ["工艺", "参数", "工序"],
                                "B设计": ["设计", "开发"],
                                "C供应链": ["供应商", "采购"],
                                "Q客户": ["客户", "客诉"]})
        _load_state["loaded"] = True
        return _load_state["level"]

    try:
        import yaml
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception:
        _load_state["level"] = "L3[no-external-source]"
        _load_state["loaded"] = True
        return _load_state["level"]

    for item in data.get("keywords", []):
        word = str(item.get("word", "")).lower()
        if not word:
            continue
        # V8.4 P5：archived 词退出活跃路由（§11.2 生命周期语义 · 归档=不参与路由但保留记录）
        if item.get("status") == "archived":
            continue
        is_base = item.get("level", "base") == "base"
        if item.get("intent"):
            kws = INTENT_KEYWORDS.setdefault(item["intent"], [])
            kws.append(word)
            if is_base:
                _load_state.setdefault("_base_intent_count", {}).setdefault(item["intent"], 0)
                _load_state["_base_intent_count"][item["intent"]] += 1
        if item.get("domain"):
            kws = DOMAIN_KEYWORDS.setdefault(item["domain"], [])
            kws.append(word)
            if is_base:
                _load_state.setdefault("_base_domain_count", {}).setdefault(item["domain"], 0)
                _load_state["_base_domain_count"][item["domain"]] += 1
        if item.get("role") == "ambiguous":
            AMBIGUOUS_TERMS.append(word)
        elif item.get("role") == "optimize_verb":
            OPTIMIZE_VERBS.append(word)
        # V8.4 字典归一化级 1（渐进式）：词条 aliases 变体 → 并入意图/领域词表（命中变体=命中主词）
        # 与实体层 aliases 模式对齐（统一词条模型 · 变体全覆盖 · aliases 不占 base 容量）
        for alias in item.get("aliases") or []:
            a = str(alias).lower()
            if not a or a == word:
                continue
            if item.get("intent"):
                INTENT_KEYWORDS.setdefault(item["intent"], []).append(a)
            if item.get("domain"):
                DOMAIN_KEYWORDS.setdefault(item["domain"], []).append(a)

    # 同义词归一化（P1-2）：副词 → 主词
    for main, alts in (data.get("synonyms") or {}).items():
        for a in alts:
            SYNONYM_MAP[str(a).lower()] = str(main).lower()

    # 容量约束检查（S1 · 容量自适应容器）：静态层（base）每意图 ≤capacity 词 / 每领域 ≤capacity 词
    # 热词层（hot）由 §11 生命周期天然管理，不占容量
    # 限值统一从 core/capacity.py 读取（router.yaml capacity 段 · 差异化覆盖 + adaptive 模式）
    try:
        from capacity import get_limit
        for intent, cnt in _load_state.get("_base_intent_count", {}).items():
            lim = get_limit("intent", intent, sum(_load_state.get("_base_intent_count", {}).values()))
            if cnt > lim:
                _load_state["capacity_warn"].append(f"{intent}: 静态 {cnt} 词超限({lim})")
        for domain, cnt in _load_state.get("_base_domain_count", {}).items():
            lim = get_limit("domain", domain)
            if cnt > lim:
                _load_state["capacity_warn"].append(f"{domain}: 静态 {cnt} 词超限({lim})")
    except Exception:
        # 容器不可用 → 回退历史硬编码（零回归）
        for intent, cnt in _load_state.get("_base_intent_count", {}).items():
            if cnt > 40:
                _load_state["capacity_warn"].append(f"{intent}: 静态 {cnt} 词超限(40)")
        for domain, cnt in _load_state.get("_base_domain_count", {}).items():
            if cnt > 20:
                _load_state["capacity_warn"].append(f"{domain}: 静态 {cnt} 词超限(20)")

    _load_state["level"] = "L0"
    _load_state["loaded"] = True
    return _load_state["level"]


def _normalize(text: str) -> str:
    """同义词归一化（匹配前文本归一）· V8.4 边界加固：None/非 str 安全"""
    if not isinstance(text, str):
        text = str(text or "")
    t = text.lower()
    for alt, main in SYNONYM_MAP.items():
        if alt and alt in t:
            t = t.replace(alt, main)
    return t


def _count_hits(text: str, keywords: List[str]) -> int:
    """统计特征词命中数（词库已归一化）"""
    return sum(1 for kw in keywords if kw and kw in text)


def _resolve_ambiguity(text: str, current_intent: str, word: str = "") -> str:
    """歧义消解（V8.4 P2 · 三级链：AI 语义消解 → Infoseek → 规则兜底）

    仅歧义词触发（调用方已确认 text 含 AMBIGUOUS_TERMS）。
    无 LLM Key / 消解失败 → 规则兜底（优化动词→② · 否则默认① · 与旧行为等价零回归）。
    """
    if word:
        try:
            from ambiguity_resolver import resolve
            r = resolve(text, word)
            if r.get("source") in ("ai", "fixed") and r.get("confidence", 0) >= 0.7:
                return r["intent"]
        except Exception:
            pass  # 消解器异常 → 规则兜底
    if any(v in text for v in OPTIMIZE_VERBS):
        return "②流程优化"
    return current_intent


# ============ 形态映射（§14.6） ============
FORM_MAP = {
    "①危机处置": "case_application",
    "②流程优化": "case_application",  # 借用 5 段式（改善适配）
    "③评估审计": "assessment_report",
    "④知识学习": "quick_response",
    "⑤知识沉淀": "case_application",  # A+B 决策：蒸馏清单走案例应用（原 adapter_pack 幽灵形态退役）
    "⑥质量文化": "assessment_report",
}


def route(query: str, domain_hint: Optional[str] = None, mds: Optional[dict] = None) -> Dict:
    """场景路由主入口

    Args:
        query: 用户输入
        domain_hint: 可选领域提示
        mds: 可选 MDS 输入（含 F13 置信度 / F24 危机等级），驱动门槛动态自适应（M3）
    Returns:
        {'intent', 'domain', 'confidence', 'form', 'gap',
         'need_clarify', 'clarify_prompt', 'keyword_level', 'need_research', 'capacity_warn',
         'load_plan', 'echo'}  # echo: A-① 路由回显（意图→形态 · 偏差可纠正）
    """
    keyword_level = load_keywords()
    text = _normalize(query)

    # ① 意图快速路由（归一化词库）
    scores = {intent: _count_hits(text, kws) for intent, kws in INTENT_KEYWORDS.items()}
    best_intent = max(scores, key=scores.get)
    best_score = scores[best_intent]

    # 歧义处理（V8.4 P2：三级链消解 · 无 Key 自动落规则等价旧行为）
    # BUG FIX（V8.3.1）：仅当歧义词实际归②时才重算 best_score；
    # 否则保留①的原始得分，避免 best_score=0 误触发"未命中→④知识学习"兜底。
    if best_intent == "①危机处置" and any(a in text for a in AMBIGUOUS_TERMS):
        amb_word = next((a for a in AMBIGUOUS_TERMS if a in text), "")
        resolved = _resolve_ambiguity(text, best_intent, amb_word)
        if resolved != best_intent:
            best_intent = resolved
            best_score = _count_hits(text, INTENT_KEYWORDS.get("②流程优化", []))

    # 无任何命中 → 兜底知识学习 + 深层实时标记（P2-3）
    need_research = False
    if best_score == 0:
        best_intent = "④知识学习"
        need_research = True  # 未命中 → 建议调研（触发门槛由调用方统计）
        # 保留 best_score=0（不人为抬到 1）→ 置信度走 fallback(0.2)，
        # 使 need_clarify 门控(M2/M3)对无命中输入真正生效（原 best_score=1 强制 0.6
        # 致 need_clarify 永不触发，悬空信号 GAP-6 失效）。
        # V8.4 闭环 Step 1：观测环——未命中词频次落盘（同词≥3 次触发调研信号）
        try:
            from hit_tracker import record_miss
            known = set()
            for kws in INTENT_KEYWORDS.values():
                known.update(kws)
            for kws in DOMAIN_KEYWORDS.values():
                known.update(kws)
            for e in load_entities():
                known.add(e.get("name", ""))
                known.update(e.get("aliases", []))
            record_miss(text, known)
        except Exception:
            pass  # 观测环失败不影响路由（防御性降级）
    else:
        # S2 使用事实采样：命中词 → 记录 (词, 实际意图, 实际领域, 语境词)（供 ⑰-R3 校准器）
        # CI 隔离：QCM_NO_REPORT=1（ci_core/word_evolution）时跳过——合成测试调用不污染运行观测
        if os.environ.get("QCM_NO_REPORT") != "1":
            try:
                from hit_tracker import record_hit
                hit_word = ""
                for intent, kws in INTENT_KEYWORDS.items():
                    for kw in kws:
                        if kw and kw in text:
                            hit_word = kw
                            break
                    if hit_word:
                        break
                if hit_word:
                    domains_now = [d for d, kws in DOMAIN_KEYWORDS.items() if _count_hits(text, kws) > 0] or ["通用"]
                    record_hit(hit_word, best_intent, domains_now, query)
            except Exception:
                pass  # 采样失败不影响路由（防御性降级）

        # V8.6 M0.9 P2-ctx · 实体缺失观测：query 含「工具编号式引用（[A-Z]\d{2}）」但不在实体索引
        # → record_entity_miss（同引用 ≥3 次触发实体库补录调研，闭环 method 实体"缺三段"离群）
        try:
            from hit_tracker import record_entity_miss
            _ent_names = {e.get("name", "") for e in load_entities()} | \
                         {a for e in load_entities() for a in e.get("aliases", [])}
            for _code in re.findall(r"[A-Z]\d{2}", query):
                if _code not in _ent_names:
                    record_entity_miss(_code)
        except Exception:
            pass  # 实体缺失观测失败不影响路由（防御性降级）

    # ② 置信度（V8.4 配置驱动 · router.yaml thresholds · 缺省等价内置默认）
    th = load_thresholds()
    if best_score >= th["score_high"]:
        confidence = min(th["high_score_base"] + th["high_score_step"] * (best_score - th["score_high"]),
                         th["high_score_cap"])
    elif best_score >= th["score_low"]:
        confidence = th["low_score_base"] + th["low_score_step"] * best_score
    else:
        confidence = th["fallback"]

    # ③ 领域次路由（归一化词库）
    domains = []
    for domain, kws in DOMAIN_KEYWORDS.items():
        if _count_hits(text, kws) > 0:
            domains.append(domain)
    if domain_hint:
        for domain in DOMAIN_KEYWORDS:
            if domain_hint.lower() in domain.lower():
                if domain not in domains:
                    domains.append(domain)
    if not domains:
        domains = ["通用"]

    # ②b 置信度门槛动态自适应（MDS · L2+M3）：矩阵(default/intent/domain/crisis) ∪ F13 耦合
    #      置于 domains 确定后（依赖 domain_overrides / crisis_overrides）
    floor = _effective_floor(best_intent, domains, mds, th)

    # ④ 形态映射
    form = FORM_MAP[best_intent]

    # ⑤ 缺口联动
    gap = domains == ["通用"] or best_intent == "⑤知识沉淀"

    # ⑥ 实体匹配（V8.4 P1：标准/大师等实体命中 → 附加信号 + 领域增强）
    entities = match_entities(text)
    # V8.6 M0.9 P2-ctx：方法实体（type=method · intent=""）作跨意图上下文锚点
    # —— 仅做领域增强（上面循环）+ 观测输出，绝不覆盖意图（意图由信号词+语境驱动，见 §14.8）
    method_anchors = [e.get("name", "") for e in entities if e.get("type") == "method"]
    if entities:
        for e in entities:
            ed = e.get("domain")
            if ed and ed != "通用" and ed not in domains:
                domains.append(ed)
        if domains:
            gap = gap and len(entities) == 0  # 实体命中视为已覆盖，缓解缺口误判

    # V8.6 P5 · R12 蓝图落地：route 适配器（链 A 意图面采样 · 出口归一化接入）
    # 语义协调：record_hit 采样词级分布（usage_stats.json · 供⑰-R3 校准器）；
    #           record_usage 采样对象域聚合（usage_global.json · 供热度归一化）。
    #           前者计「词→意图/领域分布」，后者计「对象域使用事实」，语义互斥非双计。
    # 双计治理：域级互斥——intent/domain/form 只在本次适配器计（record_hit 只计 word 域分布），
    #           无跨域重复计数路径（工具调用由 tools wrapper/网关计，与本适配器互斥）。
    if os.environ.get("QCM_NO_REPORT") != "1":
        try:
            from usage_global import record_usage
            record_usage("intent", best_intent)
            for d in domains:
                record_usage("domain", d)
            record_usage("form", form)
            if hit_word:
                record_usage("word", hit_word)
        except Exception:
            pass  # 出口采样失败不影响路由（防御性降级）

    # ②c 澄清闭环（M2 · 消费 need_clarify 悬空信号）：生成引导 + 反馈采样
    need_clarify = confidence < floor
    clarify_prompt = ""
    if need_clarify:
        clarify_prompt = _build_clarify_prompt(best_intent, domains, mds)
        if os.environ.get("QCM_NO_REPORT") != "1":
            try:
                from usage_global import record_usage
                record_usage("clarify", "%s|%s" % (best_intent, domains[0] if domains else "通用"))
            except Exception:
                pass  # 反馈采样失败不影响路由（防御性降级）

    # ⑦ 归零事件复用建议（B1 · S1 建议层 · 仅建议、绝不自动套用治理闭环）
    # 触发条件：zero_event_hint.enabled 且 best_intent ∈ trigger_intents
    # 防御降级：任何异常静默跳过，绝不影响主路由返回结构（建议缺失时为空列表）
    reuse_suggest = []
    try:
        ze = load_zero_event_hint()
        if ze.get("enabled") and best_intent in (ze.get("trigger_intents") or []):
            from zero_event import suggest_reuse
            reuse_suggest = suggest_reuse(text, min_sim=float(ze.get("min_sim", 0.5)))
    except Exception:
        reuse_suggest = []  # 复用建议失败不影响主路由（防御性降级）

    return {
        "intent": best_intent,
        "domain": domains[:2],
        "confidence": round(confidence, 2),
        "form": form,
        "gap": gap,
        "need_clarify": need_clarify,
        "clarify_prompt": clarify_prompt,
        "keyword_level": keyword_level,
        "need_research": need_research,
        "entities": [{"name": e["name"], "type": e["type"], "intent": e.get("intent")} for e in entities],
        "method_anchors": method_anchors,
        "capacity_warn": _load_state["capacity_warn"],
        "load_plan": _build_load_plan(best_intent, form, []),
        "echo": f"已识别【{best_intent}】→ 形态【{form}】，如有偏差请纠正",  # A-① 路由回显（A+B V8.7）
        "reuse_suggest": reuse_suggest,  # B1 · 归零事件复用建议（S1 建议层 · 仅建议）
    }


def suggest_research(query: str, hit_count: int = 3) -> Dict:
    """深层实时调研建议接口（P2-3 · 置信度门控）

    调用方统计未命中词频次，达到触发门槛后调用：
      - 输出调研建议词（query 整体 + 候选）
      - 门控：调研结果置信度 ≥70 才入库（§8.4）
      - 未达标词仅本次路由有效（不入库）
    """
    return {
        "suggest": query,
        "trigger": f"同词未命中 {hit_count} 次（门槛 ≥3）",
        "gate": "调研结果置信度 ≥70 才可入 keyword.yaml（§8.4）",
        "level": "deep_realtime",
    }


def _build_load_plan(intent: str, form: str, gaps: list = None) -> list:
    """R18 P5 load_plan 分发：意图/形态 → 懒加载语料对象计划

    依据 guardian.yaml loaders 段元数据（object/level/group/freq）——
    归一化定义层驱动，route 消费层执行（定义↔执行双向一致）。
    语义协调：load_plan 是**加载指引**（告诉消费方预取哪些语料对象），
    不是使用采样（record_usage 管热度事实），两者域互斥无交叉。

    返回 [{object, level, group, freq, reason}] · 按 freq 降序（high 优先）。
    """
    plan_by_obj = {}
    _reason = ""

    # ① 协议族（action-orders · freq=high）：意图驱动章节精读
    #    按意图映射关键 § 章（LRU 级 · 路由协议 §14 常驻）
    intent_chapter = {
        "①危机处置": ["§3 危机管理协议（动作阶段主）", "§1 行动指令卡 AO-1~AO-4（动作维度主 · 时间维度子）"],
        "②流程优化": ["§2 5 段式输出结构（动作维度主 · 严格分离）"],
        "③评估审计": ["§4 L1-L4 危机触发矩阵", "§5 责任层定义（动作阶段 + 责任主体双轴）"],
        "④知识学习": ["§12 三库新鲜度维护协议"],
        "⑤知识沉淀": ["§9 案例资产化协议（V8.0 新增 · 组织运行资产）"],
        "⑥质量文化": ["§7 L4 组织治理 4 层 × N 维度（预防阶段 · 4 层 × N 维度表）"],
    }
    chap = intent_chapter.get(intent, [])
    plan_by_obj["action-orders"] = {
        "object": "action-orders", "level": "chapter", "group": "协议族", "freq": "high",
        "reason": f"{intent} → 章精读 {'、'.join(chap[:2])}" if chap else f"{intent} → 协议按需",
    }

    # ② 工具族（tools · freq=low）：resolve 类意图懒加载单节
    #    （②③ 流程/评估场景按需触发 · 其余意图低频兜底）
    if intent in ("②流程优化", "③评估审计"):
        plan_by_obj.setdefault("tools", {
            "object": "tools", "level": "kw", "group": "工具族", "freq": "low",
            "reason": f"{intent} → 工具实例关键词定位",
        })

    # ③ 知识族（knowledge-base/masters/cases · freq=low）：案例/知识学习类触发
    # #60：扩展 ③评估审计（审核场景）/②流程优化（水平展开场景）预取 cases 案例库，
    #      使已登记归零事件可作为案例输入被消费（S1 建议层 · 仅加载指引不写回）
    if intent in ("④知识学习", "⑤知识沉淀", "①危机处置", "③评估审计", "②流程优化"):
        for obj, note in (("cases", "双归零/行业案例"), ("knowledge-base", "案例集/外部素材")):
            plan_by_obj.setdefault(obj, {
                "object": obj, "level": "chapter", "group": "知识族", "freq": "low",
                "reason": f"{intent} → {note}按章",
            })
    if intent in ("④知识学习", "③评估审计"):
        plan_by_obj.setdefault("masters", {
            "object": "masters", "level": "chapter", "group": "知识族", "freq": "low",
            "reason": f"{intent} → 大师心智模型按章",
        })

    # ④ 形态增强：assessment_report 形态追加（评估审计场景偏审计口径）
    if form == "assessment_report" and intent == "③评估审计":
        plan_by_obj.setdefault("knowledge-base", {
            "object": "knowledge-base", "level": "chapter", "group": "知识族", "freq": "low",
            "reason": "assessment_report 形态 → 知识库审计口径",
        })

    # freq 权重排序（high=3 / mid=2 / low=1）
    _fw = {"high": 3, "mid": 2, "low": 1}
    plan = sorted(plan_by_obj.values(), key=lambda p: _fw.get(p["freq"], 0), reverse=True)
    return plan


def load_plan(intent: str, form: str = "", gaps: list = None) -> list:
    """公开接口：按意图/形态返回懒加载计划（供编排器预取 · 同 route 内实现）"""
    return _build_load_plan(intent, form, gaps)


def keyword_head_index() -> dict:
    """P0 词头索引快照（供 SKILL 上下文裁剪指引 / 懒加载观测）

    - 意图×词头数 / 领域×词头数（词头 = 词条数 · 压缩表征）
    - 全量 1620 行 keyword.yaml 的压缩摘要（-93% 上下文）
    - 不改变 route 语义（仅观测/指引 · load_keywords 缓存已热）
    """
    load_keywords()
    return {
        "intent_heads": {i: len(k) for i, k in INTENT_KEYWORDS.items()},
        "domain_heads": {d: len(k) for d, k in DOMAIN_KEYWORDS.items()},
        "total_words": sum(len(v) for v in INTENT_KEYWORDS.values()),
        "total_domains": sum(len(v) for v in DOMAIN_KEYWORDS.values()),
        "level": _load_state.get("level", "L0"),
        "note": "词头索引 = 词数压缩表征 · 供上下文裁剪指引（-93% 路由载入）",
    }


if __name__ == "__main__":
    demos = [
        "CNC 镗孔椭圆 0.002mm 怎么办",
        "如何提升注塑良率",
        "供应商质量体系评估",
        "FMEA 七步法是什么",
        "QCM 接入新能源行业",
        "IPQC 如何控制裂纹",
        "花店情人节玫瑰大量枯萎客诉怎么办",
        "门店鲜花早衰但肉眼看不出来",
        "玻璃基板微裂纹",
        "鲜花冷柜停摆客诉",
    ]
    print("词库等级:", load_keywords(), "容量警告:", _load_state["capacity_warn"] or "无")
    for d in demos:
        r = route(d)
        print(f"{d[:22]:<24} → {r['intent']} {r['domain']} conf={r['confidence']} "
              f"research={r['need_research']}")
