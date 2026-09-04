#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asset_retirement.py — R4R 资产退休环（R-3/R-5/R-7 · 遗留资产动态管理）

三源扫描候选：
  S1 孤儿     ：ref_graph 入度=0 且非 whitelist（ref_graph.json 由 corpus_cache 生成）
  S2 悬空     ：dangling 引用目标不存在（引用方指向缺失文件 → 引用断裂候选）
  S3 废弃     ：DEPRECATED 头（g020b 已校验模板 · 此处登记观察）

生命周期状态机：new → observing(30d) → retire_candidate →（人工）retired / revived / whitelisted
  retiring    ：仅观察期满 30 天 + 人工核准（--retire）才 mv 到 archive/（规范根归档·与 g029/inventory.py 同目录）
  物理清理    ：每 1 个季度（QCM_RETIRE_CYCLE_DAYS 默认 90）执行一次 mv（用户已确认周期）

用法：
  python asset_retirement.py --scan            # 三源扫描 → 登记/更新状态机（report 为主）
  python asset_retirement.py --list            # 列出当前候选与状态
  python asset_retirement.py --retire stem     # 人工核准：mv 到 archive/（规范根归档 · 季度窗口内）
  python asset_retirement.py --revive stem     # 人工决策：摘除候选举（保留原样）
  python asset_retirement.py --whitelist stem  # 永久豁免（写入 whitelist）
  python asset_retirement.py --status          # 状态机摘要 + 本季度物理清理窗口
