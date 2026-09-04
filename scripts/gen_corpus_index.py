#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 大语料索引生成器（P2-8 懒加载支撑 · V8.6 自适应分类 + 自动检入）

扫描大语料文件（>threshold_kb），为每个生成锚点索引 yaml：
  references/index/<name>.index.yaml

V8.6 升级（自适应分类 + 自动检入）：
  - 单一真源 corpus_manifest.yaml（scripts/corpus_manifest.py 共享消费）
  - 自动发现：scan_corpus() 遍历 references/**/*.md，找出 >阈值 且未登记的大文件
  - 自适应分类：classify() 按路径启发式判定 corpus / excluded（未知→默认 excluded 失败安全）
  - 自动检入：auto_checkin() 生成索引 + 写回 manifest（corpus/excluded）
  - 漂移检测：--check 升级为检查「新大文件无索引 / 源删索引残留 / 源更新未重生」

用法：
  python3 scripts/gen_corpus_index.py                 # 全量重生成（manifest 全部 corpus+excluded）
  python3 scripts/gen_corpus_index.py --check         # 漂移检测（新鲜度 + EXCLUDE 合规 + 未登记大文件）
  python3 scripts/gen_corpus_index.py --scan          # 自适应扫描 + 分类（dry-run 报告，不写回）
  python3 scripts/gen_corpus_index.py --scan --auto   # 自动检入（生成索引 + 写回 manifest）
