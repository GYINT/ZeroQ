#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S6 意图分布校准器（决策校准环 · ⑰-R3 互锁 · 默认 dry-run 两周期）

背景：S2 usage_stats 记录每个词实际命中的意图分布（intent_dist）。当某词声明意图
      (keyword.yaml intent) 与实际使用主导意图长期偏离（主导占比 ≥60% 且 ≠ 声明），
      说明词条落库目标与实际使用场景错位。本校准器把「守卫告警（R3）」升级为
      「行动建议 + 显式批准写回」。

设计（全生命周期归一化动态自适应）：
  - 读：usage_stats.json（S2 采样 · word → intent_dist/total）
  - 判：声明意图 vs 实际主导意图；主导占比 = 主导计数/total ≥ CALIBRATE_PCT 且 ≠ 声明
  - 默认 dry-run 两周期：首次运行仅输出建议（不写回）；同词同方向建议连续出现
    达到 RUNS_THRESHOLD 次后，标记该词「可校准」——仍需 --apply <word> 显式批准才写回
  - ⑰-R3 互锁：校准器建议与 R3 守卫同源（usage_stats）——
      · R3 零告警时校准器必然零建议（互锁一致）
      · 校准器 --apply 写回 keyword.yaml 后，R3 重新检查应自动清零（闭环验证）
  - 写回安全：仅改 intent 字段 · 校验目标意图合法（INTENT_VALUES）· 幂等

用法：
  python3 core/intent_calibrator.py --check      # dry-run 报告（周期 1 · 只建议不写回）
  python3 core/intent_calibrator.py --apply 电芯  # 显式校准（dry-run 达标 + 用户批准）
  python3 core/intent_calibrator.py --status     # 校准状态（候选词/周期计数/已校准）
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "references" / "config"
DATA = ROOT / "references"

KEYWORD = CFG / "keyword.yaml"
USAGE = DATA / "usage_stats.json"
CALIB_STATE = DATA / "calibrator_state.json"

# 阈值（与 guardian_reverse.R3 对齐 · 双周期互锁）
CALIBRATE_PCT = 60        # 主导意图占比 ≥ 此值 且 ≠ 声明 → 建议校准
CALIBRATE_MIN_TOTAL = 3   # total 低于此值不评估（防小样本噪音 · 与 R3 一致）
RUNS_THRESHOLD = 2        # 同词同方向建议连续出现 ≥ 此周期数 → 标记「可校准」

INTENT_VALUES = ["①危机处置", "②流程优化", "③评估审计", "④知识学习", "⑤知识沉淀"]


# ── 数据加载（缺省安全降级） ──

def load_keywords(path: Path = None) -> list:
    path = path or KEYWORD
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get("keywords") or [])
    except Exception:
        return []


def load_usage(path: Path = None) -> dict:
    path = path or USAGE
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_state(path: Path = None) -> dict:
    """校准器状态：{word: {target_intent, runs, last_cycle}}（跨周期记忆）"""
    path = path or CALIB_STATE
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_state(state: dict, path: Path = None) -> None:
    path = path or CALIB_STATE
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"⚠️ 状态持久化失败: {e}")


# ── 核心分析 ──

def analyze(keywords: list = None, usage: dict = None, state: dict = None) -> list:
    """返回校准候选列表：
    [{word, declared, actual, pct, total, runs, actionable}]  # actionable: 达两周期可批准
    """
    keywords = keywords if keywords is not None else load_keywords()
    usage = usage if usage is not None else load_usage()
    state = state if state is not None else load_state()
    declared = {k.get("word"): k.get("intent") for k in keywords if isinstance(k, dict)}
    now = "cycle-1"  # 占位周期标识（实际由外部传入或状态推进）
    cands = []
    for w, st in usage.items():
        if not isinstance(st, dict):
            continue
        dist = st.get("intent_dist") or {}
        if not dist:
            continue
        dom_intent, dom_count = max(dist.items(), key=lambda kv: kv[1])
        total = st.get("total") or sum(dist.values())
        if total < CALIBRATE_MIN_TOTAL:
            continue
        pct = round(dom_count * 100.0 / total, 1)
        declared_intent = declared.get(w)
        if not declared_intent:
            continue  # 词不在 keyword.yaml（防御）
        if dom_intent == declared_intent or pct < CALIBRATE_PCT:
            # 一致或占比不足 → 非候选；清除历史建议（漂移消失）
            if w in state:
                del state[w]
            continue
        # 候选：同方向建议（主导意图不变）→ 周期计数 +1
        prev = state.get(w) or {}
        if prev.get("target_intent") == dom_intent:
            runs = prev.get("runs", 0) + 1
        else:
            runs = 1  # 方向变化 → 重新计数
        state[w] = {"target_intent": dom_intent, "runs": runs, "last_cycle": now}
        cands.append({
            "word": w, "declared": declared_intent, "actual": dom_intent,
            "pct": pct, "total": total, "runs": runs,
            "actionable": runs >= RUNS_THRESHOLD,
        })
    if state:
        save_state(state)  # 持久化周期记忆（仅当有状态变化）
    return cands


