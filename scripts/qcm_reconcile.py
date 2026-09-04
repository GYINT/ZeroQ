#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 采样对账（V8.6 P6 · R14 蓝图落地 · 双计/遗漏裁决）

背景（R14 结论：不需要双路冗余 —— 单源 + 兜底 + 对账）：
  采集出口归一化（usage_global）是观测单元，应用层入口归一化（契约）是履约单元。
  双计与遗漏的最终裁判 = 对账，不是多写一份数据。

基准（链 B 已有计数设施 · 非热度语义 · 视为对账基准）：
  - metrics.record_tool_call → qcm_tool_calls_total{tool=...}（会话内工具调用）
  - llm_router.by_provider（内存态 calls/success/fail）

对账逻辑：
  1. 基准汇总：遍历 metrics 计数 + LLM_ROUTER stats → {tool: calls, llm_provider: calls}
  2. 采样侧：usage_global["tool"] + usage_global["llm"]
  3. 裁决：
     - 采样 > 基准（同一次调用被织入+网关双计 / 外部直调只采样不计数）→ 双计提示
     - 基准 > 采样（织入缺失 / 网关绕过，消费未被观测）→ 遗漏提示
     - 相等 → 一致
  4. 退出码：0 = 一致或无显著偏差 · 1 = 检出双计或遗漏（CI/夜巡可门控）

用法：
  python scripts/qcm_reconcile.py [--check|--fix] [--delta N]
    --check  只输出裁决不改数据（默认）
    --fix    检出「遗漏」时自动回填采样（record_usage 补记缺口）
             —— 双计/仅采样只报告不回填（双计需人工核查，勿自动覆盖）
    --delta  偏差阈值（默认 0 = 严格一致）
    --word   附加词热度域对账（R19 · word 域观测闭环）
             —— 基准：usage_stats/hit_stats 词热度事实（R4 消费源）
             —— 采样：usage_global word 域（router 适配器 record_usage("word")）
             —— 裁决：word 域无采样 + 基准确认有热度 → 「未观测」提示
                      采样>基准 → 「双计」（同词多条记录 / 采样超前）
             —— --fix 扩展（R20）：未观测词自动补采样（record_usage 补记 1 次 · 事件级缺口）
