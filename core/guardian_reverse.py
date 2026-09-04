#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S4/S5.5 反向守卫族 ⑰-R1~R6（落库词源 → 源登记 / 声明意图 / 实际使用事实 双向锁定）

背景：正向前置守卫（g001~g016）校验"登记是否齐备/注入是否合规"，但缺少从
      落库词条回看源登记、从使用事实回看声明的反向约束。本模块实现 g017 族的
      反向守卫，把"静态声明"与"运行事实"双向锁定：

  R1 孤儿反向     source: industry 词条的 origin 指向的 pack 必须仍登记于 index.yaml
  R2 词面校准     声明意图 vs 同根/上下位词族主导意图（confirmed_pairs 豁免人工分流）
  R3 使用事实校准 声明意图 vs usage_stats 实际主导意图（S2 采样 · 一致率<60% 且
                  total>=min_total 才建议校准 · 防小样本噪音）
  R4 热度一致性   usage 高命中非 hot → hot 化建议；90d 零活动 stable → 归档建议；
                  hot 名不副实 → 降级提示（无数据 → NO_DATA 说明不告警）
  R5 注入链双向   词条 pack_ref ↔ pack 登记双向引用（S5.5 按 source_links 映射遍历多词源）
  R6 词源自适应    keyword.yaml 出现未登记 source 值 → 提示登记映射（动态自适应 · 防硬编码忽略）

设计：
  - 纯函数可注入数据：每个 check_Rx(data...) 不读文件，由 check_all() 统一加载
    （便于单测注入构造样本 · 数据源缺省时安全降级）
  - 输出带前缀 "[反向R1] " ~ "[反向R5] "，guardian.yaml g017_* 的 alias 与之对齐，
    经 core/guardian.py classify 归入对应守卫
  - 全部为 warn 级别（不使 CI 失败 · 与 g017 severity: warn 一致），但逐条可审计

用法：
  python3 core/guardian_reverse.py --check        # 全量 R1-R5（guardian 引擎集成后走 --phase decision）
  python3 core/guardian_reverse.py --guard r3     # 单守卫
  python3 core/guardian_reverse.py --json         # JSON 输出（供上层消费）
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "references" / "config"
DATA = ROOT / "references"

# ── 阈值（与 guardian.yaml g017 触发对齐 · R4 暖用配置） ──
# M1.3 自适应增强：阈值支持 env 覆盖（QCM_Rn_*），R3_MIN_TOTAL 按语料规模自适应
# （usage 数据量越大，最小样本门槛越高——防小样本噪音与大数据噪声并存）
import os as _os
R3_MIN_TOTAL = int(_os.environ.get("QCM_R3_MIN_TOTAL", 3))
R3_DOMINANT_PCT = int(_os.environ.get("QCM_R3_DOMINANT_PCT", 60))
R4_HOT_HITS = int(_os.environ.get("QCM_R4_HOT_HITS", 10))
R4_STALE_DAYS = int(_os.environ.get("QCM_R4_STALE_DAYS", 90))
R4_HOT_MIN = int(_os.environ.get("QCM_R4_HOT_MIN", 5))


# ── 数据加载（全部缺省安全降级） ──

def load_keywords(path: Path = None) -> list:
    """keyword.yaml → 词条列表（缺省 []）"""
    path = path or (CFG / "keyword.yaml")
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("keywords") or [])
    except Exception:
        return []


def load_packs(path: Path = None) -> list:
    """industry/index.yaml → industry_packs 列表（缺省 []）"""
    path = path or (DATA / "industry" / "index.yaml")
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("industry_packs") or [])
    except Exception:
        return []


def load_source_links(path: Path = None) -> list:
    """source_links.yaml → source_links 映射列表（缺省 [] · S5.5 R5 数据源映射归一化）"""
    path = path or (CFG / "source_links.yaml")
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("source_links") or [])
    except Exception:
        return []


