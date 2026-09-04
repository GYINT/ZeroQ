#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 大语料懒加载读取器（P2-8）

替代"激活即全量读入"：按锚点/关键词按需读取大语料片段。

用法：
  from corpus_loader import load_section, search_corpus, list_anchors, is_excluded_from_full

  load_section("tools.md", "A01. SPC 统计过程控制") # 返回该章节文本
  search_corpus("双归零")                             # 跨全量语料关键词定位（默认排除 EXCLUDE 项）
  list_anchors("masters.md")                          # 锚点清单（标题/行号/行数）
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "references" / "index"

# 大语料文件映射（stem → 相对路径）
# V8.6：改为从 corpus_manifest.yaml 单一真源读取（自适应分类 + 自动检入）
#   - corpus + excluded 合并为 full_rels（供 load_section/list_anchors 按需检索）
#   - excluded 子集供 is_excluded_from_full / search_corpus 默认跳过
# 兜底：manifest 缺失时回退脚本内置硬编码（与历史一致）。
from corpus_manifest import full_rels, excluded_stems

CORPUS_FILES = full_rels()

EXCLUDED_FROM_FULL = excluded_stems()


# --- G-EVT-6：消费端 P2/P3 双检索面 event_id 去重（2026-09-02 · 潜伏缺口硬化） ---
# 背景：同一 event_id 可能同时存在于 P2（sources/events 原始证据）与 P3
# （scenarios/events 归一化入口），二者均判 corpus → search_corpus 双命中。
# 设计：按 rel 提取 event_id 建"非 canonical stem 跳过集"，收敛检索主面到 P3。
_EVENT_RE = re.compile(r"QE-\d{4}-\d{3}", re.I)
_EVENT_SKIP = None
_EVENT_SKIP_SRC = None


def event_id_of(rel: str) -> str:
    """从语料 rel（references/**）提取事件 id；非事件文件返回空串。

    主键：文件名正则 ``QE-<年4>-<序3>``（P2/P3 两面文件名均含 event_id，单一可靠，
    不依赖作者是否写对 metaline）。兜底：仅当文件名无匹配时读文件首 3 行
    metaline（P3 ``case-ze-<id>`` / P2 ``event_id: <id>``）。
    """
    if not rel:
        return ""
    m = _EVENT_RE.search(rel)
    if m:
        return m.group(0).upper()
    try:
        p = ROOT / rel
        if p.exists():
            head = p.read_text(encoding="utf-8", errors="ignore").splitlines()[:3]
            for ln in head:
                mm = re.search(r"case-ze-(QE-\d{4}-\d{3})", ln, re.I)
                if mm:
                    return mm.group(1).upper()
                mm2 = re.search(r"event_id:\s*(QE-\d{4}-\d{3})", ln, re.I)
                if mm2:
                    return mm2.group(1).upper()
    except Exception:
        pass
    return ""


def _canonical_event_stems(force: bool = False) -> set:
    """返回应被 search_corpus 跳过的非 canonical event stem 集合（带缓存）。

    同一 event_id 若多面存在（P2 sources/events + P3 scenarios/events 归一化入口），
    仅保留 canonical 面（优先 rel 含 ``scenarios/events``），其余面整体跳过，
    避免检索结果对同一事件双命中。非事件文件（不匹配正则）永不入组 → 零误伤。

    缓存按 ``id(CORPUS_FILES)`` 失效：monkeypatch 替换 CORPUS_FILES 即自动重算。
    """
    global _EVENT_SKIP, _EVENT_SKIP_SRC
    if not force and _EVENT_SKIP is not None and _EVENT_SKIP_SRC is CORPUS_FILES:
        return _EVENT_SKIP
    groups = {}
    for stem, rel in CORPUS_FILES.items():
        eid = event_id_of(rel)
        if eid:
            groups.setdefault(eid, []).append((stem, rel))
    skip = set()
    for eid, items in groups.items():
        if len(items) > 1:
            canon = None
            for stem, rel in items:
                if "scenarios/events" in rel:
                    canon = (stem, rel)
                    break
            if canon is None:
                # 无 P3 时退化为文件名更短者（归一化入口）
                canon = min(items, key=lambda x: len(x[0]))
            skip.update(s for s, r in items if s != canon[0])
    _EVENT_SKIP = skip
    _EVENT_SKIP_SRC = CORPUS_FILES
    return skip


def is_excluded_from_full(stem: str) -> bool:
    """该语料对象是否被显式排除全量输入（仅索引使用）。"""
    return stem in EXCLUDED_FROM_FULL

_LINE_CACHE = {}
_INDEX_CACHE = {}
_TIER_MAP = None


