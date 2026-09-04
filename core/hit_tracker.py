#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 词源观测环 · 未命中词统计 + 使用事实采样（V8.4 动态自适应闭环 Step 1 + S2 使用事实采样器）

功能：route() 未命中（need_research）时记录未命中词频次 → 同词 ≥3 次触发调研建议
     （补齐 suggest_research 缺失的"调用方统计" · §11.2/§13 热词发现闭环驱动信号）
     S2（V8.5）：正向命中采样——route() 命中词时记录 (词, 实际意图, 实际领域, 语境词)
     → references/usage_stats.json（词 → 意图/领域分布 + 语境词集）供意图分布校准器（⑰-R3）消费

用法：
  from hit_tracker import record_miss, top_misses, suggest_research, reset, record_hit, usage_stats
  from hit_tracker import record_entity_miss, top_entity_misses, entity_miss_stats, reset_entity_miss
  record_miss("船舶螺旋桨空蚀")     # 未命中词落盘
  record_hit("电芯", "①危机处置", ["C供应链"], "热失控 着火 紧急措施")  # 正向命中采样
  top_misses(threshold=3)          # 达阈值词（待调研）
  suggest_research(word)           # 触发调研建议（置信度门控）
  usage_stats(word=None)           # 使用事实分布（词级或全量）
  reset(word)                      # 入库/确认后重置计数
  record_entity_miss("G01")        # 工具引用未命中实体 → 达阈值触发实体补录调研
  top_entity_misses()              # 达阈值的实体缺失 token（待补录）

设计：
  - 数据：references/hit_stats.json（未命中：词 → {count, first_seen, last_seen}）
         references/usage_stats.json（命中：词 → {intent_dist, domain_dist, context_words, total, first_seen, last_seen}）
  - 提取：query 中 2-4 字中文窗口 + ≥3 字母英文词（与词库匹配后取未命中片段）
  - 容量：单词计数上限 99 · 词典上限 500（防膨胀）；usage_stats 词上限 500
  - 防御：文件读写异常静默降级（观测环失败不影响路由）