"""
import os
import re
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "references" / "index"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

from corpus_manifest import load_manifest, MANIFEST, THRESHOLD_KB

HEADING = re.compile(r"^(#{1,4})\s+(.+)$")
TAGLINE = re.compile(r"^\s*<!--\s*tags:\s*(.+?)\s*-->\s*$")
# 稳定 id 元信息行（编号免疫的交叉引用锚）：<!-- id: case-xxx; tags: a, b, c -->
METALINE = re.compile(r"^\s*<!--\s*id:\s*([A-Za-z0-9_\-]+)\s*;\s*tags:\s*(.+?)\s*-->\s*$")
# 反向索引 token：章节自引用 §N（如 §八）· 工具锚点 ##D26 / ##A01
SELFREF = re.compile(r"§[一二三四五六七八九十]{1,3}")
TOOLREF = re.compile(r"##[A-Za-z]\d{2}")


def gen_index(rel: str, note: str) -> Path:
    """为单个大语料文件生成锚点索引 yaml（手写 yaml · 避免 PyYAML 依赖）。"""
    src = ROOT / rel
    if not src.exists():
        print(f"⚠ 跳过（不存在）: {rel}")
        return None
    lines = src.read_text(encoding="utf-8", errors="ignore").splitlines()
    heads = []  # (line_no_0based, level, title)
    for i, ln in enumerate(lines):
        m = HEADING.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    if not heads:
        print(f"⚠ 无标题结构: {rel}")
        return None
    anchors = []
    for idx, (i, lvl, title) in enumerate(heads):
        end = len(lines)
        for j in range(idx + 1, len(heads)):
            if heads[j][1] <= lvl:
                end = heads[j][0]
                break
        tags, anchor_id = [], ""
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        mm = METALINE.match(nxt)
        if mm:
            anchor_id = mm.group(1)
            tags = [t.strip() for t in re.split(r"[,，、;；]", mm.group(2)) if t.strip()]
        else:
            mt = TAGLINE.match(nxt)
            if mt:
                tags = [t.strip() for t in re.split(r"[,，、;；]", mt.group(1)) if t.strip()]
        # 反向索引：扫描本节正文（含子标题）中的 §N 自引用与 ##XNN 工具锚点
        links = []
        for bl in lines[i + 1:end]:
            for tok in SELFREF.findall(bl) + TOOLREF.findall(bl):
                if tok not in links:
                    links.append(tok)
        anchors.append({
            "title": title, "level": lvl,
            "line": i + 1, "end_line": end, "lines": end - i,
            "id": anchor_id, "tags": tags, "links": links,
        })
    data = {
        "file": rel, "note": note,
        "size_bytes": src.stat().st_size,
        "size_kb": round(src.stat().st_size / 1024, 1),
        "anchor_count": len(anchors),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "anchors": anchors,
    }
    out = INDEX_DIR / (src.stem + ".index.yaml")
    buf = [f"# QCM 大语料索引（自动生成 · 勿手改）", f"file: {rel}",
           f"note: {note}", f"size_bytes: {data['size_bytes']}",
           f"size_kb: {data['size_kb']}", f"anchor_count: {data['anchor_count']}",
           f"generated: {data['generated']}", "anchors:"]
    for a in anchors:
        tag_str = ", ".join(a.get("tags", []))
        id_str = a.get("id", "") or "-"
        link_str = ", ".join(a.get("links", []))
        buf.append(f"  - {{id: {id_str}, title: {_yaml_str(a['title'])}, level: {a['level']}, "
                   f"line: {a['line']}, end_line: {a['end_line']}, lines: {a['lines']}, "
                   f"tags: [{tag_str}], links: [{link_str}]}}")
    out.write_text("\n".join(buf) + "\n", encoding="utf-8")
    print(f"✅ {rel} → {out.relative_to(ROOT)}（{len(anchors)} 锚点 · {data['size_kb']}KB）")
    return out


def _yaml_str(s: str) -> str:
    s = s.replace('"', "'").replace("{", "（").replace("}", "）").replace(":", "：")
    return s


def _derive_note(rel: str, cls: str) -> str:
    name = rel.split("/")[-1].rsplit(".", 1)[0]
    if cls == "corpus":
        return f"{name}（自适应分类→corpus · 自动检入）"
    return f"{name}（自适应分类→excluded · 仅索引使用）"


def scan_corpus():
    """自动发现：遍历 references/**/*.md，返回未登记且 >阈值 的大文件清单（已分类）。"""
    m = load_manifest()
    known = {e["rel"] for e in (m.get("corpus", []) + m.get("excluded", []))}
    thresh = int(m.get("threshold_kb", THRESHOLD_KB)) * 1024
    cands = []
    for p in (ROOT / "references").rglob("*.md"):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if "references/index/" in rel or "automation_log" in rel:
            continue
        if p.stat().st_size <= thresh:
            continue
        if rel in known:
            continue
        cls, level, group, freq = classify(rel)
        cands.append((rel, cls, level, group, freq))
    return cands


def classify(rel: str):
    """自适应分类（路径启发式）：返回 (cls, level, group, freq)。

    规则：testing→excluded · tools/knowledge/scenarios/protocol/industry→corpus（level/group 由目录派生）
          未知/歧义 → 默认 excluded（失败安全，绝不自动提升为全量语料）
    """
    if "/testing/" in rel:
        return ("excluded", "index", "测试族", "low")
    if "/tools/" in rel:
        return ("corpus", "kw", "工具族", "low")
    if "/knowledge/" in rel:
        return ("corpus", "chapter", "知识族", "low")
    if "/scenarios/" in rel:
        return ("corpus", "chapter", "知识族", "low")
    if "/protocol/" in rel:
        return ("corpus", "chapter", "协议族", "high")
    if "/industry/" in rel:
        return ("corpus", "chapter", "行业族", "low")
    # C5（2026-09-02）：sources 内分层——event 原始证据需检索，蒸馏资料仍 excluded。
    # 精确前缀优先：/sources/events/ 命中→corpus；其余 /sources/* 落到末行 excluded（蒸馏）。
    if "/sources/events/" in rel:
        return ("corpus", "chapter", "事件证据族", "low")
    # 失败安全：未知路径默认排除（仅索引），避免新大文件被整文件读入上下文
    return ("excluded", "index", "未分类(默认排除)", "low")


def auto_checkin(dry_run: bool = True) -> int:
    """自动检入：发现未登记大文件 → 分类 → 生成索引 + 写回 manifest。

    dry_run=True：仅报告，不写回 manifest（夜巡/默认安全）。
    dry_run=False（--scan --auto）：生成索引并写回 corpus_manifest.yaml。
    """
    cands = scan_corpus()
    if not cands:
        print("✅ 无新大文件需检入（全部已登记 · 语料自洽）")
        return 0
    m = load_manifest()
    corpus = list(m.get("corpus", []))
    excluded = list(m.get("excluded", []))
    added = 0
    for rel, cls, level, group, freq in cands:
        note = _derive_note(rel, cls)
        gen_index(rel, note)
        if cls == "corpus":
            corpus.append({"rel": rel, "level": level, "group": group, "freq": freq, "note": note})
        else:
            excluded.append({"rel": rel, "note": note,
                             "reason": "自适应分类：测试资产/未分类 → 默认 excluded（失败安全）"})
        added += 1
        print(f"  {'[dry] ' if dry_run else ''}检入 {cls}: {rel} (level={level}, group={group})")
    if not dry_run:
        m["corpus"] = corpus
        m["excluded"] = excluded
        _dump_manifest(m)
        print(f"✅ 已写入 {MANIFEST.relative_to(ROOT)}（+{added} 项）")
    else:
        print(f"  (dry-run：未写回 manifest；实际执行需 --scan --auto)")
    return added


def _dump_manifest(m: dict) -> None:
    """手写 manifest（保留 header 注释 + 内联条目风格，与 skill 其余配置一致）。"""
    lines = [
        "# QCM 大语料清单单一真源（V8.6 · 自适应分类 + 自动检入）",
        "# 由 scripts/gen_corpus_index.py --scan --auto 自动维护；手工可调 note/reason，勿删条目。",
        f"threshold_kb: {m.get('threshold_kb', THRESHOLD_KB)}",
        "corpus:",
    ]
    for e in m.get("corpus", []):
        lines.append(f"  - {{rel: {e['rel']}, level: {e.get('level','chapter')}, "
                     f"group: {e.get('group','?')}, freq: {e.get('freq','low')}, note: \"{_yaml_str(e.get('note',''))}\"}}")
    lines.append("excluded:")
    for e in m.get("excluded", []):
        line = f"  - {{rel: {e['rel']}, note: \"{_yaml_str(e.get('note',''))}\""
        if e.get("reason"):
            line += f", reason: \"{_yaml_str(e['reason'])}\"}}"
        else:
            line += "}"
        lines.append(line)
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_freshness(m: dict) -> int:
    """已登记项索引新鲜度（源 mtime ≤ 索引 mtime）。"""
    stale = 0
    for e in (m.get("corpus", []) + m.get("excluded", [])):
        rel = e["rel"]
        src = ROOT / rel
        idx = INDEX_DIR / (src.stem + ".index.yaml")
        if not src.exists():
            print(f"⚠ 漂移：登记源已删 {rel}"); stale += 1; continue
        if not idx.exists():
            print(f"⚠ 漂移：缺索引 {rel}"); stale += 1; continue
        if idx.stat().st_mtime < src.stat().st_mtime:
            print(f"⚠ 漂移：索引过期（源文件更新）: {rel}"); stale += 1
    return stale


def check_excluded(m: dict) -> int:
    """EXCLUDE 合规：排除项必须已生成新鲜索引且未被误标为 corpus。"""
    corpus_rels = {e["rel"] for e in m.get("corpus", [])}
    problems = 0
    for e in m.get("excluded", []):
        rel = e["rel"]
        if rel in corpus_rels:
            print(f"⚠ 排除冲突：{rel} 同时出现在 corpus（应移除）"); problems += 1; continue
        src = ROOT / rel
        idx = INDEX_DIR / (src.stem + ".index.yaml")
        if not idx.exists():
            print(f"⚠ 排除文件缺索引（须生成）: {rel}"); problems += 1
        elif idx.stat().st_mtime < src.stat().st_mtime:
            print(f"⚠ 排除文件索引过期: {rel}"); problems += 1
    return problems


def check_drift(m: dict) -> int:
    """漂移检测：发现未登记的大文件（>阈值且不在 manifest）。"""
    known = {e["rel"] for e in (m.get("corpus", []) + m.get("excluded", []))}
    thresh = int(m.get("threshold_kb", THRESHOLD_KB)) * 1024
    problems = 0
    for p in (ROOT / "references").rglob("*.md"):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if "references/index/" in rel or "automation_log" in rel:
            continue
        if p.stat().st_size <= thresh:
            continue
        if rel not in known:
            print(f"⚠ 漂移：未登记大文件 {rel}（须 --scan --auto 自动检入）"); problems += 1
    return problems


def main():
    if "--scan" in sys.argv:
        dry = "--auto" not in sys.argv
        print("=== 自适应扫描（scan_corpus + classify）===")
        if dry:
            print("  (dry-run 模式 · 仅报告，不写回 manifest)")
        added = auto_checkin(dry_run=dry)
        return 0 if added is not None else 0
    if "--check" in sys.argv:
        m = load_manifest()
        stale = check_freshness(m) + check_excluded(m) + check_drift(m)
        if stale == 0:
            print("✅ 语料索引全部自洽（新鲜 + EXCLUDE 合规 + 无未登记大文件）")
        return 1 if stale else 0
    # 默认：全量重生成（manifest 全部 corpus + excluded）
    m = load_manifest()
    for e in m.get("corpus", []):
        gen_index(e["rel"], e.get("note", ""))
    for e in m.get("excluded", []):
        out = gen_index(e["rel"], e.get("note", ""))
        if out:
            print(f"   ↳ EXCLUDE(index-only): {e['rel']}")
    print(f"\n索引目录: {INDEX_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