def load_packs_by_link(link: dict) -> list:
    """按 source_link 映射加载登记中心 pack 列表（动态自适应 · S5.5）
    读取 index_path 指向的 YAML 的 index_key 列表；缺省降级 []"""
    if not isinstance(link, dict):
        return []
    try:
        import yaml
        idx = ROOT / str(link.get("index_path", ""))
        if not idx.exists():
            return []
        data = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
        return list(data.get(link.get("index_key", "industry_packs")) or [])
    except Exception:
        return []


def load_usage(path: Path = None) -> dict:
    """usage_stats.json → {word: stats}（缺省 {}）"""
    path = path or (DATA / "usage_stats.json")
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_hits(path: Path = None) -> dict:
    """hit_stats.json → {word: count}（缺省 {}）"""
    path = path or (DATA / "hit_stats.json")
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_entities(path: Path = None) -> list:
    """entities.yaml → 实体列表（缺省 []）"""
    path = path or (CFG / "entities.yaml")
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("entities") or [])
    except Exception:
        return {}


def load_semantic(path: Path = None) -> dict:
    """semantic.yaml → 语义配置（confirmed_pairs/complementary_pairs/params）"""
    path = path or (CFG / "semantic.yaml")
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _days_since(iso: str) -> int:
    """ISO 时间串距今天数（缺省/异常 → None）"""
    if not iso:
        return None
    try:
        s = iso[:19].replace("T", " ")
        d = datetime.strptime(s, "%Y-%m-%d %H:%M") if len(s) > 10 else datetime.strptime(s, "%Y-%m-%d")
        days = (datetime.now().date() - d.date()).days
        return max(days, 0)
    except Exception:
        return None


# ── R1 孤儿反向 ──

def check_r1(keywords: list = None, packs: list = None) -> tuple:
    """R1：industry 词条的 origin 必须仍指向已登记的 pack 且词在 pack keywords 中"""
    keywords = keywords if keywords is not None else load_keywords()
    packs = packs if packs is not None else load_packs()
    pack_ids = {p.get("id") for p in packs if isinstance(p, dict)}
    pack_words = {p.get("id"): set(p.get("keywords") or []) for p in packs if isinstance(p, dict)}
    issues, warnings = [], []
    for kw in keywords:
        if not isinstance(kw, dict) or kw.get("source") != "industry":
            continue
        w, origin = kw.get("word"), kw.get("origin")
        if not origin:
            warnings.append(f"[反向R1] {w}: source=industry 但缺少 origin（应 pack_id:word）")
            continue
        if ":" not in origin:
            warnings.append(f"[反向R1] {w}: origin 格式非法（应 pack_id:word）: {origin}")
            continue
        pid, pword = origin.split(":", 1)
        if pid not in pack_ids:
            warnings.append(f"[反向R1] {w}: origin 指向的 pack 未登记于 index.yaml（孤儿反向）: {pid}")
        elif pid in pack_words and pword not in pack_words[pid]:
            warnings.append(f"[反向R1] {w}: origin 词 {pword} 不在 {pid} 登记的 keywords 中")
    return issues, warnings


# ── R2 词面校准（同根/上下位族主导意图） ──

def _same_family(a: str, b: str, min_len: int = 2) -> bool:
    """中文词同根判定：一者包含另一者（短者≥min_len 字） 或 共享 ≥min_len 字公共子串"""
    if len(a) < min_len or len(b) < min_len:
        return False
    if a in b or b in a:
        return True
    short = a if len(a) <= len(b) else b
    for i in range(len(short) - min_len + 1):
        sub = short[i:i + min_len]
        if sub in a and sub in b:
            return True
    return False


def _exempt_pairs(semantic: dict, w: str, o: str) -> bool:
    """人工确认分流对（confirmed_pairs/complementary_pairs）→ 豁免（词序无关）"""
    for pairs_key in ("confirmed_pairs", "complementary_pairs"):
        for pair in (semantic.get(pairs_key) or []):
            if isinstance(pair, list) and len(pair) >= 2:
                if {pair[0], pair[1]} == {w, o}:
                    return True
    return False


