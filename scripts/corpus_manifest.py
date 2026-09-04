#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 大语料清单单一真源（V8.6 · 自适应分类 + 自动检入）

被 gen_corpus_index / corpus_loader / guardian 共享消费。
由 `python3 scripts/gen_corpus_index.py --scan --auto` 自动维护（新增大文件自动检入）；
手工微调可编辑本文件 note/reason 字段，勿删 corpus/excluded 条目（除非对应源文件已删）。

字段：
  threshold_kb : 触发索引/分类的体积阈值（KB）
  corpus       : 运行语料（经懒加载全文/章节/关键词级读取）
  excluded     : 排除全量输入的语料（仅经索引锚点按需检索，绝不整体读入上下文）
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "references" / "config" / "corpus_manifest.yaml"
THRESHOLD_KB = 30

# 兜底（manifest 缺失时 · 与历史硬编码 CORPUS/EXCLUDE 对齐 · 保证向后兼容）
_FALLBACK = {
    "threshold_kb": 30,
    "corpus": [
        {"rel": "references/tools/tools.md", "level": "kw", "group": "工具族", "freq": "low",
         "note": "工具库（SPC/防错/8D 等 90+ 工具实例）"},
        {"rel": "references/knowledge/knowledge-base.md", "level": "chapter", "group": "知识族", "freq": "low",
         "note": "知识库（案例集/外部素材）"},
        {"rel": "references/tools/masters.md", "level": "chapter", "group": "知识族", "freq": "low",
         "note": "大师库（21 位质量大师心智模型）"},
        {"rel": "references/scenarios/cases.md", "level": "chapter", "group": "知识族", "freq": "low",
         "note": "案例库（双归零/行业案例）"},
        {"rel": "references/protocol/action-orders.md", "level": "chapter", "group": "协议族", "freq": "high",
         "note": "协议章（AO-1~AO-4/5 段式/危机协议/§14 路由协议 · 按章懒加载）"},
    ],
    "excluded": [
        {"rel": "references/testing/test-cases.md", "note": "测试案例库（>30KB）",
         "reason": "测试资产·非运行语料·仅经索引锚点按需检索·不走全量懒加载"},
    ],
}


def load_manifest() -> dict:
    """加载语料清单（manifest 优先，缺失回退兜底）。返回 {threshold_kb, corpus[], excluded[]}。"""
    if MANIFEST.exists():
        try:
            d = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
            if isinstance(d, dict) and (d.get("corpus") or d.get("excluded")):
                d.setdefault("threshold_kb", THRESHOLD_KB)
                return d
        except Exception:
            pass
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _FALLBACK.items()}


def all_rels() -> set:
    m = load_manifest()
    return {e["rel"] for e in (m.get("corpus", []) + m.get("excluded", []))}


def corpus_rels() -> dict:
    """stem → rel（仅 corpus 段，供懒加载全文读取）"""
    m = load_manifest()
    return {e["rel"].split("/")[-1].rsplit(".", 1)[0]: e["rel"] for e in m.get("corpus", [])}


def excluded_stems() -> set:
    m = load_manifest()
    return {e["rel"].split("/")[-1].rsplit(".", 1)[0] for e in m.get("excluded", [])}


def full_rels() -> dict:
    """stem → rel（corpus + excluded 合并，供 load_section/list_anchors 按需检索）"""
    m = load_manifest()
    d = {}
    for sec in ("corpus", "excluded"):
        for e in m.get(sec, []):
            stem = e["rel"].split("/")[-1].rsplit(".", 1)[0]
            d[stem] = e["rel"]
    return d