# ── 显式校准 ──

def apply_calibration(word: str, keywords: list = None, usage: dict = None, state: dict = None) -> tuple:
    """显式校准（--apply <word>）：dry-run 达标（actionable）+ 用户批准 → 写回 intent
    Returns:
        (success: bool, message: str)
    """
    keywords = keywords if keywords is not None else load_keywords()
    state = state if state is not None else load_state()
    cands = analyze(keywords, usage if usage is not None else load_usage(), state)
    cand = next((c for c in cands if c["word"] == word and c["actionable"]), None)
    if not cand:
        return False, f"词「{word}」不在可校准候选（需主导占比≥{CALIBRATE_PCT}% 且连续{RUNS_THRESHOLD}周期）"
    target = cand["actual"]
    if target not in INTENT_VALUES:
        return False, f"目标意图 {target} 非法（合法: {INTENT_VALUES}）"
    # 写回 keyword.yaml（仅改 intent）
    import yaml
    try:
        data = yaml.safe_load(KEYWORD.read_text(encoding="utf-8")) or {}
        items = data.get("keywords") or []
        found = False
        for it in items:
            if isinstance(it, dict) and it.get("word") == word:
                it["intent"] = target
                # 校准溯源（S3 审计可查）
                it.setdefault("calibrations", []).append({
                    "from": cand["declared"], "to": target, "cycle": "apply",
                })
                found = True
                break
        if not found:
            return False, f"词「{word}」不在 keyword.yaml"
        KEYWORD.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        # 校准后清状态（下周期重新计数）
        if word in state:
            del state[word]
            save_state(state)
        return True, f"✅ 已校准: {word} {cand['declared']} → {target}（基于 {cand['total']} 次使用事实）"
    except Exception as e:
        return False, f"写回失败: {e}"


# ── CLI ──

def report(cands: list) -> str:
    lines = ["QCM 意图分布校准器（S6 · ⑰-R3 互锁 · dry-run 两周期）", "=" * 60,
             f"校准候选: {len(cands)} 个（主导占比 ≥{CALIBRATE_PCT}% 且 ≠ 声明）"]
    if not cands:
        lines.append("\n✅ 无校准候选（声明意图与使用事实一致 · R3 互锁验证通过）")
        return "\n".join(lines) + "\n"
    for c in cands:
        flag = "🔔 可校准(--apply)" if c["actionable"] else f"📊 周期 {c['runs']}/{RUNS_THRESHOLD}"
        lines.append(
            f"  [{flag}] {c['word']}: 声明 {c['declared']} · 实际主导 {c['actual']} "
            f"({c['pct']}% · {c['total']}次) → 建议校准"
        )
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    if "--apply" in args:
        wi = args.index("--apply")
        word = args[wi + 1] if wi + 1 < len(args) else None
        if not word:
            print("用法: intent_calibrator.py --apply <word>")
            return 2
        ok, msg = apply_calibration(word)
        print(msg)
        return 0 if ok else 1
    # 默认 --check（dry-run 周期 1 · 只建议不写回）
    cands = analyze()
    print(report(cands))
    if cands:
        # dry-run：输出候选 + 提示 --apply 需达两周期
        n_actionable = sum(1 for c in cands if c["actionable"])
        print(f"ℹ️  可校准 {n_actionable} 个（--apply <word> 显式批准写回）· 其余待连续观察")
    return 0


if __name__ == "__main__":
    sys.exit(main())