def check_r2(keywords: list = None, semantic: dict = None) -> tuple:
    """R2：词条声明意图 vs 同根词族主导意图（豁免人工确认分流对）"""
    keywords = keywords if keywords is not None else load_keywords()
    semantic = semantic if semantic is not None else load_semantic()
    issues, warnings = [], []
    pmin = int(semantic.get("params", {}).get("min_word_len", 3)) if isinstance(semantic.get("params"), dict) else 3
    for kw in keywords:
        if not isinstance(kw, dict):
            continue
        w, declared = kw.get("word"), kw.get("intent")
        if not w or not declared or not any("\u4e00" <= ch <= "\u9fff" for ch in w):
            continue  # 仅中文词做同根族分析（英文/混合词跳过）
        fam = {}
        fam_words = {}
        for o in keywords:
            if not isinstance(o, dict) or o.get("word") == w:
                continue
            ow = o.get("word")
            if not ow or not any("\u4e00" <= ch <= "\u9fff" for ch in ow):
                continue
            if _same_family(w, ow, max(pmin, 2)):
                it = o.get("intent")
                fam[it] = fam.get(it, 0) + 1
                fam_words.setdefault(it, []).append(ow)
        # 主导意图：票数最高（≥2 票才具统计意义 · 防单样本噪音）
        if len(fam) >= 2:
            dominant, votes = max(fam.items(), key=lambda kv: (kv[1], kv[0]))
            if votes >= 2 and dominant != declared:
                if not any(_exempt_pairs(semantic, w, ow) for ow in fam_words.get(dominant, [])):
                    warnings.append(
                        f"[反向R2] {w}: 声明 {declared}，同根族主导 {dominant}（{votes} 票 · "
                        f"同根词 {', '.join(fam_words.get(dominant, [])[:3])}）→ 建议校准或用例说明"
                    )
        elif len(fam) == 1 and fam[list(fam.keys())[0]] >= 2:
            # 族内全一致但 ≠ 声明：词根族语义单调，声明意图脱群
            only_intent, only_votes = list(fam.items())[0]
            if only_intent != declared and not any(_exempt_pairs(semantic, w, ow) for ow in fam_words.get(only_intent, [])):
                warnings.append(
                    f"[反向R2] {w}: 声明 {declared}，同根族全部 {only_intent}（{only_votes} 票 · "
                    f"同根词 {', '.join(fam_words.get(only_intent, [])[:3])}）→ 声明脱群，建议校准"
                )
    return issues, warnings


# ── R3 使用事实校准 ──

def check_r3(keywords: list = None, usage: dict = None) -> tuple:
    """R3：声明意图 vs usage_stats 实际主导意图（S2 采样 · 防小样本）

    M1.3 自适应增强：min_total 门槛按 usage 数据规模轻量缩放——
      词条总数 ≥ 200 → 门槛提升为 5；≥ 500 → 7（数据量越大，样本噪音容忍越低）。
      可通过 QCM_R3_MIN_TOTAL 显式覆盖；自适应仅放大默认值，不缩小（保守方向）。
    """
    keywords = keywords if keywords is not None else load_keywords()
    usage = usage if usage is not None else load_usage()
    issues, warnings = [], []
    # 自适应最小样本门槛（按 usage 词条规模缩放）
    n_usage = len(usage)
    if n_usage >= 500:
        min_total = max(R3_MIN_TOTAL, 7)
    elif n_usage >= 200:
        min_total = max(R3_MIN_TOTAL, 5)
    else:
        min_total = R3_MIN_TOTAL
    declared = {k.get("word"): k.get("intent") for k in keywords if isinstance(k, dict)}
    for w, st in usage.items():
        if not isinstance(st, dict):
            continue
        dist = st.get("intent_dist") or {}
        if not dist:
            continue
        dom_intent, dom_count = max(dist.items(), key=lambda kv: kv[1])
        t_total = st.get("total") or sum(dist.values())
        if t_total < min_total:
            continue  # 样本不足不触发（避免 1-2 次随机命中噪音）
        pct = round(dom_count * 100.0 / t_total, 1) if t_total else 0.0
        declared_intent = declared.get(w)
        if declared_intent and dom_intent != declared_intent and pct >= R3_DOMINANT_PCT:
            warnings.append(
                f"[反向R3] {w}: 声明 {declared_intent}，实际使用主导 {dom_intent}（{dom_count}/{t_total} · "
                f"{pct}% ≥ {R3_DOMINANT_PCT}%）→ 按使用场景事实校准落库目标"
            )
    return issues, warnings