"""
import json
import os
import sys
from typing import Dict

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)                              # scripts/
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "core"))  # core/（usage_global）

DELTA_DEFAULT = 0


def _collect_metrics_tools() -> Dict[str, int]:
    """基准①：metrics qcm_tool_calls_total（按 tool 标签聚合）

    注意：标签顺序为 {status=..., tool=...}（metrics.py record_tool_call 定义），
    解析须用 'tool=' 精确剥离，不能按位置假设。
    """
    out: Dict[str, int] = {}
    try:
        from metrics import metrics
        txt = metrics.export()
        for line in txt.splitlines():
            line = line.strip()
            if not line.startswith("qcm_tool_calls_total{"):
                continue
            if line.startswith("#"):
                continue
            # qcm_tool_calls_total{status="ok",tool="qcm_research"} 1.0
            try:
                head, _, val = line.rpartition(" ")
                tool = head.split('tool="', 1)[1].split('"', 1)[0]
                out[tool] = out.get(tool, 0) + int(float(val))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _collect_metrics_llm() -> Dict[str, int]:
    """基准②：metrics qcm_llm_calls_total（按 provider 标签聚合）"""
    out: Dict[str, int] = {}
    try:
        from metrics import metrics
        txt = metrics.export()
        for line in txt.splitlines():
            line = line.strip()
            if not line.startswith("qcm_llm_calls_total{"):
                continue
            if line.startswith("#"):
                continue
            try:
                head, _, val = line.rpartition(" ")
                prov = head.split('provider="', 1)[1].split('"', 1)[0]
                out[prov] = out.get(prov, 0) + int(float(val))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _collect_llm_router() -> Dict[str, int]:
    """基准③：llm_router.by_provider（内存态 · 进程内）"""
    out: Dict[str, int] = {}
    try:
        from llm_router import LLMRouter
        r = LLMRouter()
        for name, st in (r.stats.get("by_provider") or {}).items():
            out[name] = st.get("calls", 0)
    except Exception:
        pass
    return out


def _collect_sampled() -> Dict[str, Dict[str, int]]:
    """采样侧：usage_global 的 tool / llm 域"""
    out: Dict[str, Dict[str, int]] = {}
    try:
        from usage_global import usage_global_stats
        s = usage_global_stats()
        dd = s.get("namespaces_detail", {})
        for ns in ("tool", "llm"):
            out[ns] = {k: v.get("count", 0) for k, v in (dd.get(ns) or {}).items()}
    except Exception:
        pass
    return out


def _collect_word_basis() -> Dict[str, int]:
    """词热度基准：usage_stats（正向命中 total）+ hit_stats（未命中 count）

    语义（域级互斥）：
      - usage_stats 记录「词→意图/领域分布 + total」（record_hit · 观测环正向）
      - hit_stats 记录「未命中词 count」（record_miss · 观测环负向）
      - 两者是**词热度的事实基准**（R4 消费源 · guardian_reverse.load_usage/load_hits）
    输出 {word: total}（命中优先 · 未命中合并为 miss 语义）
    """
    out: Dict[str, int] = {}
    try:
        from hit_tracker import _load_usage, _load
        for w, e in (_load_usage() or {}).items():
            out[w] = out.get(w, 0) + int(e.get("total") or 0)
    except Exception:
        pass
    try:
        from hit_tracker import _load
        for w, e in (_load() or {}).items():
            if isinstance(e, dict):
                out[w] = out.get(w, 0) + int(e.get("count") or 0)
            else:
                out[w] = out.get(w, 0) + int(e or 0)
    except Exception:
        pass
    return out


def _collect_word_sampled() -> Dict[str, int]:
    """采样侧：usage_global word 域"""
    out: Dict[str, int] = {}
    try:
        from usage_global import usage_global_stats
        s = usage_global_stats()
        dd = s.get("namespaces_detail", {})
        out = {k: v.get("count", 0) for k, v in (dd.get("word") or {}).items()}
    except Exception:
        pass
    return out


def reconcile_word(delta: int = DELTA_DEFAULT, fix: bool = False) -> dict:
    """词热度域对账（R19 --word · R20 --fix 扩展）

    基准（词热度事实）↔ 采样（usage_global word 域）：
      - 基准确认有热度（total>0）但 word 域无采样 → 「未观测」提示
        （观测链断点：caller 未走 router 适配器 / 直调语义工具 / 历史遗留）
      - word 域 count > 基准 + delta → 「双计」提示（同词多条记录 / 采样超前）
      - 基准确认无热度但 word 域有记录 → 「仅采样」提示（历史残留 or 观测超前）

    R20 fix 扩展：fix=True 时「未观测」词自动补采样——record_usage("word", w) 补记 1 次。
      语义：确认观测链断点后补记缺口（事件级 · 非补足 total），使 word 域覆盖闭合；
      双计/仅采样只报告（双计需人工核查 · 仅采样可 reset_namespace 清理，勿自动写）。
    Note：word 域语义是「热度观测」而非「调用计数」——基准与采样统计口径
    天然不同（基准=微观词热度 · 采样=聚合使用事实），对账目标是**检测观测断链**
    与**数量级漂移**，不追求逐次相等。故以 0 计数缺失为严重信号，
    数量偏差仅提示（delta 宽松默认 0 但以存在性为主）。
    """
    base = _collect_word_basis()
    sampled = _collect_word_sampled()
    findings = []
    fixed = []  # R20：fix 模式补采样记录
    seen_words = set(base) | set(sampled)

    for w in sorted(seen_words):
        bcnt = base.get(w, 0)
        scnt = sampled.get(w, 0)
        if bcnt > 0 and scnt == 0:
            detail = "词热度事实存在但 usage_global.word 无采样：观测链断点（应走 router 适配器）"
            findings.append({"level": "未观测", "domain": "word", "obj": w,
                             "basis": bcnt, "sampled": 0, "detail": detail})
            if fix:
                try:
                    from usage_global import record_usage
                    record_usage("word", w)  # 补记 1 次（事件级缺口补采）
                    fixed.append({"domain": "word", "obj": w, "backfilled": 1, "reason": "未观测自动补采样"})
                except Exception as e:
                    findings.append({"level": "回填失败", "domain": "word", "obj": w,
                                     "basis": bcnt, "sampled": 0, "detail": f"record_usage 异常: {e}"})
        elif scnt > bcnt + delta and bcnt > 0:
            findings.append({"level": "双计", "domain": "word", "obj": w,
                             "basis": bcnt, "sampled": scnt,
                             "detail": "采样>基准：同词多条记录或采样超前（热度聚合超前）"})
        elif bcnt == 0 and scnt > 0:
            findings.append({"level": "仅采样", "domain": "word", "obj": w,
                             "basis": 0, "sampled": scnt,
                             "detail": "word 域有记录但词热度基准无：历史残留或观测超前（可 reset_namespace 清理）"})

    return {
        "basis_word": base,
        "sampled_word": sampled,
        "findings": findings,
        "fixed": fixed,
        "ok": len(findings) == 0,
    }


def reconcile(delta: int = DELTA_DEFAULT, fix: bool = False) -> dict:
    """执行对账 · 返回裁决报告（fix=True 自动回填遗漏采样）"""
    base_tools = _collect_metrics_tools()
    base_llm = _collect_llm_router()
    sampled = _collect_sampled()

    findings = []
    fixed = []  # fix 模式回填记录

    def _backfill(namespace: str, obj: str, gap: int, reason: str):
        """回填采样：基准>采样 且 fix=True → record_usage 补记 gap 次"""
        if gap <= 0:
            return
        try:
            from usage_global import record_usage
            for _ in range(gap):
                record_usage(namespace, obj)
            fixed.append({"domain": namespace, "obj": obj, "backfilled": gap, "reason": reason})
        except Exception as e:
            findings.append({"level": "回填失败", "domain": namespace, "obj": obj,
                             "basis": 0, "sampled": 0, "detail": f"record_usage 异常: {e}"})

    # ① 工具域：基准(metrics) vs 采样(usage_global.tool)
    for tool, bcnt in sorted(base_tools.items()):
        scnt = sampled["tool"].get(tool, 0)
        if scnt > bcnt + delta:
            findings.append({"level": "双计", "domain": "tool", "obj": tool,
                             "basis": bcnt, "sampled": scnt,
                             "detail": "采样>基准：同一次调用被织入+网关双计，或外部直调只采样不计数"})
        elif bcnt > scnt + delta:
            gap = bcnt - scnt
            findings.append({"level": "遗漏", "domain": "tool", "obj": tool,
                             "basis": bcnt, "sampled": scnt,
                             "detail": f"基准>采样：织入缺失或网关绕过，消费未被观测（缺口 {gap}）"})
            if fix:
                _backfill("tool", tool, gap, "metrics 基准回填")
    for tool, scnt in sorted(sampled["tool"].items()):
        if tool.endswith(":error"):
            continue
        if tool not in base_tools and scnt > delta:
            findings.append({"level": "仅采样", "domain": "tool", "obj": tool,
                             "basis": 0, "sampled": scnt,
                             "detail": "采样侧独有：metrics 未计数（跨进程/无 metrics 环境）"})

    # ② LLM 域：基准(by_provider) vs 采样(usage_global.llm)
    for prov, bcnt in sorted(base_llm.items()):
        scnt = sampled["llm"].get(f"{prov.lower()}:mock", 0) + sampled["llm"].get(f"{prov.lower()}:real", 0)
        if scnt > bcnt + delta:
            findings.append({"level": "双计", "domain": "llm", "obj": prov,
                             "basis": bcnt, "sampled": scnt,
                             "detail": "采样>基准：LLM 调用被重复观测"})
        elif bcnt > scnt + delta:
            gap = bcnt - scnt
            findings.append({"level": "遗漏", "domain": "llm", "obj": prov,
                             "basis": bcnt, "sampled": scnt,
                             "detail": f"基准>采样：LLM 调用未被出口采样（缺口 {gap}）"})
            if fix:
                _backfill("llm", f"{prov.lower()}:real", gap, "by_provider 基准回填")

    return {
        "basis_tools": base_tools,
        "basis_llm": base_llm,
        "sampled_tool": sampled["tool"],
        "sampled_llm": sampled["llm"],
        "findings": findings,
        "fixed": fixed,
        "ok": len(findings) == 0,
    }


def main():
    fix_mode = "--fix" in sys.argv
    word_mode = "--word" in sys.argv
    delta = DELTA_DEFAULT
    if "--delta" in sys.argv:
        try:
            delta = int(sys.argv[sys.argv.index("--delta") + 1])
        except Exception:
            pass

    rep = reconcile(delta, fix=fix_mode)
    mode = "fix(自动回填)" if fix_mode else "check"
    print(f"QCM 采样对账（{mode} · delta={delta}）")
    print(f"  基准 tools(metrics): {rep['basis_tools'] or '∅'}")
    print(f"  基准 llm(by_provider): {rep['basis_llm'] or '∅'}")
    print(f"  采样 tool(usage_global): {rep['sampled_tool'] or '∅'}")
    print(f"  采样 llm(usage_global): {rep['sampled_llm'] or '∅'}")
    if not rep["findings"]:
        print("  ✅ 一致：无双计 · 无遗漏")
    else:
        for f in rep["findings"]:
            print(f"  ⚠️ [{f['level']}] {f['domain']}/{f['obj']}: "
                  f"基准={f['basis']} 采样={f['sampled']} — {f['detail']}")
    if rep["fixed"]:
        print(f"  🔧 已回填 {len(rep['fixed'])} 条遗漏采样：")
        for fx in rep["fixed"]:
            print(f"    · {fx['domain']}/{fx['obj']} += {fx['backfilled']}（{fx['reason']}）")

    # R19+R20：词热度域附加对账（--word · fix 透传自动补采样）
    if word_mode:
        wrep = reconcile_word(delta, fix=fix_mode)
        print(f"  基准 word(usage_stats/hit_stats): {wrep['basis_word'] or '∅'}")
        print(f"  采样 word(usage_global): {wrep['sampled_word'] or '∅'}")
        if not wrep["findings"]:
            print("  ✅ word 域一致：热度观测闭环无断点")
        else:
            for f in wrep["findings"]:
                print(f"  ⚠️ [{f['level']}] {f['domain']}/{f['obj']}: "
                      f"基准={f['basis']} 采样={f['sampled']} — {f['detail']}")
        if wrep["fixed"]:
            print(f"  🔧 word 域已补采样 {len(wrep['fixed'])} 条（未观测自动补记）：")
            for fx in wrep["fixed"]:
                print(f"    · {fx['domain']}/{fx['obj']} += {fx['backfilled']}（{fx['reason']}）")
        rep = {**rep, "ok": rep["ok"] and wrep["ok"], "fixed": rep.get("fixed", []) + wrep["fixed"]}

    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())