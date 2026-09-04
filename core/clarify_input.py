#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 输入引导生成器（M2 · 消费 need_clarify 信号 · 复用 prompts 机制，不复用 5Why）

功能：当路由置信度低于自适应门槛（need_clarify）或 MDS 最小必要集缺失时，
      生成结构化澄清问句（F1-F4 基础字段 + 意图针对性提示），将悬空信号转为可行动引导。
设计：与 scripts/prompts.py 的 qcm_clarify_input 模板同源（同一模板注册表）；
      本模块为引擎侧轻量封装，无 prompts 模块依赖时回退内置模板（防御性降级）。
"""
from typing import Dict, Optional

# 最小必要信息集（MDS F1-F4 基础字段 · 对齐 input-handbook.md §1.1）
BASE_FIELDS = {
    "F1": "场景描述（实战问题/危机现象）",
    "F2": "涉及范围（行业/工艺/危机类型）",
    "F3": "影响对象（客户端/内部/供应链）",
    "F4": "期望产出（决策/案例/评估/快响）",
}

# 意图针对性提示（复用 mds-input.md 场景路由语义）
INTENT_HINTS = {
    "①危机处置": "请优先给出危机等级（F24：微型/普通/中度/重度）与时效要求，便于 24h 围堵路由。",
    "②流程优化": "请说明待改善指标与当前基线，便于定位改善工具。",
    "③评估审计": "请明确评估对象与验收标准，便于给出审计框架。",
    "④知识学习": "请描述想了解的概念/标准，便于精准检索。",
    "⑤知识沉淀": "请说明待沉淀的方法/案例来源，便于蒸馏挂载。",
    "⑥质量文化": "请描述文化/组织现状，便于成熟度评估。",
}


def generate_clarify(route_result: Dict, mds: Optional[dict] = None) -> str:
    """生成澄清引导文本（F1-F4 最小必要集 + 意图针对性提示）

    Args:
        route_result: 含 intent/domain 的路由结果（或等价 dict）
        mds: 可选 MDS 输入（含已填字段，用于跳过已提供项）
    Returns:
        多行澄清提示文本
    """
    intent = route_result.get("intent", "") if isinstance(route_result, dict) else ""
    filled = set()
    if isinstance(mds, dict):
        for k in mds:
            if str(k).upper().startswith("F"):
                filled.add(str(k).upper())
    lines = ["为精准路由到【%s】，请补充最小必要信息：" % intent]
    for fid, desc in BASE_FIELDS.items():
        mark = "（已提供）" if fid in filled else ""
        lines.append("  · %s %s%s" % (fid, desc, mark))
    hint = INTENT_HINTS.get(intent)
    if hint:
        lines.append("")
        lines.append(hint)
    return "\n".join(lines)