# ── R4 热度一致性 ──

def check_r4(keywords: list = None, usage: dict = None, hits: dict = None) -> tuple:
    """R4：热度状态 vs 使用事实（高命中应 hot / 长期零活动应归档 / hot 名不副实提示）"""
    keywords = keywords if keywords is not None else load_keywords()
    usage = usage if usage is not None else load_usage()
    hits = hits if hits is not None else load_hits()
    issues, warnings = [], []
    seen = 0
    for kw in keywords:
        if not isinstance(kw, dict):
            continue
        w, status = kw.get("word"), kw.get("status")
        st = usage.get(w) or {}
        total = int(st.get("total") or 0)
        hit = 0
        if isinstance(hits, dict) and w in hits:
            hv = hits[w]
            hit = int(hv.get("count") or 0) if isinstance(hv, dict) else int(hv or 0)
        if total or hit:
            seen += 1
        # S7b 热词豁免：status: hot 是人工/流程主动提升（不占容量 · 需稳定期）
        #   → hot 词不做热度动态判定（名不副实降级仅提示 · 归档永不触发）
        if status == "hot":
            if (total + hit) < R4_HOT_MIN:
                warnings.append(
                    f"[反向R4] {w}: 状态 hot 但使用 {total + hit} 次 < {R4_HOT_MIN} → 名不副实提示（热词豁免 · 不自动降级）"
                )
            continue  # hot 豁免后续判定
        if status != "hot" and (total + hit) >= R4_HOT_HITS:
            warnings.append(
                f"[反向R4] {w}: 使用 {total + hit} 次 ≥ {R4_HOT_HITS} 但状态 {status} → 建议 hot 化"
            )
        if status in ("stable", "active") and st:
            days = _days_since(st.get("last_seen"))
            if days is not None and days >= R4_STALE_DAYS:
                warnings.append(
                    f"[反向R4] {w}: 状态 {status} 但 {R4_STALE_DAYS}d 零活动（last_seen {st.get('last_seen')}）→ 建议归档"
                )
    if seen == 0:
        warnings.append(f"[反向R4] 无使用数据（usage_stats/hit_stats 全空）→ 本轮 NO_DATA，跳过热度判定")
    return issues, warnings


# ── R5 注入链双向引用（S5.5 · 按 source_links 映射遍历多词源） ──

def _packs_for_source(link: dict, packs_injected=None):
    """取某词源的 pack 列表：注入优先 · 否则按映射加载 · 缺省 []"""
    if packs_injected is not None:
        return packs_injected
    return load_packs_by_link(link)


