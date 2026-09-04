#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 关联引用热度自动回灌与聚合互链（M5 · ⑤ 核心）

目标：捕获语料检索/引用事件 → 聚合共现/互引 → 发现高引用对与未互链对 →
      回灌沉淀（默认 dry，需 QCM_REF_HEAT_APPLY=1）→ 动态反馈 M3 阈值校准。

机制：
  ① capture(stem, section, via)：实时埋点（load_section/search_corpus/cross_ref/host_read(预留)）。
      落 outputs/.runtime/ref_heat.json（窗口聚合：weekly 为主、cumulative 为辅）。
      失败安全：磁盘/解析异常不抛（不阻塞检索）。
  ② aggregate(window)：计算 (stemA, stemB) 共现/互引频次 → 高引用对、未互链对
      （A→B 有引用、B→A 无）。三维分层触发：数据层 tier（复用 corpus_cache.export_tiers）
      + 关系层 共现强度（strong≥5/周）+ 时间层 窗口（weekly 建议/cumulative 校准）。
  ③ suggest_links()：对未互链对生成互链建议（复用 §4 联动格式）。
  ④ backfill_suggest()：默认 dry（仅打印建议）；QCM_REF_HEAT_APPLY=1 才写回
      SOLE 权威源或相关文件"主动联动"节（防误改语料 · M0.4 决策）。
  ⑤ confirmed_pairs 反馈：backfill/人工确认后写回 ref_heat.json，供 M3 file_homology
      校准 0.6 基准（report-only，不写 yaml）。

调度（M0.6 决策）：capture 实时无频限；nightly [6.12] 仅 aggregate+suggest dry；
      真实 backfill 每月 ≤2 次由独立定时器/automation 调度（非夜巡常跑）。
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "outputs" / ".runtime"
HEAT_PATH = RUNTIME_DIR / "ref_heat.json"

WEEK_SECONDS = 7 * 86400
STRONG_WEEKLY = int(os.environ.get("QCM_REF_HEAT_STRONG", 5))  # 周共现强度阈值

# 相似度通道故障计数（D3：故障必须可观测，否则「0 建议」与「真无数据」无法区分）
_SIM_FAULTS: Dict[str, int] = {}

# 已确认同根（动态校准 M3 阈值源）
CONFIRMED_DEFAULT: Dict[str, float] = {}


def _strong_threshold(weeks: int) -> int:
    """共现强度阈值：窗口自适应（D2 修复）。

    原实现固定比对 STRONG_WEEKLY(默认 5)，但 cooccur[pair] 计的是「周桶数」
    ——即该 pair 同现于多少个周桶——其上限为窗口周数（weeks=4 时上限仅 4~5）。
    故 `c >= 5` 几乎恒不成立，high_ref 结构性恒空，三维分层中的「共现强度」
    维度形同虚设，suggest/backfill 实际只剩 `sim >= 0.6` 单通道生效。

    现按窗口自适应取 min(STRONG_WEEKLY, weeks)，下限 2（避免窗口过窄时
    1 次偶发共现即判强）。
    """
    return max(2, min(STRONG_WEEKLY, weeks))


def sim_faults() -> Dict[str, int]:
    """返回相似度通道故障计数快照（D3 可观测性）。"""
    return dict(_SIM_FAULTS)


def _warn_sim(a: str, b: str, e: Exception, stage: str) -> None:
    """相似度通道故障告警（D3）：区分 import/compute/read 阶段，累计计数 + stderr。

    同类故障（同 stage + 同异常类型）仅首次打印明细，其余静默计数，避免语料
    规模较大时告警刷屏（14 个大语料 → 最多 91 对）；CLI 末尾统一输出汇总。
    """
    key = f"{stage}:{type(e).__name__}"
    n = _SIM_FAULTS.get(key, 0)
    _SIM_FAULTS[key] = n + 1
    if n == 0:
        print(f"  [ref_heat] WARN 相似度{stage}失败（首例 {a}|{b}）："
              f"{type(e).__name__}: {e} → 退化为 0.0（同类故障后续仅计数）",
              file=sys.stderr)


def _now() -> float:
    return time.time()