def _tier_map(force: bool = False) -> dict:
    """② 动态分类分层增强（M2）：从运行态缓存读取 {name: tier}。

    懒加载 + 失败安全：缓存不可用（未 build/导入失败）时返回 {} → 调用方退化为无 tier 排序。
    name 用 CORPUS_FILES 的 rel（references 根为相对路径），与 corpus_cache 写入键一致。
    """
    global _TIER_MAP
    if _TIER_MAP is not None and not force:
        return _TIER_MAP
    m = {}
    try:
        from corpus_cache import CorpusCache
        from paths import REFERENCES
        cache = CorpusCache(str(REFERENCES))
        m = cache.export_tiers()
    except Exception:
        m = {}
    _TIER_MAP = m
    return m


def _capture_heat(stem: str, title: str = "", via: str = "load_section") -> None:
    """⑤ 关联引用热度埋点（M5 前置 · 失败安全：ref_heat 未建/异常不阻塞检索）。

    延迟导入 ref_heat，避免 M2 阶段依赖尚未创建的模块。
    """
    try:
        from ref_heat import capture
        capture(stem, title, via)
    except Exception:
        pass


def _resolve_corpus_name(rel: str):
    """把 CORPUS_FILES 的 rel（references/**）解析为 corpus_files.name（仓库根相对路径）。

    corpus_files 的 193 个 name 均为「去 references/ 前缀」的仓库根相对路径
    （如 tools/tools.md），而 CORPUS_FILES 值为 references/tools/tools.md，
    两者命名空间不一致（D5/D7 同源）。三级解析：精确 → 去前缀 → 文件名后缀。
    失败安全：无匹配返回 None（调用方跳过，绝不写孤儿脏键）。
    """
    if not rel:
        return None
    no_ref = rel[len("references/"):] if rel.startswith("references/") else rel
    base = rel.rsplit("/", 1)[-1]
    try:
        from corpus_cache import CorpusCache
        from paths import REFERENCES
        db = CorpusCache(str(REFERENCES)).db_path
        import sqlite3
        with sqlite3.connect(db) as conn:
            cur = conn.cursor()
            for cand in (rel, no_ref):
                if cur.execute("SELECT 1 FROM corpus_files WHERE name=?", (cand,)).fetchone():
                    return cand
            row = cur.execute(
                "SELECT name FROM corpus_files WHERE name LIKE ? LIMIT 1",
                ("%/" + base,)).fetchone()
            if row:
                return row[0]
    except Exception:
        pass
    return None


def _record_tier_access(rel: str) -> None:
    """访问计数回流 tier（可选 · 默认关闭 · D7a 已修复命名空间）。

    背景：corpus_files 当前 193 行**不含任何 references/** 前缀（14 个大语料
    未注册进 corpus_files），其 tier 恒为 build 时静态值，hot/warm/cold 动态
    分层对大语料结构性失效。本函数经 _resolve_corpus_name 把 rel 对齐到合法
    corpus_files.name 后再 record_access，无匹配则跳过（防孤儿脏键）。

    默认关闭（需 QCM_CORPUS_RECORD_ACCESS=1 启用）：因其会改写 tier 推导，
    并经 corpus_cache 间接影响 asset_retirement 的删减判定，属中风险变更，
    须评估后再开启；开启前须先确保 references/** 已登记进 corpus_files。
    """
    if not rel or os.environ.get("QCM_CORPUS_RECORD_ACCESS", "0") != "1":
        return
    name = _resolve_corpus_name(rel)
    if not name:
        return  # 无合法 corpus_files.name → 跳过，防孤儿脏键（D7a）
    try:
        from corpus_cache import CorpusCache
        from paths import REFERENCES
        CorpusCache(str(REFERENCES)).record_access(name)
    except Exception:
        pass


def _load_index(stem: str) -> dict:
    if stem in _INDEX_CACHE:
        return _INDEX_CACHE[stem]
    idx_path = INDEX_DIR / f"{stem}.index.yaml"
    if not idx_path.exists():
        return {}
    data = {}
    anchors = []
    current = None
    for ln in idx_path.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s.startswith("file: "):
            data["file"] = s[6:].strip()
        elif s.startswith("anchor_count: "):
            data["anchor_count"] = int(s[14:].strip())
        elif s.startswith("- {title:"):
            # 解析 {title: xxx, level: N, line: N, end_line: N, lines: N}
            m = re.match(r"- \{title: (.+), level: (\d+), line: (\d+), end_line: (\d+), lines: (\d+)\}", s)
            if m:
                anchors.append({
                    "title": m.group(1), "level": int(m.group(2)),
                    "line": int(m.group(3)), "end_line": int(m.group(4)),
                    "lines": int(m.group(5)),
                })
    data["anchors"] = anchors
    _INDEX_CACHE[stem] = data
    return data


def _load_lines(stem: str) -> list:
    if stem in _LINE_CACHE:
        return _LINE_CACHE[stem]
    rel = CORPUS_FILES.get(stem)
    if not rel:
        return []
    path = ROOT / rel
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    _LINE_CACHE[stem] = lines
    return lines