def check_r5(keywords: list = None, packs: list = None, links: list = None) -> tuple:
    """R5：词条 pack_ref ↔ pack 登记 双向引用（按 source_links 映射遍历多词源）

    S5.5 归一化：不再硬编码 industry —— 遍历 source_links.yaml 每个映射，
    动态读取各词源登记中心（index_path/index_key），全生命周期多词源可扩展。

    Args:
        keywords: 词条列表（缺省读 keyword.yaml）
        packs: 注入的 pack 列表（向后兼容：单词源测试注入 · 优先于 links 加载）
        links: source_links 映射列表（缺省读 source_links.yaml）
    """
    keywords = keywords if keywords is not None else load_keywords()
    links = links if links is not None else load_source_links()
    issues, warnings = [], []

    # 反向通用：pack 登记的 keywords 每个词必须已在 keyword.yaml 注入且 pack_ref == pack_id
    def _check_reverse(pid, pack_kws):
        for w in pack_kws:
            kw = next((k for k in keywords if isinstance(k, dict) and k.get("word") == w), None)
            if not kw:
                warnings.append(f"[反向R5] {pid}: 登记的 keyword({w}) 未注入 keyword.yaml（反向断链）")
            elif kw.get("pack_ref") is not None and kw.get("pack_ref") != pid:
                warnings.append(
                    f"[反向R5] {pid}: keyword({w}) 的 pack_ref={kw.get('pack_ref')} 与本包不一致（反向引用错位）"
                )

    # 正向通用：某词源的词条必须带 pack_ref 且指向该词源已登记 pack
    def _check_forward(src, kw_list, src_pack_ids):
        for kw in kw_list:
            if not isinstance(kw, dict) or kw.get("source") != src:
                continue
            w, ref = kw.get("word"), kw.get("pack_ref")
            origin_pid = None
            if kw.get("origin") and ":" in kw.get("origin", ""):
                origin_pid = kw["origin"].split(":", 1)[0]
            if not ref:
                warnings.append(f"[反向R5] {w}: source={src} 缺 pack_ref（origin 指向 {origin_pid}）→ 注入链未闭环")
            elif ref not in src_pack_ids:
                warnings.append(f"[反向R5] {w}: pack_ref={ref} 未登记于 {src} 登记中心（正向断链）")

    if not links:
        # 向后兼容：无映射配置时退化为旧 industry 逻辑（注入 packs 或默认加载）
        packs = packs if packs is not None else load_packs()
        pack_ids = {p.get("id") for p in packs if isinstance(p, dict)}
        _check_forward("industry", keywords, pack_ids)
        for p in packs:
            if isinstance(p, dict):
                _check_reverse(p.get("id"), p.get("keywords") or [])
        return issues, warnings

    for link in links:
        if not isinstance(link, dict):
            continue
        src = link.get("source")
        if not src:
            continue
        # 单一映射注入时仅处理该词源（测试隔离）；全量时遍历全部映射
        if packs is not None:
            # 注入模式下：仅对注入的 packs 所属词源做正向校验
            src_pack_ids = {p.get("id") for p in packs if isinstance(p, dict)}
            _check_forward(src, keywords, src_pack_ids)
            for p in packs:
                if isinstance(p, dict):
                    _check_reverse(p.get("id"), p.get("keywords") or [])
            return issues, warnings
        # 全量模式：按映射加载 packs
        src_packs = load_packs_by_link(link)
        src_pack_ids = {p.get("id") for p in src_packs if isinstance(p, dict)}
        _check_forward(src, keywords, src_pack_ids)
        for p in src_packs:
            if isinstance(p, dict):
                _check_reverse(p.get("id"), p.get("keywords") or [])
    return issues, warnings


# ── R6 词源自适应探测（S5.5 · 动态自适应 · 未登记词源提示） ──

def check_r6(keywords: list = None, links: list = None) -> tuple:
    """R6：keyword.yaml 出现的 source 值必须在 source_links 有映射
    新词源未登记 → 提示（动态自适应 · 防硬编码静默忽略）"""
    keywords = keywords if keywords is not None else load_keywords()
    links = links if links is not None else load_source_links()
    issues, warnings = [], []
    registered = {}
    for link in links:
        if isinstance(link, dict) and link.get("source"):
            registered[link["source"]] = link.get("desc", "")
    # source 字段的存在性：缺省 source 的词条（base 词）不算新词源
    used_sources = set()
    for kw in keywords:
        if isinstance(kw, dict) and kw.get("source"):
            used_sources.add(kw["source"])
    for src in sorted(used_sources):
        if src not in registered:
            warnings.append(
                f"[反向R6] 未登记词源: source={src}（keyword.yaml {used_sources} 中出现但 source_links 无映射）"
                f"→ 请在 source_links.yaml 登记（source/index_path/index_key）"
            )
        else:
            # 已登记但缺 index 文件 → warn（S7 强化 · 配置断链审计 · 生产零误报）
            link = next((l for l in links if isinstance(l, dict) and l.get("source") == src), None)
            if link:
                idx = ROOT / str(link.get("index_path", ""))
                if not idx.exists():
                    warnings.append(
                        f"[反向R6] 词源 {src}: 已登记映射但 index 文件缺失（{link.get('index_path')}）"
                        f"→ R1/R5 将无法校验该词源 · 请创建 index_path 或移除映射"
                    )
    return issues, warnings