def _load() -> dict:
    try:
        if HEAT_PATH.exists():
            return json.loads(HEAT_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"events": [], "confirmed_pairs": {}, "last_aggregate": None}


def _save(d: dict) -> None:
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        json.dump(d, HEAT_PATH.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass


def _week_bucket(ts: float) -> str:
    """ISO 周桶（周一为界）。"""
    dt = datetime.fromtimestamp(ts)
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


# ── ① 实时埋点 ──
def capture(stem: str, section: str = "", via: str = "load_section") -> None:
    """检索/引用事件埋点（失败安全）。

    via ∈ {load_section, search_corpus, cross_ref, host_read(预留)}：
      - load_section / search_corpus：经 corpus_loader 的 MCP 工具路径（M0.a）
      - cross_ref：互链检测命中
      - host_read：**预留**给 true-B 宿主读钩子（待 WorkBuddy 提供文件读拦截面时启用）；
        启用时若与 MCP 路径同周同 stem 同 via 已记录，下方去重逻辑可防重复计数。

    M0.b 去重：同 (stem, via, week) 已存在则跳过追加。aggregate 本就按周桶去重共现，
    故周桶内唯一；此去重仅抑制 events 列表膨胀（A+B 联用/重复读场景），不改变 cooccur 信号。
    """
    try:
        d = _load()
        now = _now()
        wk = _week_bucket(now)
        # M0.b：周桶内同 (stem, via) 已记录 → 跳过，防 events 膨胀（不影响 cooccur）
        for e in d["events"]:
            if e.get("stem") == stem and e.get("via") == via and e.get("week") == wk:
                return
        ev = {
            "ts": now,
            "stem": stem,
            "section": section or "",
            "via": via,
            "week": wk,
        }
        d["events"].append(ev)
        # 控制体积：保留近 90 天事件（约 12 周）
        cutoff = now - 90 * 86400
        d["events"] = [e for e in d["events"] if e["ts"] >= cutoff]
        _save(d)
    except Exception:
        pass


# ── ② 聚合 ──
def aggregate(window: str = "weekly", weeks: int = 4) -> dict:
    """按窗口聚合共现/互引。

    Returns: {
      "cooccur": {(a,b): cnt},          # 共现（两文件同现于多少个「周桶」，非次数）
      "cross_ref": [(a,b)],             # 已互链对（正文互相引用）
      "high_ref": [(a,b,cnt)],          # 高引用对（cnt >= strong）
      "unlinked": [(a,b,cnt,sim)],      # 未互链对（建议互链）
      "strong": int,                    # 本次实际采用的共现强度阈值（窗口自适应）
      "weeks": int,                     # 窗口周数
    }

    注：cooccur 的 cnt 上限 = 窗口内的周桶数（约 weeks），故不可与固定阈值
    STRONG_WEEKLY 直接比较——详见 _strong_threshold（D2）。
    """
    d = _load()
    now = _now()
    if window == "weekly":
        cutoff = now - weeks * WEEK_SECONDS
        evs = [e for e in d["events"] if e["ts"] >= cutoff]
    else:  # cumulative
        evs = d["events"]

    # 按周分桶，桶内共现（同周访问两不同 stem）
    by_week: Dict[str, List[str]] = {}
    for e in evs:
        by_week.setdefault(e["week"], []).append(e["stem"])

    cooccur: Dict[Tuple[str, str], int] = {}
    for stems in by_week.values():
        uniq = sorted(set(stems))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                pair = (uniq[i], uniq[j])
                cooccur[pair] = cooccur.get(pair, 0) + 1

    # 交叉引用检测（复用 file_homology 思路，失败安全）
    cross_ref = _detect_cross_ref(set(cooccur.keys()))
    # D2：阈值随窗口自适应，而非固定 STRONG_WEEKLY（周桶数上限 = 窗口周数）
    strong = _strong_threshold(weeks)

    high_ref = [(a, b, c) for (a, b), c in cooccur.items() if c >= strong]
    unlinked = []
    for (a, b), c in cooccur.items():
        if (a, b) not in cross_ref and (b, a) not in cross_ref:
            sim = _pair_sim(a, b, d.get("confirmed_pairs", {}))
            unlinked.append((a, b, c, sim))

    return {
        "cooccur": {f"{a}|{b}": c for (a, b), c in cooccur.items()},
        "cross_ref": [f"{a}|{b}" for (a, b) in cross_ref],
        "high_ref": high_ref,
        "unlinked": sorted(unlinked, key=lambda x: x[2], reverse=True),
        "strong": strong,
        "weeks": weeks,
    }


def _detect_cross_ref(pairs) -> set:
    """检测已互链对（正文互相含对方 stem）。失败安全返回空集。

    D1 修复：原实现在循环内 `return {(a, b)}` ——命中即整体返回，导致全函数
    **最多只产出 1 对**，cross_ref 严重漏检；其后果是 unlinked 虚高，已互链
    的对被误判为「未互链」并写入 confirmed_pairs，反向污染 M3 阈值校准源。
    另：(a,b) 与 (b,a) 两次判定条件完全相同（互为充要），原 `seen` 分支属冗余。

    现改为：累积集合后统一返回；并缓存文件内容，避免 O(n²) 重复磁盘 IO。
    互链为对称关系，故每个无序 pair 只需判定一次。
    """
    try:
        from corpus_loader import CORPUS_FILES, ROOT as CROOT
        linked = set()
        text_cache: Dict[str, str] = {}

        def _text(stem: str) -> str:
            if stem not in text_cache:
                rel = CORPUS_FILES.get(stem, "")
                # 未登记 stem：CROOT / "" 会指向目录，read_text 抛 IsADirectoryError
                # 并被外层 except 吞掉 → 整个 cross_ref 检测退化为空集。此处显式短路。
                p = (CROOT / rel) if rel else None
                text_cache[stem] = (
                    p.read_text(encoding="utf-8", errors="ignore")
                    if p is not None and p.is_file() else "")
            return text_cache[stem]

        for (a, b) in pairs:
            if (a, b) in linked or (b, a) in linked:
                continue
            ta, tb = _text(a), _text(b)
            if not ta or not tb:
                continue
            if (b in ta or f"{b}.md" in ta) and (a in tb or f"{a}.md" in tb):
                linked.add((a, b))
        return linked
    except Exception:
        pass
    return set()


def _pair_sim(a: str, b: str, confirmed: dict) -> float:
    """未互链对相似度（供 suggest 排序）；已确认同根返回确认值。

    D3 修复：原实现整体 `except Exception: pass` 后统一 `return 0.0`，把
    「依赖缺失/算法异常」与「该对真实相似度为 0」压缩成同一个静默结果。
    典型场景：corpus_loader 依赖 PyYAML（QCM 声明的核心必需依赖），环境缺失时
    导入即失败 → 全部相似度静默退化为 0.0 → suggest/backfill 空转，且运维侧
    无法与「真无数据」区分。现按 import / compute 分级告警并累计计数。
    """
    key = f"{a}|{b}"
    if key in confirmed:
        return confirmed[key]
    try:
        from file_homology import _similarity
        from corpus_loader import CORPUS_FILES, ROOT as CROOT
    except Exception as e:      # 依赖缺失（如 PyYAML 未装）——必须可见
        _warn_sim(a, b, e, stage="import")
        return 0.0
    try:
        rel_a, rel_b = CORPUS_FILES.get(a, ""), CORPUS_FILES.get(b, "")
        if not rel_a or not rel_b:
            return 0.0          # stem 未登记 → 非故障，静默 0.0（不产生告警噪声）
        pa = CROOT / rel_a
        pb = CROOT / rel_b
        if pa.is_file() and pb.is_file():
            ta = pa.read_text(encoding="utf-8", errors="ignore")
            tb = pb.read_text(encoding="utf-8", errors="ignore")
            try:
                return round(_similarity(ta, a, tb, b), 3)
            except Exception as e:
                _warn_sim(a, b, e, stage="compute")
    except Exception as e:
        _warn_sim(a, b, e, stage="read")
    return 0.0


# ── ③ 建议 ──
def suggest_links(agg: dict = None, dry: bool = True) -> List[str]:
    """对未互链对生成互链建议（复用 §4 联动格式）。dry=True 仅返回文本。"""
    agg = agg or aggregate("weekly")
    # D2：用聚合结果中窗口自适应的阈值，而非固定 STRONG_WEEKLY
    strong = agg.get("strong", STRONG_WEEKLY)
    sugg = []
    for (a, b, cnt, sim) in agg["unlinked"]:
        # 关系层 + 相似度层：strong 共现（≥strong 周桶）或高相似（≥0.6 疑似同根）→ 建议互链
        # weak 且低相似 → 仅观测不建议（防噪声）
        if cnt < strong and sim < 0.6:
            continue
        line = (f"建议互链：{a}.md ↔ {b}.md（周共现 {cnt} · 相似度 {sim}）\n"
                f"  在 {a}.md 末尾加：参见 [{b}](references/knowledge/{b}.md)（关联引用/主动联动）\n"
                f"  在 {b}.md 末尾加：参见 [{a}](references/knowledge/{a}.md)")
        sugg.append(line)
    if dry:
        for s in sugg:
            print("  " + s)
    return sugg


# ── ④ 回灌（默认 dry） ──
def backfill_suggest(agg: dict = None, apply: bool = None) -> dict:
    """回灌沉淀到 SOLE 权威源或联动节。

    apply=None → 读环境变量 QCM_REF_HEAT_APPLY（默认 False=dry）。
    dry：仅报告；apply：写回（每月 ≤2 次由定时器控制，非夜巡常跑）。
    """
    if apply is None:
        apply = os.environ.get("QCM_REF_HEAT_APPLY", "0") == "1"
    agg = agg or aggregate("weekly")
    strong = agg.get("strong", STRONG_WEEKLY)
    result = {"applied": 0, "dry": not apply, "suggested": 0}
    sugg = suggest_links(agg, dry=True)
    result["suggested"] = len(sugg)
    if not apply:
        print(f"  (dry-run：{len(sugg)} 条建议未写回 · 需 QCM_REF_HEAT_APPLY=1 或定时器回灌)")
        return result

    # apply：将高置信对写入 confirmed_pairs（动态反馈 M3），不自动改语料正文
    # （防误改 · M0.4 纪律：人工确认后改正文，程序仅沉淀确认态）
    d = _load()
    d.setdefault("confirmed_pairs", {})
    for (a, b, cnt, sim) in agg["unlinked"]:
        if cnt >= strong or sim >= 0.6:
            d["confirmed_pairs"][f"{a}|{b}"] = sim
            result["applied"] += 1
    _save(d)
    print(f"  (apply：{result['applied']} 对写入 confirmed_pairs · 供 M3 阈值校准)")
    return result


# ── CLI ──
def _main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", nargs="*", default=[], help="stem section via")
    ap.add_argument("--aggregate", action="store_true")
    ap.add_argument("--window", default="weekly")
    ap.add_argument("--weeks", type=int, default=4,
                    help="weekly 窗口的周数（影响共现强度阈值，默认 4）")
    ap.add_argument("--suggest", action="store_true")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--apply", action="store_true", help="覆盖 dry（QCM_REF_HEAT_APPLY=1）")
    args = ap.parse_args()

    if args.capture:
        stem = args.capture[0]
        sec = args.capture[1] if len(args.capture) > 1 else ""
        via = args.capture[2] if len(args.capture) > 2 else "load_section"
        capture(stem, sec, via)
        print(f"  capture: {stem} / {sec} / {via}")
    if args.aggregate or args.suggest or args.backfill:
        agg = aggregate(args.window, weeks=args.weeks)
        print(f"  共现对 {len(agg['cooccur'])} · 已互链 {len(agg['cross_ref'])} "
              f"· 高引用 {len(agg['high_ref'])} · 未互链 {len(agg['unlinked'])} "
              f"· 强度阈值 {agg.get('strong')}（窗口 {agg.get('weeks')} 周）")
        faults = sim_faults()
        if faults:
            print(f"  ⚠ 相似度通道故障 {sum(faults.values())} 次："
                  + "，".join(f"{k}={v}" for k, v in sorted(faults.items())),
                  file=sys.stderr)
        if args.suggest:
            suggest_links(agg, dry=True)
        if args.backfill:
            backfill_suggest(agg, apply=args.apply)


if __name__ == "__main__":
    _main()