"""
import json
import os
import re
import sys
import threading
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
HIT_STATS = ROOT / "references" / "hit_stats.json"
USAGE_STATS = ROOT / "references" / "usage_stats.json"  # S2 使用事实采样
ENTITY_MISS_STATS = ROOT / "references" / "entity_miss_stats.json"  # V8.6 M0.9 P4-norm 实体缺失观测
ENTITY_HIT_STATS = ROOT / "references" / "entity_hit_stats.json"  # M1.0 ② 实体级使用事实（正向命中热度 · 校准输入）

MISS_THRESHOLD = 3      # 同词未命中 ≥3 次 → 触发调研
ENTITY_MISS_THRESHOLD = 3  # 同工具引用未命中 ≥3 次 → 触发实体 auto-add 调研
MAX_WORD_COUNT = 99     # 单词计数上限
MAX_ENTRIES = 500       # 词典上限
MAX_USAGE_ENTRIES = 500 # usage_stats 词上限
MAX_CONTEXT_WORDS = 12  # 语境词集上限（防膨胀）
MAX_ENTITY_MISS_ENTRIES = 500  # 实体缺失观测词典上限
_lock = threading.Lock()


def _load() -> dict:
    try:
        if HIT_STATS.exists():
            return json.loads(HIT_STATS.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        HIT_STATS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def extract_miss_words(query: str, known_words: set = None) -> list:
    """从未命中 query 提取候选词（整句 + 有意义中文短语 + 英文词）

    V8.4 优化：废弃 4 字全滑窗（产生"蚀机理分"类碎词）；
    改为整句候选 + 中文 run 前缀/后缀 6 字段（语义完整可调研）。
    """
    import re
    candidates = set()
    q = query.strip()
    if q:
        candidates.add(q[:40])  # 整句（≤40 字 · 调研输入语义完整）
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", q):
        if len(run) <= 6:
            candidates.add(run)          # 短串整串
        else:
            candidates.add(run[:6])      # 长串前缀 6 字
            candidates.add(run[-6:])     # 长串后缀 6 字
    # 英文词 ≥3 字母
    candidates.update(w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", q))
    # 排除已知词（已命中词库/实体 → 无需调研）
    if known_words:
        candidates = {c for c in candidates if c.lower() not in known_words}
    return sorted(candidates)


def record_miss(query: str, known_words: set = None) -> list:
    """记录未命中词频次（返回本次新增/递增的词）"""
    words = extract_miss_words(query, known_words)
    if not words:
        return []
    with _lock:
        data = _load()
        now = datetime.now().isoformat(timespec="minutes")
        bumped = []
        for w in words[:8]:  # 单次最多 8 词
            e = data.setdefault(w, {"count": 0, "first_seen": now, "last_seen": now})
            e["count"] = min(e["count"] + 1, MAX_WORD_COUNT)
            e["last_seen"] = now
            if e["count"] >= MISS_THRESHOLD:
                bumped.append(w)
        # 容量治理：超限淘汰最旧
        if len(data) > MAX_ENTRIES:
            for k in sorted(data, key=lambda k: data[k].get("last_seen", ""))[:len(data) - MAX_ENTRIES]:
                data.pop(k, None)
        _save(data)
        return bumped


def top_misses(threshold: int = MISS_THRESHOLD) -> list:
    """达阈值未命中词（待调研候选）· V8.4 防御：跳过非 dict 条目（防损坏文件崩溃）"""
    data = _load()
    return sorted(
        [{"word": w, "count": e["count"], "last_seen": e.get("last_seen", "")}
         for w, e in data.items() if isinstance(e, dict) and e.get("count", 0) >= threshold],
        key=lambda x: -x["count"],
    )


def suggest_research(word: str = None, hit_count: int = MISS_THRESHOLD) -> dict:
    """触发调研建议（suggest_research 补齐实现 · 置信度门控 ≥70 才入库）"""
    if word:
        return {
            "suggest": word,
            "trigger": f"同词未命中 ≥{hit_count} 次（当前统计命中阈值）",
            "gate": "调研结果置信度 ≥70 才可入 keyword.yaml/entities.yaml（§8.4）",
            "level": "deep_realtime",
        }
    misses = top_misses(hit_count)
    return {
        "suggest": [m["word"] for m in misses],
        "trigger": f"{len(misses)} 个词达到未命中阈值 {hit_count}",
        "gate": "调研结果置信度 ≥70 才可入 keyword.yaml/entities.yaml（§8.4）",
        "level": "deep_realtime",
    }


def reset(word: str) -> None:
    """入库/确认后重置计数"""
    with _lock:
        data = _load()
        if word in data:
            data.pop(word)
            _save(data)


# ============ V8.6 M0.9 P4-norm 实体缺失观测（method 实体离群补齐 · 驱动实体 auto-add） ============
# 问题背景：method 实体相对语料/关键词是"缺三段"离群者（无 auto-checkin/生命周期/使用校准/实体级缺失观测）。
# 本观测环补齐"实体缺失观测"一段：route() 检测到「工具编号式引用（如 G01）但未命中任何实体」时
# 调用 record_entity_miss → 同引用 ≥3 次触发实体库补录建议（置信度门控 ≥70 入库，对齐 §8.4）。

def _load_entity_miss() -> dict:
    try:
        if ENTITY_MISS_STATS.exists():
            return json.loads(ENTITY_MISS_STATS.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_entity_miss(data: dict) -> None:
    try:
        ENTITY_MISS_STATS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_entity_miss(token: str) -> list:
    """记录工具/方法引用未命中（未匹配任何实体）→ 返回达阈值的 token 列表

    Args:
        token: 用户 query 中出现的「疑似工具编号/方法名」但未命中实体索引（如 G01 / TRIZ）
    Returns:
        达 ENTITY_MISS_THRESHOLD 的 token 列表（触发实体库补录调研）
    """
    token = (token or "").strip()
    if not token or len(token) > 40:
        return []
    with _lock:
        data = _load_entity_miss()
        now = datetime.now().isoformat(timespec="minutes")
        e = data.setdefault(token, {"count": 0, "first_seen": now, "last_seen": now})
        e["count"] = min(e["count"] + 1, MAX_WORD_COUNT)
        e["last_seen"] = now
        bumped = [token] if e["count"] >= ENTITY_MISS_THRESHOLD else []
        if len(data) > MAX_ENTITY_MISS_ENTRIES:
            for k in sorted(data, key=lambda k: data[k].get("last_seen", ""))[:len(data) - MAX_ENTITY_MISS_ENTRIES]:
                data.pop(k, None)
        _save_entity_miss(data)
        return bumped


def top_entity_misses(threshold: int = ENTITY_MISS_THRESHOLD) -> list:
    """达阈值的实体缺失 token（待补录候选）"""
    data = _load_entity_miss()
    return sorted(
        [{"token": w, "count": e["count"], "last_seen": e.get("last_seen", "")}
         for w, e in data.items() if isinstance(e, dict) and e.get("count", 0) >= threshold],
        key=lambda x: -x["count"],
    )


def entity_miss_stats() -> dict:
    """实体缺失观测摘要"""
    data = _load_entity_miss()
    return {
        "total_tracked": len(data),
        "above_threshold": len(top_entity_misses()),
        "threshold": ENTITY_MISS_THRESHOLD,
    }


def reset_entity_miss(token: str) -> None:
    """实体补录/确认后重置计数"""
    with _lock:
        data = _load_entity_miss()
        if token in data:
            data.pop(token)
            _save_entity_miss(data)


# ============ M1.0 ② 实体正向命中观测（entity 级使用事实 · P3-norm 校准输入） ============
# 问题背景：method 实体相对语料/关键词是"缺三段"离群者，P4-norm 已补齐"实体缺失观测"
# （record_entity_miss），但缺"实体命中热度"一段 → 校准侧（tier/status 由使用事实推导）无输入。
# 本段补齐"实体正向命中"：router.match_entities 命中实体时调用 record_entity_hit →
# 累计每实体命中热度（count/first_seen/last_seen），供 guardian_reverse R8 做使用事实校准。

def _load_entity_hit() -> dict:
    try:
        if ENTITY_HIT_STATS.exists():
            return json.loads(ENTITY_HIT_STATS.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_entity_hit(data: dict) -> None:
    try:
        ENTITY_HIT_STATS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_entity_hit(name: str) -> dict:
    """记录实体正向命中（router 已匹配实体索引）→ 返回该实体累计观测

    Args:
        name: 命中实体的 name（如 "F01" / "ISO 9001" / "8D"）
    Returns:
        {name, count, first_seen, last_seen}（本次采样后聚合）
    """
    name = (name or "").strip()
    if not name or len(name) > 80:
        return {}
    with _lock:
        data = _load_entity_hit()
        now = datetime.now().isoformat(timespec="minutes")
        e = data.setdefault(name, {"count": 0, "first_seen": now, "last_seen": now})
        e["count"] = min(e["count"] + 1, MAX_WORD_COUNT)
        e["last_seen"] = now
        if len(data) > MAX_ENTITY_MISS_ENTRIES:
            for k in sorted(data, key=lambda k: data[k].get("last_seen", ""))[:len(data) - MAX_ENTITY_MISS_ENTRIES]:
                data.pop(k, None)
        _save_entity_hit(data)
        return {"name": name, "count": e["count"], "first_seen": e["first_seen"], "last_seen": e["last_seen"]}


def top_entity_hits(threshold: int = 1) -> list:
    """达阈值的实体命中（按热度降序）"""
    data = _load_entity_hit()
    return sorted(
        [{"name": w, "count": e["count"], "last_seen": e.get("last_seen", "")}
         for w, e in data.items() if isinstance(e, dict) and e.get("count", 0) >= threshold],
        key=lambda x: -x["count"],
    )


def entity_hit_stats() -> dict:
    """实体正向命中观测摘要"""
    data = _load_entity_hit()
    return {
        "total_tracked": len(data),
        "total_hits": sum(e.get("count", 0) for e in data.values() if isinstance(e, dict)),
    }


def reset_entity_hit(name: str) -> None:
    """实体命中计数重置"""
    with _lock:
        data = _load_entity_hit()
        if name in data:
            data.pop(name)
            _save_entity_hit(data)


# ============ S2 使用事实采样（正向命中 · 供意图分布校准器 ⑰-R3 消费） ============

def _load_usage() -> dict:
    """读 usage_stats.json（词 → 意图/领域分布 + 语境词集）"""
    try:
        if USAGE_STATS.exists():
            return json.loads(USAGE_STATS.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_usage(data: dict) -> None:
    try:
        USAGE_STATS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _extract_context_words(query: str) -> list:
    """提取语境词（中文 2-6 字片段 + 英文词）——用于观察命中词的使用场景"""
    ctx = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,6}", query or ""):
        if len(run) >= 2:
            ctx.add(run)
    ctx.update(w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", query or ""))
    return sorted(ctx)[:MAX_CONTEXT_WORDS]


def record_hit(word: str, intent: str, domains: list = None, query: str = "") -> dict:
    """正向命中采样：记录词条的实际使用事实（会话级 · 幂等聚合）

    Args:
        word:    命中词条主词
        intent:  路由实际输出的意图（best_intent · 可能是歧义消解后）
        domains: 路由实际输出的领域列表（默认 ['通用']）
        query:   原始查询（提取语境词）
    Returns:
        {"word": word, "total": n, "intent_dist": {...}}（本次采样后聚合）
    """
    if not word or not intent:
        return {}
    with _lock:
        data = _load_usage()
        now = datetime.now().isoformat(timespec="minutes")
        e = data.setdefault(word, {
            "intent_dist": {}, "domain_dist": {}, "context_words": [],
            "total": 0, "first_seen": now, "last_seen": now,
        })
        e["intent_dist"][intent] = e["intent_dist"].get(intent, 0) + 1
        for d in (domains or ["通用"]):
            e["domain_dist"][d] = e["domain_dist"].get(d, 0) + 1
        for c in _extract_context_words(query):
            if c and c != word and c not in e["context_words"]:
                e["context_words"].append(c)
        e["context_words"] = e["context_words"][:MAX_CONTEXT_WORDS]
        e["total"] += 1
        e["last_seen"] = now
        # 容量治理：超限淘汰最旧
        if len(data) > MAX_USAGE_ENTRIES:
            for k in sorted(data, key=lambda k: (data[k].get("last_seen", "") or ""))[:len(data) - MAX_USAGE_ENTRIES]:
                data.pop(k, None)
        _save_usage(data)
        return {"word": word, "total": e["total"], "intent_dist": e["intent_dist"]}


def usage_stats(word: str = None) -> dict:
    """使用事实分布查询（⑰-R3 校准器输入）

    Args:
        word: 指定词（全部词用 None）
    Returns:
        {"total_words": n, "total_hits": n, "words": {word: entry}}（word 指定时单条）
    """
    data = _load_usage()
    if word:
        e = data.get(word)
        return e if e else {}
    return {
        "total_words": len(data),
        "total_hits": sum(e.get("total", 0) for e in data.values() if isinstance(e, dict)),
        "words": data,
    }


def stats() -> dict:
    """观测摘要（供 /metrics 与闭环报告）"""
    data = _load()
    return {
        "total_tracked": len(data),
        "above_threshold": len(top_misses()),
        "threshold": MISS_THRESHOLD,
    }


def main():
    if "--stats" in sys.argv:
        s = stats()
        print(f"未命中词观测：跟踪 {s['total_tracked']} 词 · 达阈值 {s['above_threshold']}（≥{s['threshold']}）")
        for m in top_misses()[:10]:
            print(f"  🔍 {m['word']}（{m['count']} 次 · 最近 {m['last_seen'][:16]}）")
        return 0
    if "--usage" in sys.argv:
        u = usage_stats()
        print(f"使用事实采样（usage_stats.json）：{u['total_words']} 词 · {u['total_hits']} 次命中")
        for w, e in sorted(u["words"].items(), key=lambda x: -x[1].get("total", 0))[:10]:
            doms = ",".join(e.get("domain_dist", {}).keys()) or "通用"
            print(f"  📊 {w}: {e.get('total', 0)} 次 · 意图 {e.get('intent_dist', {})} · 领域[{doms}]"
                  f"{(' · 语境 ' + ','.join(e.get('context_words', [])[:4])) if e.get('context_words') else ''}")
        return 0
    if len(sys.argv) >= 4 and sys.argv[1] == "--usage-record":
        # --usage-record <word> <intent> [domains...]
        domains = [a for a in sys.argv[4:] if not a.startswith("--")]
        record_hit(sys.argv[2], sys.argv[3], domains or None)
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--record":
        bumped = record_miss(sys.argv[2])
        print(f"已记录：{sys.argv[2]} → 达阈值词: {bumped}")
        return 0
    if "--entity-stats" in sys.argv:
        s = entity_miss_stats()
        print(f"实体缺失观测：跟踪 {s['total_tracked']} token · 达阈值 {s['above_threshold']}（≥{s['threshold']}）")
        for m in top_entity_misses()[:10]:
            print(f"  🔧 {m['token']}（{m['count']} 次 · 最近 {m['last_seen'][:16]}）→ 建议补录实体")
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--entity-record":
        bumped = record_entity_miss(sys.argv[2])
        print(f"已记录实体缺失：{sys.argv[2]} → 达阈值 token: {bumped}")
        return 0
    if "--entity-hit-stats" in sys.argv:
        s = entity_hit_stats()
        print(f"实体正向命中观测：跟踪 {s['total_tracked']} 实体 · 累计命中 {s['total_hits']}")
        for m in top_entity_hits()[:10]:
            print(f"  🎯 {m['name']}（{m['count']} 次 · 最近 {m['last_seen'][:16]}）")
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--entity-hit-record":
        record_entity_hit(sys.argv[2])
        print(f"已记录实体命中：{sys.argv[2]}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
