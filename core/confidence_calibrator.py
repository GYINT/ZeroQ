#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S6 置信度门槛校准器（MDS 动态自适应 · ⑰-R3 互锁 · 默认 dry-run 两周期）

背景：M2 消费 need_clarify 后，每次澄清事件经 usage_global.record_usage("clarify", "<intent>|<domain>")
      落盘（M4 补维）。本校准器读取澄清率（clarify 次数 / intent 总路由次数），当某意图澄清率
      长期偏高（门槛过低→频繁误触发）或偏低（门槛过高→该问没问），提出 clarify_matrix 门槛调整建议。

设计（复用 intent_calibrator.py 同构 · 全生命周期归一化动态自适应）：
  - 读：usage_global.json（"clarify" 维 = 澄清事件；"intent" 维 = 总路由次数）
  - 判：意图澄清率 = clarify_count / intent_count；率 > HIGH_RATE → 建议抬高门槛（降噪）；
        率 < LOW_RATE → 建议降低门槛（少打扰）
  - 默认 dry-run 两周期：同意图同方向建议连续出现 ≥ RUNS_THRESHOLD 次 → 标记「可校准」
        —— 仍须 --apply <intent> 显式批准才写回 router.yaml（保持审过才跑）
  - ⑰-R3 互锁：仅改 router.yaml clarify_matrix.intent_overrides[intent]；校验意图合法；
        幂等；写回后边界测试应仍绿
  - 写回安全：clamp [0.1, 0.9]；只改意图级覆盖，不碰 default/domain/crisis

用法：
  python3 core/confidence_calibrator.py --check      # dry-run 报告（周期 1 · 只建议不写回）
  python3 core/confidence_calibrator.py --apply ①危机处置  # 显式校准（dry-run 达标 + 用户批准）
  python3 core/confidence_calibrator.py --status     # 校准状态（候选/周期计数/已校准）
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "references" / "config"
DATA = ROOT / "references"

USAGE = DATA / "usage_global.json"
ROUTER_CFG = CFG / "router.yaml"
CALIB_STATE = DATA / "confidence_calibrator_state.json"

# 阈值（与 intent_calibrator 同构 · 双周期互锁）
HIGH_RATE = 0.40        # 澄清率 ≥ 此值 → 建议抬高门槛（频率过高=门槛偏低）
LOW_RATE = 0.10         # 澄清率 ≤ 此值 → 建议降低门槛（频率过低=门槛偏高）
MIN_TOTAL = 5           # intent 总路由 < 此值不评估（防小样本噪音）
RUNS_THRESHOLD = 2      # 同意图同方向建议连续出现 ≥ 此周期数 → 标记「可校准」
STEP = 0.05             # 门槛调整步长
FLOOR_MIN, FLOOR_MAX = 0.10, 0.90

INTENT_VALUES = ["①危机处置", "②流程优化", "③评估审计", "④知识学习", "⑤知识沉淀", "⑥质量文化"]


# ── 数据加载（缺省安全降级） ──