# ── R7 静态绑定 vs 方法实体碰撞（M0.9 P3-ctx/P2-norm · 顶层宽护栏） ──

def check_r7(keywords: list = None, entities: list = None) -> tuple:
    """R7：keyword.yaml 静态意图绑定 不得与 method 实体（intent='' 跨意图锚点）碰撞

    依据 action-orders §14.8「挂领域不挂意图」：method 实体（来自 tools.md · type=method
    · intent=''）是跨意图上下文锚点，其意图必须由信号词（危机/讲解/优化/评估）驱动，
    禁止在 keyword.yaml 用静态 intent 绑定强制落某意图（违背「顶层宽·应用层紧」）。
    碰撞（词面或别名命中 method 实体且 keyword 带非空 intent）→ warn（可被静态白名单豁免）。

    白名单 static_bindings_allowlist：仅收录「非方法实体本义」的碰撞——
      ① 通用优化动词（改善/kaizen）经别名巧合命中 D01，但作为中文通用动词需保留 intent ② 供关键词打分；
      ② 与既有 standard 实体意图一致（vda→③ 与 VDA 6.3/6.5 standard 意图一致）。
    白名单项须在 keyword.yaml 显式登记并附理由，逐条可审计。
    """
    keywords = keywords if keywords is not None else load_keywords()
    entities = entities if entities is not None else load_entities()
    issues, warnings = [], []

    # 方法实体（intent=''）词面集合
    meth_surfaces = {}  # surface(lower) -> entity_name
    for e in entities:
        if not isinstance(e, dict):
            continue
        if e.get("type") != "method":
            continue
        if e.get("intent") not in ("", None):
            continue
        for s in [e.get("name", "")] + list(e.get("aliases", []) or []):
            if s:
                meth_surfaces[str(s).lower()] = e.get("name", "")

    # 静态白名单（keyword.yaml 顶层 static_bindings_allowlist: [词...]）
    allow = set()
    try:
        import yaml as _yaml
        _raw = _yaml.safe_load((CFG / "keyword.yaml").read_text(encoding="utf-8")) or {}
        allow = {str(a).lower() for a in (_raw.get("static_bindings_allowlist") or [])}
    except Exception:
        pass

    for k in keywords:
        if not isinstance(k, dict):
            continue
        w, declared = k.get("word"), k.get("intent")
        if not w or not declared:
            continue
        if w.lower() in allow:
            continue  # 显式白名单豁免（附理由登记）
        surfaces = {w.lower()} | {str(a).lower() for a in (k.get("aliases") or [])}
        hit_entity = next((meth_surfaces[s] for s in surfaces if s in meth_surfaces), None)
        if hit_entity:
            warnings.append(
                f"[反向R7] {w}: 静态意图 {declared} 与 method 实体 {hit_entity}（intent='' 跨意图锚点）"
                f"碰撞 → 应删除静态意图绑定，改由信号词驱动（§14.8 · 顶层宽）；"
                f"若需保留须登记 static_bindings_allowlist 并附理由"
            )
    return issues, warnings


# ── R8 实体分层 + 使用事实校准（M1.0 · g017 决策族 · 闭环 method 实体「缺三段」离群） ──
# 背景：method 实体相对语料/关键词是"缺三段"离群者（无 auto-checkin/生命周期/使用校准/实体级缺失观测）。
# M0.9 P4-norm 已补齐"实体缺失观测"（entity_miss）；M1.0 ② 补齐"实体正向命中"（entity_hit），
# 本守卫消费 entity_hit_stats + entity_miss_stats，对实体分层字段做两类校验：
#   ① 分层 schema 一致性：每个实体须含 status/level/lifecycle/tier 且枚举合法（① 字段建设门禁）
#   ② 使用事实校准一致性：声明 tier/status 须与使用事实（命中热度/失活时长）自洽
# 全部 warn 级别（report-only，与 R1-R7 一致），可审计、不使 CI 失败。