def list_anchors(stem: str) -> list:
    """返回锚点清单 [{title, level, line, end_line, lines}]"""
    data = _load_index(stem)
    return data.get("anchors", [])


def load_section(stem: str, title: str) -> str:
    """按标题（支持模糊匹配）读取章节片段。未命中返回空串。"""
    # ⑤ 埋点：检索即引用事件（失败安全）
    _capture_heat(stem, title, "load_section")
    _record_tier_access(CORPUS_FILES.get(stem, ""))
    anchors = list_anchors(stem)
    if not anchors:
        return ""
    # 精确匹配优先，其次包含匹配
    hit = None
    for a in anchors:
        if a["title"] == title:
            hit = a
            break
    if hit is None:
        for a in anchors:
            if title in a["title"] or a["title"] in title:
                hit = a
                break
    if hit is None:
        return ""
    lines = _load_lines(stem)
    seg = lines[hit["line"] - 1: hit["end_line"]]
    return "\n".join(seg)


def _tier_of(rel: str, tiers: dict) -> str:
    """按命名空间归一化查询 tier（D5 修复 · 可单测）。

    tiers 的 key 来自 corpus_cache.export_tiers()（仓库根相对路径、全仓文件），
    而 rel 来自 CORPUS_FILES（references/**、14 个大语料），两者直接查表
    命中数为 0。故先精确匹配，再退化为「文件名后缀」匹配。
    """
    if rel in tiers:
        return tiers[rel]
    base = rel.rsplit("/", 1)[-1]              # 如 tools.md
    for k, v in tiers.items():
        if k == base or k.endswith("/" + base):
            return v
    return "warm"


_REL2STEM = None


def _stem_of_rel(rel: str) -> str:
    """rel（references/**）→ stem。供 search_corpus 命中后按 stem 埋点（D4）。"""
    global _REL2STEM
    if _REL2STEM is None:
        _REL2STEM = {v: k for k, v in CORPUS_FILES.items()}
    return _REL2STEM.get(rel, "")


def search_corpus(keyword: str, max_hits: int = 5, include_excluded: bool = False) -> list:
    """跨大语料关键词搜索，返回 [{file, line, text}]（仅 120 字片段，非全量）

    include_excluded=False（默认）：跳过 EXCLUDED_FROM_FULL 项，
    确保 test-cases 等被显式排除全量输入的语料绝不被整体扫描。

    ② tier 感知：命中结果按 stem 的 tier 排序（hot 优先、cold 降级），
    同 tier 内保持出现顺序。tier 缺失时退化为原顺序（失败安全）。
    """
    results = []
    kw = keyword.lower()
    tiers = _tier_map()
    skip = _canonical_event_stems()  # G-EVT-6：收敛双检索面到 canonical（P3）
    for stem, rel in CORPUS_FILES.items():
        if stem in skip:
            continue
        if not include_excluded and is_excluded_from_full(stem):
            continue
        lines = _load_lines(stem)
        for i, ln in enumerate(lines):
            if kw in ln.lower():
                results.append({"file": rel, "line": i + 1, "text": ln.strip()[:120]})
                if len(results) >= max_hits:
                    break
    # tier 感知排序：hot=0, warm=1, cold=2（缺失默认 warm=1）
    # D5 修复：tiers 的 key 来自 corpus_cache.export_tiers()（仓库根相对路径、
    # 覆盖全仓 193 个文件），而 r["file"] 来自 CORPUS_FILES（references/**、
    # 14 个大语料）——两者命名空间不相交，实测命中数为 0，原 `tiers.get(...)`
    # 恒 miss，所谓「hot 优先、cold 降级」完全失效。现按文件名后缀归一化匹配。
    tier_rank = {"hot": 0, "warm": 1, "cold": 2}
    results.sort(key=lambda r: tier_rank.get(_tier_of(r["file"], tiers), 1))
    results = results[:max_hits]

    # ⑤ 埋点：检索即引用事件（失败安全）
    # D4 修复：原实现 `_capture_heat(keyword, "", "search_corpus")` 把**关键词**
    # 当作 stem 埋点，与 load_section 的文件 stem 语义不一致——共现聚合会把
    # 「关键词 ↔ 文件」误当成「文件 ↔ 文件」配对，污染 confirmed_pairs 及
    # M3 阈值校准源。现改为对命中的语料 stem 逐一埋点（检索命中即该语料被引用）。
    for r in results:
        _s = _stem_of_rel(r["file"])
        if _s:
            _capture_heat(_s, keyword, "search_corpus")
            _record_tier_access(r["file"])
    return results


def total_sections(stem: str) -> int:
    """锚点数（用于统计/报告）"""
    return len(list_anchors(stem))
