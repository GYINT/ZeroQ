#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 意图表派生生成器（A+B 落地 V8.7 · B-2 治本）

意图表（references/governance/naming-convention.md §意图类）由代码真源派生，
杜绝「二次定义漂移」（历史：文档 5 类·⑤蒸馏扩展 vs 真源 6 类·⑤知识沉淀 静默漂移）。

真源：
  - 意图全集：core/ambiguity_resolver.py 的 INTENTS（6 类）
  - 形态映射：core/router.py 的 FORM_MAP（意图 → 输出形态）

功能：
  - 默认：重写 naming-convention.md 中 GEN-INTENT-TABLE 标记块为真源派生内容
  - --check：断言真源一致（不改写）· 供 g025 扩展复用（漂移即非零退出）

用法：
  python3 scripts/gen_intent_table.py          # 重写意图表块（对齐真源）
  python3 scripts/gen_intent_table.py --check  # 只校验（漂移 → 退出码 1）
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BEG = "<!-- GEN-INTENT-TABLE:BEGIN -->"
END = "<!-- GEN-INTENT-TABLE:END -->"
NAMING = ROOT / "references" / "governance" / "naming-convention.md"


def _load_intents() -> tuple:
    """从 ambiguity_resolver.INTENTS 读 6 类意图（真源）。"""
    sys.path.insert(0, str(ROOT / "core"))
    from ambiguity_resolver import INTENTS
    return INTENTS


def _load_form_map() -> dict:
    """从 router.FORM_MAP 读意图→形态映射（真源）。"""
    sys.path.insert(0, str(ROOT / "core"))
    sys.path.insert(0, str(ROOT / "scripts"))
    from router import FORM_MAP
    return FORM_MAP


def _gen_block(intents: tuple, form_map: dict) -> str:
    """生成意图表核心块（仅 BEG~END · 供 check 断言）。"""
    joined = " / ".join(intents)
    return "\n".join([BEG, joined, END])


def _gen_annotation(intents: tuple, form_map: dict) -> str:
    """生成形态映射注释行（附随块后 · 供人工速览 · 非不变量）。"""
    forms = " · ".join(f"{i}→{form_map.get(i, '?')}" for i in intents)
    return f"> 形态映射（派生 · {forms}）"


def _current_block(text: str) -> str:
    m = re.search(re.escape(BEG) + r"(.*?)" + re.escape(END), text, re.S)
    return m.group(0) if m else ""


def sync() -> bool:
    """重写意图表块 + 形态注释（对齐真源）· 返回是否发生变化。"""
    intents = _load_intents()
    form_map = _load_form_map()
    new_block = _gen_block(intents, form_map)
    annotation = _gen_annotation(intents, form_map)
    text = NAMING.read_text(encoding="utf-8")
    old_block = _current_block(text)
    if old_block:
        text = text.replace(old_block, new_block)
        # 清理紧随块后的旧注解行（含历史残留重复行）
        idx = text.find(new_block) + len(new_block)
        rest = text[idx:]
        while rest.startswith("\n> 形态映射（派生 ·"):
            nxt = rest.find("\n", 1)
            if nxt < 0:
                nxt = len(rest)
            rest = rest[nxt:]
        text = text[:idx] + "\n" + annotation + rest
    else:
        # 无标记块：在「### 意图 6 类」小节后插入
        anchor = re.search(r"^### 意图 .*类.*$", text, re.M)
        if not anchor:
            print("⚠ naming-convention.md 未找到意图小节（无法标记插入）")
            return False
        text = text[:anchor.end()] + "\n\n" + new_block + "\n" + annotation + "\n" + text[anchor.end():]
    NAMING.write_text(text, encoding="utf-8")
    return new_block != old_block


def check() -> bool:
    """断言 naming-convention 意图表 == router INTENTS（漂移 → False）。"""
    intents = _load_intents()
    expect = _gen_block(intents, {})  # 核心块不含形态注释（纯不变量）
    text = NAMING.read_text(encoding="utf-8")
    cur = _current_block(text)
    ok = (cur == expect)
    if not ok:
        print("❌ 意图表漂移：naming-convention.md 与真源 INTENTS 不一致，请运行 gen_intent_table.py 重写")
        print(f"   当前块: {cur[:120]!r}")
        print(f"   期望块: {expect[:120]!r}")
    return ok


def main():
    args = sys.argv[1:]
    if "--check" in args:
        sys.exit(0 if check() else 1)
    changed = sync()
    print("意图表已对齐真源（6 类）" + (" · 块已更新" if changed else " · 无变化"))
    sys.exit(0)


if __name__ == "__main__":
    main()