# 分层枚举（与 extract_entities.LAYER_ENUMS 对齐 · 反向守卫依赖轻量故内联，避免跨模块路径耦合）
R8_LAYER_ENUMS = {
    "status": {"active", "deprecated", "archived"},
    "level": {"core", "derived"},
    "lifecycle": {"draft", "evolving", "stable", "mature"},
    "tier": {"hot", "warm", "cold"},
}
R8_ENTITY_HOT_HITS = int(_os.environ.get("QCM_R8_HOT_HITS", 10))   # 累计命中 ≥ 此值 → 建议 tier=hot
R8_ENTITY_HOT_MIN = int(_os.environ.get("QCM_R8_HOT_MIN", 5))     # 声明 tier=hot 但累计 < 此值 → 名不副实
R8_ENTITY_STALE_DAYS = int(_os.environ.get("QCM_R8_STALE_DAYS", 90)) # status=active 但末次命中 ≥ 此天数 → 建议复核/降级


def load_entity_hits(path=None) -> dict:
    """entity_hit_stats.json → {name: {count, first_seen, last_seen}}（缺省 {}）

    入参可为 Path 或 str；str 自动 Path() 化，避免误传字符串时静默返回 {}。
    """
    path = Path(path) if path else (DATA / "entity_hit_stats.json")
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def check_r8(entities: list = None, entity_hits: dict = None,
             entity_misses: dict = None) -> tuple:
    """R8：实体分层 schema + 使用事实校准一致性

    Args:
        entities:     实体列表（load_entities）
        entity_hits:  {name: {count, first_seen, last_seen}}（load_entity_hits）
        entity_misses: {token: {count, ...}}（load_entity_miss · 预留）
    Returns:
        (issues, warnings) — 带 [反向R8] 前缀
    """
    try:
        from datetime import datetime as _dt
        now = _dt.now()
    except Exception:
        now = None
    ents = entities if entities is not None else load_entities()
    hits = entity_hits if entity_hits is not None else load_entity_hits()
    issues, warnings = [], []
    for e in ents:
        if not isinstance(e, dict):
            continue
        name = e.get("name", "<unnamed>")
        # ① 分层 schema 一致性
        for k, allowed in R8_LAYER_ENUMS.items():
            if e.get(k) not in allowed:
                warnings.append(
                    f"[反向R8] {name}: 分层字段 {k}={e.get(k)!r} 非法（应 ∈ {sorted(allowed)}）"
                    f"→ extract_entities.py 重新生成补全（M1.0 ①）"
                )
        # ② 使用事实校准一致性（仅当存在命中观测数据；无数据 → 不告警，同 R4 NO_DATA）
        h = hits.get(name)
        if not h:
            continue
        total = h.get("count", 0)
        tier = e.get("tier")
        status = e.get("status")
        # tier 校准：声明 warm/cold 但高频命中 → 建议 hot
        if tier in ("warm", "cold") and total >= R8_ENTITY_HOT_HITS:
            warnings.append(
                f"[反向R8] {name}: 声明 tier={tier} 但累计命中 {total} 次（≥{R8_ENTITY_HOT_HITS}）"
                f"→ 建议 tier=hot（使用事实校准）"
            )
        # tier 名不副实：声明 hot 但命中极低
        if tier == "hot" and total < R8_ENTITY_HOT_MIN:
            warnings.append(
                f"[反向R8] {name}: 声明 tier=hot 但累计命中仅 {total} 次（<{R8_ENTITY_HOT_MIN}）"
                f"→ 名不副实，建议降级 warm"
            )
        # status 校准：active 但长期未命中 → 建议复核
        if status == "active" and now is not None:
            last = h.get("last_seen")
            try:
                last_dt = _dt.fromisoformat(last) if last else None
                if last_dt and (now - last_dt).days >= R8_ENTITY_STALE_DAYS:
                    warnings.append(
                        f"[反向R8] {name}: status=active 但末次命中 {last[:10]}（≥{R8_ENTITY_STALE_DAYS}d 无活动）"
                        f"→ 建议复核 lifecycle/status（疑似失活）"
                    )
            except Exception:
                pass
    return issues, warnings


