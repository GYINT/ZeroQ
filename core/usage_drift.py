#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""澄清率漂移扫描（L3 · 复刻 g029_archive_drift 模板 · GAP-L1 动态自适应闭环延伸）

将"澄清率"登记为治理资产：以 references/usage_global.json 的 clarify/intent 双维为数据源，
逐意图计算澄清率 = 该意图澄清次数 / 该意图路由次数，
识别澄清率超阈值的意图（提示阈值/提示词需复盘 → 供 R3 confidence_calibrator 消费）。

由 core/governance_check.py::check_g031_clarify_drift 在 --check / --nightrun 时调用，
实现"采样即校验"的动态自适应（无需人工逐意图核对）。

设计（对齐 g029 / archive/inventory.py）：
  - 纯读 usage_global.json（report-only · 符合 M0.4 守卫约束）
  - 不改动任何文件、不写回阈值（写回由 confidence_calibrator --apply 门控）
  - 失败降级：usage_global.json 缺失/解析异常 → 返回空（fail-open 不阻断）

数据源（core/router.py route() 出口采样 · M2/M4 已接入）：
  - intent 维：  obj=<意图>，            count=路由命中次数
  - clarify 维： obj=<意图>|<领域>，      count=澄清触发次数

用法：
  python3 core/usage_drift.py            # 手动跑澄清率漂移扫描
被 governance_check 导入：from usage_drift import scan_clarify_drift
"""
import json
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
USAGE_GLOBAL = ROOT / "references" / "usage_global.json"

# 默认澄清率告警阈值（超此视为该意图澄清负担异常 → 触发复盘信号）
DEFAULT_RATE_ALERT = 0.20
# 最小样本：路由次数低于此值不告警（防小样本噪声误报）
DEFAULT_MIN_SAMPLES = 10


def _load_usage() -> dict:
    try:
        if USAGE_GLOBAL.exists():
            return json.loads(USAGE_GLOBAL.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def scan_clarify_drift(rate_alert: float = DEFAULT_RATE_ALERT,
                       min_samples: int = DEFAULT_MIN_SAMPLES) -> Tuple[List[dict], dict]:
    """返回 (drift, stats)

    - drift: 澄清率超阈值的意图明细列表 [{intent, rate, clarified, routed, window}]
    - stats: 全量 per-intent 统计 {intent: {routed, clarified, rate}}

    纯观测，不写回。fail-open：数据源异常返回双空。
    """
    data = _load_usage()
    intent_ns = data.get("intent", {}) if isinstance(data.get("intent"), dict) else {}
    clarify_ns = data.get("clarify", {}) if isinstance(data.get("clarify"), dict) else {}

    # 按意图聚合澄清次数（clarify obj 形如 <意图>|<领域>，取首段）
    clarify_by_intent: Dict[str, int] = {}
    for k, e in clarify_ns.items():
        if not isinstance(e, dict):
            continue
        intent = str(k).split("|", 1)[0]
        clarify_by_intent[intent] = clarify_by_intent.get(intent, 0) + int(e.get("count", 0))

    stats = {}
    drift = []
    for intent, e in intent_ns.items():
        if not isinstance(e, dict):
            continue
        routed = int(e.get("count", 0))
        clarified = clarify_by_intent.get(intent, 0)
        if routed <= 0:
            continue
        rate = clarified / routed if routed else 0.0
        stats[intent] = {"routed": routed, "clarified": clarified, "rate": round(rate, 4)}
        if routed >= min_samples and rate > rate_alert:
            drift.append({
                "intent": intent,
                "rate": round(rate, 4),
                "clarified": clarified,
                "routed": routed,
                "window": "all",
            })
    drift.sort(key=lambda x: -x["rate"])
    return drift, stats


def main() -> int:
    drift, stats = scan_clarify_drift()
    print("=== 澄清率漂移扫描（L3 · GAP-L1 动态自适应 · 复刻 g029） ===")
    print("已采集意图：%d 个" % len(stats))
    if stats:
        print("逐意图澄清率：")
        for intent, s in sorted(stats.items(), key=lambda x: -x[1]["rate"]):
            print("   ↳ %s  澄清率 %.1f%%（澄清 %d / 路由 %d）"
                  % (intent, s["rate"] * 100, s["clarified"], s["routed"]))
    if drift:
        print("⚠️ 超阈值意图（>%.0f%% · 须复盘 clarify_matrix / 提示词）：" % (DEFAULT_RATE_ALERT * 100))
        for d in drift:
            print("   ↳ %s  澄清率 %.1f%%（澄清 %d / 路由 %d）"
                  % (d["intent"], d["rate"] * 100, d["clarified"], d["routed"]))
    if not stats:
        print("✅ usage_global.json 无意图采样（或文件缺失）→ 无漂移可判")
    elif not drift:
        print("✅ 无意图澄清率超阈值（全部 ≤ %.0f%%）" % (DEFAULT_RATE_ALERT * 100))
    return 0


if __name__ == "__main__":
    main()