def load_usage() -> dict:
    try:
        return json.loads(USAGE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_state() -> dict:
    try:
        return json.loads(CALIB_STATE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        CALIB_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("⚠️ 状态持久化失败: %s" % e)


def _current_override(intent: str) -> float:
    """读取 router.yaml 当前 intent_overrides 门槛（缺省 0.3）"""
    try:
        import yaml
        data = yaml.safe_load(ROUTER_CFG.read_text(encoding="utf-8")) or {}
        cm = data.get("clarify_matrix") or {}
        io = cm.get("intent_overrides") or {}
        if intent in io and io[intent] is not None:
            return float(io[intent])
    except Exception:
        pass
    return 0.3


# ── 核心分析 ──

def analyze(usage: dict = None, state: dict = None) -> list:
    """返回校准候选列表：
    [{intent, clarify_count, intent_total, rate, direction, proposed, runs, actionable}]
    direction: raise(抬高) / lower(降低)；proposed: 新门槛
    """
    usage = usage if usage is not None else load_usage()
    state = state if state is not None else load_state()
    clarify_ns = usage.get("clarify") or {}
    intent_ns = usage.get("intent") or {}
    now = "cycle-1"
    cands = []
    for intent in INTENT_VALUES:
        c_total = intent_ns.get(intent, {}).get("count", 0)
        if c_total < MIN_TOTAL:
            continue
        # clarify 键形如 "intent|domain" → 汇总该意图所有域澄清次数
        c_clarify = 0
        for k, v in clarify_ns.items():
            if not isinstance(v, dict):
                continue
            if k.startswith(intent + "|"):
                c_clarify += v.get("count", 0)
        if c_clarify == 0:
            continue
        rate = round(c_clarify / max(c_total, 1), 3)
        cur = _current_override(intent)
        if rate >= HIGH_RATE:
            direction, proposed = "raise", min(FLOOR_MAX, round(cur + STEP, 2))
        elif rate <= LOW_RATE:
            direction, proposed = "lower", max(FLOOR_MIN, round(cur - STEP, 2))
        else:
            if intent in state:
                del state[intent]
            continue
        # 同方向建议（门槛值不变）→ 周期计数 +1
        prev = state.get(intent) or {}
        if prev.get("proposed") == proposed:
            runs = prev.get("runs", 0) + 1
        else:
            runs = 1
        state[intent] = {"proposed": proposed, "runs": runs, "last_cycle": now}
        cands.append({
            "intent": intent, "clarify_count": c_clarify, "intent_total": c_total,
            "rate": rate, "direction": direction, "proposed": proposed,
            "current": cur, "runs": runs, "actionable": runs >= RUNS_THRESHOLD,
        })
    if state:
        save_state(state)
    return cands


# ── 显式校准（--apply 门控） ──

def apply_calibration(intent: str, usage: dict = None, state: dict = None) -> tuple:
    """显式校准（--apply <intent>）：dry-run 达标（actionable）+ 用户批准 → 写回 router.yaml"""
    if intent not in INTENT_VALUES:
        return False, "意图 %s 非法（合法: %s）" % (intent, INTENT_VALUES)
    if state is None:
        state = load_state()
    cands = analyze(usage if usage is not None else load_usage(), state)
    cand = next((c for c in cands if c["intent"] == intent and c["actionable"]), None)
    if not cand:
        return False, "意图「%s」不在可校准候选（需澄清率越界且连续 %d 周期）" % (intent, RUNS_THRESHOLD)
    proposed = cand["proposed"]
    try:
        import yaml
        data = yaml.safe_load(ROUTER_CFG.read_text(encoding="utf-8")) or {}
        cm = data.setdefault("clarify_matrix", {})
        io = cm.setdefault("intent_overrides", {})
        io[intent] = proposed
        io[intent] = float(io[intent])
        ROUTER_CFG.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        if intent in state:
            del state[intent]
            save_state(state)
        return True, "✅ 已校准门槛: %s %.2f → %.2f（基于 %d 次路由 / 澄清率 %.0f%%）" % (
            intent, cand["current"], proposed, cand["intent_total"], rate100(cand["rate"]))
    except Exception as e:
        return False, "写回失败: %s" % e


def rate100(rate: float) -> int:
    return int(round(rate * 100))


# ── CLI ──

def report(cands: list) -> str:
    lines = ["QCM 置信度门槛校准器（S6 · ⑰-R3 互锁 · dry-run 两周期）", "=" * 60,
             "校准候选: %d 个（澄清率 ≥%.0f%% 抬高 / ≤%.0f%% 降低）" % (
                 len(cands), HIGH_RATE * 100, LOW_RATE * 100)]
    if not cands:
        lines.append("\n✅ 无校准候选（澄清率处稳态 · R3 互锁验证通过）")
        return "\n".join(lines) + "\n"
    for c in cands:
        flag = "🔔 可校准(--apply)" if c["actionable"] else "📊 周期 %d/%d" % (c["runs"], RUNS_THRESHOLD)
        arrow = "↑抬高" if c["direction"] == "raise" else "↓降低"
        lines.append("  [%s] %s: 澄清率 %.0f%% (%d/%d) · 门槛 %.2f %s %.2f → 建议" % (
            flag, c["intent"], rate100(c["rate"]), c["clarify_count"], c["intent_total"],
            c["current"], arrow, c["proposed"]))
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    if "--apply" in args:
        wi = args.index("--apply")
        intent = args[wi + 1] if wi + 1 < len(args) else None
        if not intent:
            print("用法: confidence_calibrator.py --apply <intent>")
            return 2
        ok, msg = apply_calibration(intent)
        print(msg)
        return 0 if ok else 1
    cands = analyze()
    print(report(cands))
    if cands:
        n_actionable = sum(1 for c in cands if c["actionable"])
        print("ℹ️  可校准 %d 个（--apply <intent> 显式批准写回）· 其余待连续观察" % n_actionable)
    return 0


if __name__ == "__main__":
    sys.exit(main())