# ── 汇总入口 ──

def check_all(keywords: list = None, packs: list = None, usage: dict = None,
              hits: dict = None, semantic: dict = None, links: list = None,
              entities: list = None) -> tuple:
    """运行 R1-R8 全部反向守卫（可注入数据便于单测）

    Returns:
        (issues, warnings) — 均为带 [反向R#] 前缀的消息列表
    """
    issues, warnings = [], []
    for fn in (check_r1, check_r2, check_r3, check_r4, check_r5, check_r6, check_r7, check_r8):
        try:
            if fn is check_r2:
                i, w = fn(keywords, semantic)
            elif fn is check_r1 or fn is check_r5:
                i, w = fn(keywords, packs, links if fn is check_r5 else None) if fn is check_r5 else fn(keywords, packs)
            elif fn is check_r6:
                i, w = fn(keywords, links)
            elif fn is check_r4:
                i, w = fn(keywords, usage, hits)
            elif fn is check_r7:
                i, w = fn(keywords, entities)
            elif fn is check_r8:
                i, w = fn(entities, hits)
            else:  # check_r3
                i, w = fn(keywords, usage)
            issues += i
            warnings += w
        except Exception as e:  # 单守卫异常不拖垮全量
            warnings.append(f"[反向守卫] {fn.__name__} 异常: {e}")

    # S7b 基线去重：同一词跨守卫重复建议合并（R2/R3 同词 → 只报一次）
    # 规则：词面校准(R2) + 使用事实校准(R3) 对同一词的重复建议 → 保留 R3（事实优先）
    seen_words = {}
    dedup = []
    for w in warnings:
        # 提取词名（[反向R2] X: ... 形式）
        import re as _re
        m = _re.match(r"\[反向R[23]\] ([^:：]+)[:：]", w)
        if not m:
            dedup.append(w)
            continue
        word = m.group(1).strip()
        guard = "r3" if "[反向R3]" in w else "r2"
        if word in seen_words:
            # 已有同词建议 → R3 覆盖 R2（事实优先）；R3 重复 → 保留首次
            if guard == "r2" and seen_words[word] == "r3":
                continue  # R2 与 R3 重复 → 丢弃 R2（R3 更权威）
            if guard == "r3" and seen_words[word] == "r3":
                continue  # R3 自身重复（不应发生 · 防御）
            seen_words[word] = "r3"  # 后到 R3 覆盖 R2
            # 移除已保留的同词 R2（匹配该词的 R2 消息丢弃 · 保留其他）
            dedup = [x for x in dedup if not _re.match(r"\[反向R2\] " + _re.escape(word) + r"[:：]", x)]
            dedup.append(w)
            continue
        seen_words[word] = guard
        dedup.append(w)
    return issues, dedup


def summary(issues, warnings) -> str:
    lines = ["QCM 反向守卫族 ⑰-R1~R8", "=" * 56,
             f"严重问题：{len(issues)} 项", f"警告：{len(warnings)} 项"]
    if warnings:
        lines.append("\n⚠️ 警告：")
        for w in warnings:
            lines.append(f"   {w}")
    if not issues and not warnings:
        lines.append("\n✅ 全部通过")
    return "\n".join(lines) + "\n"


def main():
    if "--json" in sys.argv:
        i, w = check_all()
        print(json.dumps({"issues": i, "warnings": w}, ensure_ascii=False, indent=2))
        return 1 if i else 0
    if "--guard" in sys.argv:
        g = sys.argv[sys.argv.index("--guard") + 1].lower()
        fn_map = {"r1": check_r1, "r2": check_r2, "r3": check_r3,
                  "r4": check_r4, "r5": check_r5, "r6": check_r6, "r7": check_r7,
                  "r8": check_r8}
        fn = fn_map.get(g)
        if not fn:
            print(f"未知守卫 {g}（可选 r1-r8）")
            return 2
        i, w = fn()
        print(summary(i, w))
        return 1 if i else 0
    i, w = check_all()
    print(summary(i, w))
    return 1 if i else 0


if __name__ == "__main__":
    sys.exit(main())