#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qcm_ref_query.py — R-2 引用图查询器（R-1 ref_graph.json 的 CLI 消费方）

输入：outputs/.runtime/ref_graph.json（由 corpus_cache.py --ref-graph / build 生成）
查询：
  --orphan       入度=0 且非白名单 的疑似孤儿节点（供 R4R 资产退休候选扫描）
  --indegree N   入度 ≥ N 的高被引节点（核心资产识别）
  --chain stem   输出 stem 的出链路径（引用传播链）
  --dangling     列出悬空引用（引用目标不存在）
  --whitelist    追加白名单（stem 逗号分隔；孤儿查询时豁免，report-only 不写回）

用法：
  python qcm_ref_query.py --orphan
  python qcm_ref_query.py --indegree 5
  python qcm_ref_query.py --chain action-orders
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH = ROOT / "outputs" / ".runtime" / "ref_graph.json"

# 内置白名单：非语料运行态/构建产物/仓库元文档/行业包（不参与退休扫描，非断链）
DEFAULT_WHITELIST = {
    # 仓库元文档（repo 级，刻意不互链）
    "README", "SKILL", "CHANGELOG", "INSTALL", "TROUBLESHOOTING",
    # 治理白名单（资产退休环已纳入）
    "asset-lifecycle",
    # 行业包（由 g016 industry 注册表独立治理，非 corpus_manifest）
    "consumer_electronics", "new_energy",
    # outputs/ / docs/ 生成物（评估/执行报告/草稿，非语料）
    "assessment-report", "case-application", "decision-card", "eval", "quick-response",
    # 独立资产 / 运维手册 / 退役编目（刻意低入链，豁免退休扫描 · 2026-09-02 巡检后显式登记）
    "INDEX",                 # archive/ 退役资产编目（裸 stem 经 ref_graph 命名泄漏为孤儿）
    "TIMER-RUNBOOK",         # docs/ 运维手册（仍启用，README 引用；docs 根非 refs 故 edge 不计入）
    "MSA", "Tolerance",                  # references/sources/ 蒸馏源独立资产（已登记 corpus_manifest）
    "intent-glossary",       # 被 3 处文档引用的意图词典（refs 根的带路径引用被 edge 扫描跳过，故天然孤儿）
    "归档台账",              # outputs/ 交付物归档台账（meta 索引，按设计低入链）
}


def _load() -> dict:
    if not GRAPH.exists():
        print(f"❌ ref_graph.json 不存在：{GRAPH}（先运行 corpus_cache.py --ref-graph）", file=sys.stderr)
        sys.exit(1)
    return json.loads(GRAPH.read_text(encoding="utf-8"))


def _orphan(d: dict, whitelist: set):
    nodes = set(d.get("nodes", []))
    incoming = d.get("incoming", {})
    wl = whitelist | DEFAULT_WHITELIST
    # 入度=0：incoming 无该 key 或 空列表（ref_graph 生成时为全部节点初始化占位）
    orphans = [n for n in sorted(nodes)
               if not incoming.get(n) and n not in wl]
    # 排除运行态报告（outputs/ 下的 QCM-*.md 评估/执行报告：非语料，不参与退休扫描）
    orphans = [n for n in orphans if not n.startswith("QCM-")]
    # 排除构建草稿（components/ 下 _ 前缀片段，非 markdown 链接目标）
    orphans = [n for n in orphans if not n.startswith("_")]
    print(f"疑似孤儿（入度=0 · 非白名单 · 排除 QCM- 运行态/构建草稿/仓库元文档/行业包）{len(orphans)} 个:")
    for o in orphans:
        print(f"  {o}.md")
    return orphans


def _indegree(d: dict, n: int):
    incoming = d.get("incoming", {})
    rows = [(k, len(v)) for k, v in incoming.items() if len(v) >= n]
    rows.sort(key=lambda x: -x[1])
    print(f"入度 ≥ {n} 的高被引节点 {len(rows)} 个:")
    for k, c in rows[:20]:
        print(f"  {k}.md  ← {c}")
    return rows


def _chain(d: dict, stem: str):
    outgoing = d.get("outgoing", {})
    nodes = set(d.get("nodes", []))
    if stem not in nodes:
        print(f"❌ 节点不存在: {stem}.md（可用 --indegree 查看全部节点）", file=sys.stderr)
        sys.exit(1)
    print(f"{stem}.md 出链（引用传播）:")
    seen = set()
    stack = [(stem, 0)]
    while stack:
        cur, depth = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        print(f"  {'  ' * depth}→ {cur}.md")
        for nxt in sorted(outgoing.get(cur, [])):
            if nxt not in seen:
                stack.append((nxt, depth + 1))
    return sorted(seen)


def _dangling(d: dict):
    dangling = d.get("dangling", {})
    print(f"悬空引用 {sum(len(v) for v in dangling.values())} 条（{len(dangling)} 个缺失目标）:")
    for k, v in sorted(dangling.items()):
        print(f"  {k}.md ← {sorted(set(v))}")
    return dangling


def main():
    ap = argparse.ArgumentParser(description="QCM 引用图查询（R-2）")
    ap.add_argument("--orphan", action="store_true", help="疑似孤儿（入度=0 非白名单）")
    ap.add_argument("--indegree", type=int, metavar="N", help="入度 ≥ N 高被引节点")
    ap.add_argument("--chain", metavar="stem", help="某节点的出链传播链")
    ap.add_argument("--dangling", action="store_true", help="悬空引用列表")
    ap.add_argument("--whitelist", default="", help="逗号分隔白名单（孤儿查询豁免）")
    args = ap.parse_args()

    d = _load()
    whitelist = {w.strip() for w in args.whitelist.split(",") if w.strip()}
    if args.orphan:
        _orphan(d, whitelist)
    if args.indegree:
        _indegree(d, args.indegree)
    if args.chain:
        _chain(d, args.chain)
    if args.dangling:
        _dangling(d)
    if not any([args.orphan, args.indegree, args.chain, args.dangling]):
        st = d.get("stats", {})
        print(f"引用图统计: nodes={st.get('nodes')} refs={st.get('references')} "
              f"dangling={st.get('dangling')} · 生成于 {d.get('generated_at')}")
        print("用法: --orphan | --indegree N | --chain stem | --dangling")


if __name__ == "__main__":
    main()