"""
import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF_DIR = ROOT / "references"
# #62-B 修正：规范归档目录 = 项目根 archive/（与 archive/inventory.py、g029 守卫同一目录）。
#   原 REF_DIR/"archive"（references/archive/）是 M0.4 设计预留路径，但规范归档最终落在根 archive/，
#   导致 R4R 退休文件与 g029 漂移扫描/INDEX 编目"各看各的"——本次纠正结构性错配。
ARCHIVE_DIR = ROOT / "archive"
INDEX = ARCHIVE_DIR / "INDEX.md"              # #62-B：退役资产编目真源（R4R↔INDEX 闭环目标）
STATE_FILE = ROOT / "references" / "config" / "asset_retirement.json"
GRAPH_FILE = ROOT / "outputs" / ".runtime" / "ref_graph.json"
RETIRE_CYCLE_DAYS = int(__import__("os").environ.get("QCM_RETIRE_CYCLE_DAYS", 90))
OBSERVE_DAYS = 30

# 豁免：索引/知识库总纲/运行时报告/治理规范（不参与退休扫描）
ALWAYS_WHITELIST = {"knowledge-base", "action-orders", "index", "README",
                    "asset-lifecycle"}  # asset-lifecycle=废弃模板规范文档（正文含示例 DEPRECATED 头，非废弃资产）


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"whitelist": list(ALWAYS_WHITELIST), "observe": {}, "retired": {}}


def _save(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_graph() -> dict:
    if not GRAPH_FILE.exists():
        return {"nodes": [], "incoming": {}, "dangling": {}}
    try:
        return json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"nodes": [], "incoming": {}, "dangling": {}}


def scan() -> dict:
    """三源扫描 → 候选清单（不写状态，仅报告；status 推进由 --scan 的 observe 阶段做）。"""
    g = _load_graph()
    state = _load_state()
    whitelist = set(state.get("whitelist", [])) | ALWAYS_WHITELIST   # 动态并入常驻豁免
    nodes = set(g.get("nodes", []))
    incoming = g.get("incoming", {})
    dangling = g.get("dangling", {})

    # S1 孤儿：入度=0（incoming 为空列表或 key 缺失）且排除 QCM- 运行态报告（非语料）
    orphans = sorted(n for n in nodes
                     if not incoming.get(n) and
                     not n.startswith("QCM-") and n not in whitelist)
    # S2 悬空：dangling 缺失目标（这些是无法解析的引用）
    dangling_targets = sorted(dangling.keys())
    # S3 废弃：DEPRECATED 头文件（从 references 内识别 · 与 g020b 同判定：⚠️/—/STUB 明确废弃语义）
    deprecated = []
    for f in sorted(REF_DIR.rglob("*.md")):
        rel = f.relative_to(REF_DIR)
        if any(p in ("index", ".runtime", "archive") for p in rel.parts):
            continue
        try:
            head = f.read_text(encoding="utf-8")[:800]
            if re.search(r"⚠️\s*DEPRECATED|DEPRECATED\s*[—-]|DEPRECATED\s+STUB", head) \
                    and f.stem not in whitelist:
                deprecated.append(f.stem)
        except Exception:
            pass

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "orphan": orphans,
        "dangling": dangling_targets,
        "deprecated": sorted(set(deprecated)),
        "retire_cycle_days": RETIRE_CYCLE_DAYS,
    }
    return result


def observe(result: dict) -> dict:
    """观察期推进：候选登记 observe 状态机，30d 内不动作（R-5）。"""
    state = _load_state()
    observe = dict(state.get("observe", {}))
    today = datetime.now().date().isoformat()
    merge = {}
    for src in ("orphan", "dangling", "deprecated"):
        for stem in result.get(src, []):
            if stem in state.get("retired", {}) or stem in state.get("whitelist", []):
                continue
            key = f"{stem}|{src}"
            rec = observe.get(key)
            if rec is None:
                observe[key] = {"stem": stem, "source": src,
                                "since": today, "review_due":
                                    (datetime.now().date() + timedelta(days=OBSERVE_DAYS)).isoformat(),
                                "status": "observing"}
            elif rec.get("status") == "observing" and today >= rec.get("review_due", "9999"):
                rec["status"] = "retire_candidate"
            merge[key] = True
    # 清理：不再出现在任何源的观察记录 → 保留历史但标记 stale（不删除，安全）
    for key in list(observe.keys()):
        if observe[key].get("source") == "zero_event":
            continue  # #68-B：隔离零事件桥接记录，防 --scan 误标 stale_passed
        if key not in merge:
            observe[key]["status"] = "stale_passed" if observe[key].get("status") in (
                "retire_candidate", "observing") else observe[key].get("status", "stale_passed")
    state["observe"] = observe
    _save(state)
    return state


def _mv_to_archive(stem: str) -> str:
    """物理移动到 references/archive/（保留可逆，mv 非 delete）。"""
    # 定位文件（references 下任意目录）
    target = None
    for f in REF_DIR.rglob(f"{stem}.md"):
        rel = f.relative_to(REF_DIR)
        if any(p in ("index", ".runtime", "archive") for p in rel.parts):
            continue
        target = f
        break
    if target is None:
        return f"❌ {stem}.md 不存在"
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    # 季度窗口检查：仅当本季度清理窗口开放（用于 --retire 批量执行；与 automation 频次无关）
    dest = ARCHIVE_DIR / f"{stem}.md.deprecated"
    if dest.exists():
        return f"⏭️  {stem} 已存在于 archive/（{dest.name}）"
    shutil.move(str(target), str(dest))
    return f"✅ {target.relative_to(REF_DIR)} → archive/{dest.name}"


def _register_in_index(stem: str, retired_rel: str) -> str:
    """#62-B：R4R↔INDEX 结构性闭环——`--retire` 物理 mv 后补登 archive/INDEX.md 一行。

    - 幂等：若 retired_rel 已出现在 INDEX.md 则跳过（重复 --retire 安全）。
    - 格式须匹配 archive/inventory.py::_registered_paths 解析正则
      `^\\|\\s*\\d+\\s*\\|\\s*`([^`]+)``（第二列反引号包裹的退役文件路径）。
    - 表行结构（与既有清单一致）：`| # | `archive/<stem>.md.deprecated` | 类型 | 活跃替代 | 日期 | 状态 | 守卫覆盖 |`
    - --retire 已是人工核准语义（须先 --scan 入 observe 记录），补登随其执行；不新增自动 enable。
    """
    if not INDEX.exists():
        return "⚠️ INDEX.md 不存在，跳过补登（%s）" % INDEX
    text = INDEX.read_text(encoding="utf-8")
    if retired_rel in text:                       # 幂等：已编目则跳过
        return "⏭️  %s 已在 INDEX.md 编目（幂等跳过）" % retired_rel
    lines = text.splitlines()
    max_no = 0
    for ln in lines:
        m = re.match(r"^\|\s*(\d+)\s*\|", ln)
        if m:
            max_no = max(max_no, int(m.group(1)))
    today = datetime.now().date().isoformat()
    row = "| %d | `%s` | references 语料资产 | `references/%s.md`（活跃版） | %s | deprecated | g002 / g020b / g021 |" % (
        max_no + 1, retired_rel, stem, today)
    # 在首个 "## 维护" 段前插入（即退役资产清单表尾），保持表格结构完整
    insert_at = len(lines)
    for i, ln in enumerate(lines):
        if ln.startswith("## 维护"):
            insert_at = i
            break
    lines.insert(insert_at, row)
    INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "✅ 已补登 INDEX.md（R4R↔INDEX 闭环）：%s" % row


def main():
    ap = argparse.ArgumentParser(description="QCM R4R 资产退休环")
    ap.add_argument("--scan", action="store_true", help="三源扫描 + 观察期推进")
    ap.add_argument("--list", action="store_true", help="列出候选与状态")
    ap.add_argument("--retire", metavar="stem", help="人工核准退休（mv → archive/）")
    ap.add_argument("--revive", metavar="stem", help="人工决策摘除候选举（保留原样）")
    ap.add_argument("--whitelist", metavar="stem", help="永久豁免")
    ap.add_argument("--status", action="store_true", help="状态机摘要 + 季度窗口")
    args = ap.parse_args()

    if args.scan:
        r = scan()
        state = observe(r)
        print(f"三源扫描（{r['generated_at']} · 季度周期 {r['retire_cycle_days']}d）:")
        print(f"  S1 孤儿 {len(r['orphan'])}: {r['orphan'][:8]}{'…' if len(r['orphan'])>8 else ''}")
        print(f"  S2 悬空 {len(r['dangling'])}: {r['dangling'][:8]}{'…' if len(r['dangling'])>8 else ''}")
        print(f"  S3 废弃 {len(r['deprecated'])}: {r['deprecated']}")
        due = [k for k, v in state.get('observe', {}).items() if v.get('status') == 'retire_candidate']
        print(f"  观察期满可退休: {len(due)} 项 → {due}")
        return

    if args.list:
        state = _load_state()
        print(f"whitelist({len(state.get('whitelist', []))}): {state.get('whitelist', [])}")
        obs = state.get("observe", {})
        print(f"观察/退休记录({len(obs)}):")
        for k, v in sorted(obs.items()):
            print(f"  [{v.get('status','?')}] {v.get('stem')} ({v.get('source')}) since={v.get('since')} due={v.get('review_due')}")
        return

    if args.retire:
        state = _load_state()
        r = scan()
        # 仅允许在观察记录中（retire_candidate 或人工强制）退休
        found = any(v.get("stem") == args.retire for v in state.get("observe", {}).values())
        if not found:
            print(f"⚠️  {args.retire} 不在观察记录中（先 --scan；如需强制请直接在状态文件操作）")
        else:
            mv = _mv_to_archive(args.retire)
            print(mv)
            # #62-B：物理 mv 成功后补登 archive/INDEX.md（R4R↔INDEX 结构性闭环）
            if "❌" not in mv:
                print(_register_in_index(args.retire, "archive/%s.md.deprecated" % args.retire))
            for k, v in state.get("observe", {}).items():
                if v.get("stem") == args.retire:
                    state["observe"][k]["status"] = "retired"
                    state["observe"][k]["retired_at"] = datetime.now().isoformat(timespec="seconds")
            state.setdefault("retired", {})[args.retire] = datetime.now().isoformat(timespec="seconds")
            _save(state)
        return

    if args.revive:
        state = _load_state()
        for k, v in list(state.get("observe", {}).items()):
            if v.get("stem") == args.revive and v.get("status") not in ("retired",):
                state["observe"][k]["status"] = "revived"
                state["observe"][k]["revived_at"] = datetime.now().isoformat(timespec="seconds")
        _save(state)
        print(f"↩️  {args.revive} 已标记 revived（保留原样 · 后续扫描不再推 retire）")
        return

    if args.whitelist:
        state = _load_state()
        wl = set(state.get("whitelist", [])) | ALWAYS_WHITELIST
        wl.add(args.whitelist)
        state["whitelist"] = sorted(wl)
        _save(state)
        print(f"🛡️  {args.whitelist} 已加入白名单（孤儿扫描豁免）")
        return

    if args.status:
        state = _load_state()
        obs = state.get("observe", {})
        candidates = sum(1 for v in obs.values() if v.get("status") == "retire_candidate")
        observing = sum(1 for v in obs.values() if v.get("status") == "observing")
        retired = len(state.get("retired", {}))
        print(f"R4R 状态机: observing={observing} · retire_candidate={candidates} · "
              f"retired={retired} · whitelist={len(state.get('whitelist', []))}")
        today = datetime.now().date()
        q_start = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
        print(f"当前物理清理窗口: {q_start.isoformat()} ~ "
              f"{(q_start + timedelta(days=90)).isoformat()}（每季度 1 次 · {RETIRE_CYCLE_DAYS}d 周期）")
        print(f"archive 目录: {ARCHIVE_DIR} {'已存在' if ARCHIVE_DIR.exists() else '未创建（--retire 时自动建）'}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()