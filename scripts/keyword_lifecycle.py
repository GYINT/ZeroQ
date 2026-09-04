#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 热词生命周期执行器（V8.4 P5 · 词源管理 #2 生命周期状态机）

§11.2 五态状态机的代码化执行器：新建 → 活跃 → 稳定 → 归档 → 淘汰
驱动信号：状态元数据（status）+ 容量约束（意图≤40/领域≤20）+ 词龄/命中（可选元数据）

用法：
  python3 scripts/keyword_lifecycle.py --check    # CI 健康检查（0 严重即绿）
  python3 scripts/keyword_lifecycle.py --report   # 状态分布 + 迁移建议（dry-run）
  python3 scripts/keyword_lifecycle.py --promote  # 实际执行迁移（写回 keyword.yaml）
  python3 scripts/keyword_lifecycle.py --apply-r4           # R4 热度写回（dry-run · 默认安全）
  python3 scripts/keyword_lifecycle.py --apply-r4 --yes    # R4 热度写回（hot 化实际执行 · 归档留候）
  python3 scripts/keyword_lifecycle.py --apply-r4 --yes --auto-archive  # 写回（+ 90d 零活动稳定词自动归档）

设计原则：
  - 只读检查默认安全（--check/--report 不改文件）；--promote 显式写回
  - 迁移规则对齐 §11.2（new→active→stable→archived→淘汰）
  - 防御性：无元数据（created_at/hit_count_30d）的词不强行迁移，仅提示
"""
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parent.parent
from paths import KEYWORD_YAML as KEYWORD  # V8.4 路径归一

# 生命周期迁移规则（天数阈值 · 与 §11.2 对齐）
RULE = {
    "new_to_active_days": 14,        # 新建满 14 天 → 活跃
    "active_to_stable_days": 30,     # 活跃满 30 天 → 稳定
    "stable_archive_miss_days": 90,  # 稳定连续 90 天无命中 → 归档候选
    "archive_retention_cycles": 2,   # 归档保留 2 个周期 → 淘汰
}
# 容量上限（S1 容量容器：统一从 core/capacity.py 读取 · 差异化覆盖 + adaptive）
# 对齐 router.py 容量约束；容器不可用回退 40/20（零回归）
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
    import capacity as _capacity
    CAP_INTENT = _capacity.get_limit("intent")
    CAP_DOMAIN = _capacity.get_limit("domain")
    def _lim(dim, key):
        try:
            return _capacity.get_limit(dim, key)
        except Exception:
            return CAP_INTENT if dim == "intent" else CAP_DOMAIN
except Exception:
    CAP_INTENT = 40
    CAP_DOMAIN = 20
    def _lim(dim, key):
        return CAP_INTENT if dim == "intent" else CAP_DOMAIN


def load():
    import yaml
    data = yaml.safe_load(KEYWORD.read_text(encoding="utf-8")) or {}
    items = data.get("keywords", [])
    for it in items:
        it.setdefault("status", "new")
        it.setdefault("level", "base")
    return data, items


def stats(items):
    """状态分布 + 容量 + 年龄"""
    dist = {}
    for it in items:
        dist[it["status"]] = dist.get(it["status"], 0) + 1

    intent_cnt, domain_cnt = {}, {}
    for it in items:
        if it.get("status") == "archived":
            continue  # V8.4 P5：archived 退出活跃路由，不计容量
        if it.get("level") == "hot":
            continue  # V8.4+ 热词层由 §11 生命周期天然管理，不占容量（对齐 core/router.py 容量口径）
        if it.get("intent"):
            intent_cnt[it["intent"]] = intent_cnt.get(it["intent"], 0) + 1
        if it.get("domain"):
            domain_cnt[it["domain"]] = domain_cnt.get(it["domain"], 0) + 1

    # 词龄（created_at 元数据存在时）
    today = datetime.now().date()
    aged = {"new": [], "active": []}
    for it in items:
        ca = it.get("created_at")
        if ca and it["status"] in ("new", "active"):
            try:
                d = datetime.strptime(ca, "%Y-%m-%d").date()
                aged[it["status"]].append((it["word"], (today - d).days))
            except Exception:
                pass

    return dist, intent_cnt, domain_cnt, aged


def check():
    """CI 健康检查：容量超限（严重）+ 状态异常（严重）+ 迁移候选（警告）"""
    try:
        data, items = load()
    except Exception as e:
        print(f"❌ keyword.yaml 加载失败: {e}")
        return 2

    dist, intent_cnt, domain_cnt, aged = stats(items)
    issues, warns = [], []

    # ① 容量检查（严重 · 仅统计活跃词：archived 退出路由后不计入）
    for intent, cnt in sorted(intent_cnt.items()):
        lim = _lim("intent", intent)
        if cnt > lim:
            issues.append(f"❌ 意图 {intent} 活跃词数 {cnt} 超限（上限 {lim}）——需淘汰/归档")
    for dom, cnt in sorted(domain_cnt.items()):
        lim = _lim("domain", dom)
        if cnt > lim:
            warns.append(f"⚠️  领域 {dom} 词数 {cnt} 超限（上限 {lim}）")

    # ② 状态异常（严重）
    # V8.4 S7b：hot 是 §11 热词生命周期合法状态（热词豁免 · guardian_reverse R4 显式支持）
    #   → 值域与 guardian.yaml / guardian_reverse.check_r4 对齐（合法: {new,active,stable,hot,archived}）
    valid = {"new", "active", "stable", "hot", "archived"}
    for it in items:
        if it["status"] not in valid:
            issues.append(f"❌ 词 {it['word']} 状态非法: {it['status']}（合法: {valid}）")

    # ③ 迁移候选（警告 · dry-run）
    for status, limit in (("new", RULE["new_to_active_days"]), ("active", RULE["active_to_stable_days"])):
        for word, age in aged.get(status, []):
            if age >= limit:
                target = "active" if status == "new" else "stable"
                warns.append(f"ℹ️  {word}（{status} {age} 天）≥{limit} 天 → 建议 {target}（--promote 执行）")

    # ④ 元数据缺失提示（警告）
    no_meta = [it["word"] for it in items if it["status"] in ("new", "active") and not it.get("created_at")]
    if no_meta:
        warns.append(f"ℹ️  {len(no_meta)} 个 new/active 词缺 created_at 元数据（无法自动迁移，建议补充）")

    print("QCM 热词生命周期健康检查")
    print(f"  状态分布: {dist}")
    print(f"  严重问题: {len(issues)} 项 · 警告/建议: {len(warns)} 项")
    for i in issues:
        print(f"    {i}")
    for w in warns[:12]:
        print(f"    {w}")
    if len(warns) > 12:
        print(f"    … 其余 {len(warns) - 12} 条见 --report")
    return 1 if issues else 0


def report():
    """状态分布 + 迁移建议详细报告"""
    data, items = load()
    dist, intent_cnt, domain_cnt, aged = stats(items)
    print("QCM 热词生命周期状态报告")
    print(f"  总词数: {len(items)}")
    print(f"  状态分布: {dist}")
    print(f"  意图容量: {intent_cnt}")
    print(f"  领域容量: {domain_cnt}")
    for status, limit in (("new", RULE["new_to_active_days"]), ("active", RULE["active_to_stable_days"])):
        cands = [(w, a) for w, a in aged.get(status, []) if a >= limit]
        if cands:
            print(f"  [{status}→迁移候选] " + ", ".join(f"{w}({a}d)" for w, a in cands[:10]))
    return 0


def backfill_created_at():
    """V8.4 闭环 Step 2：为缺 created_at 的词回填时间戳（按状态推断 · 幂等）

    stable → 45 天前 · active → 15 天前 · new → 今天（new 需积累观察期）
    回填后 --promote 即可按年龄自动迁移（闭合决策环自动化）。
    """
    import yaml
    data, items = load()
    today = datetime.now().date()
    filled = 0
    for it in items:
        if it.get("created_at"):
            continue
        st = it.get("status", "new")
        if st == "stable":
            it["created_at"] = (today - timedelta(days=45)).isoformat()
        elif st == "active":
            it["created_at"] = (today - timedelta(days=15)).isoformat()
        else:  # new
            it["created_at"] = today.isoformat()
        filled += 1
    if filled:
        KEYWORD.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"✅ 已回填 {filled} 个词 created_at（stable=45d前 · active=15d前 · new=今天）")
    else:
        print("ℹ️  全部词已有 created_at 元数据")
    return 0


def promote():
    """实际执行迁移（写回 keyword.yaml）——保守：仅处理有 created_at 且达阈值的新/活跃词"""
    import yaml
    data, items = load()
    today = datetime.now().date()
    changed = []
    for it in items:
        ca = it.get("created_at")
        if not ca or it["status"] not in ("new", "active"):
            continue
        try:
            age = (today - datetime.strptime(ca, "%Y-%m-%d").date()).days
        except Exception:
            continue
        if it["status"] == "new" and age >= RULE["new_to_active_days"]:
            it["status"] = "active"
            changed.append((it["word"], "new→active"))
        elif it["status"] == "active" and age >= RULE["active_to_stable_days"]:
            it["status"] = "stable"
            changed.append((it["word"], "active→stable"))

    if changed:
        KEYWORD.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"✅ 已迁移 {len(changed)} 个词：")
        for w, tr in changed[:15]:
            print(f"    {w}: {tr}")
    else:
        print("ℹ️  无词达到迁移阈值（需 created_at 元数据）")

    # S5a 分发接线：--promote 尾部复检（迁移写回不引入断链 · R1 孤儿/R5 注入链）
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
        from guardian_reverse import check_all
        _ri, _rw = check_all()
        if _rw:
            print(f"⚠️ 尾部复检（反向守卫族）：{len(_rw)} 条警告（迁移后需人工复核）:")
            for wm in _rw[:10]:
                print(f"    {wm}")
        else:
            print("✅ 尾部复检（反向守卫族）：R1-R5 全部通过 · 写回无断链")
    except Exception as _e:
        print(f"ℹ️ 尾部复检跳过（guardian_reverse 不可用: {_e}）")
    return 0


def apply_r4():
    """R18 R4 写回自动化：把 [反向R4] 热度建议落地为 keyword.yaml 状态变更

    复用 guardian_reverse 的 R4 判定逻辑与阈值（R4_HOT_HITS=10 / R4_STALE_DAYS=90 /
    R4_HOT_MIN=5）——决策与执行同阈值（一侧改动两侧生效，归一化定义单一）。
    - high 命中（≥10 次）→ status: hot + level: hot（挑单词条写回）
    - 长期零活动（≥90d）→ 归档候选（默认留人工确认）
      --auto-archive 旗标：--yes + --auto-archive 双旗标下自动归档（保底：稳定态 + 有 last_seen）
    - hot 词豁免：热词豁免策略继承（名不副实仅提示 · 不自动降级）
    用法：
      --apply-r4              # dry-run：仅展示候选（默认安全 · 不改文件）
      --apply-r4 --yes        # 实际写回（仅 hot 化 · 归档留候选）
      --apply-r4 --yes --auto-archive  # 写回（hot 化 + 90d 零活动稳定词自动归档）
    """
    import yaml
    # ① 复用 guardian_reverse R4 判定（同阈值单一来源）
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
    from guardian_reverse import check_r4, load_usage, load_hits, R4_HOT_HITS

    auto_archive = "--auto-archive" in sys.argv

    data, items = load()
    usage = load_usage()
    hits = load_hits()
    _, warnings = check_r4(keywords=items, usage=usage, hits=hits)

    # ② 解析候选（hot 化候选：非 hot 且 30d 命中 ≥ 阈值）
    #    热词豁免对齐 check_r4（S7b）：status: hot 为人工/流程主动提升，
    #    不做热度动态判定（名不副实仅提示 · 不自动降级）→ 解析候选同样跳过
    hot_cands, stale_cands, underuse_cands = [], [], []
    for it in items:
        if not isinstance(it, dict) or it.get("status") == "hot":
            continue
        w = it.get("word", "")
        st = (usage or {}).get(w) or {}
        total = int(st.get("total") or 0)
        hit = 0
        if isinstance(hits, dict) and w in hits:
            hv = hits[w]
            hit = int(hv.get("count") or 0) if isinstance(hv, dict) else int(hv or 0)
        if (total + hit) >= R4_HOT_HITS:
            hot_cands.append((w, total + hit, it))
            continue
        # 归档候选（非 hot · 有使用数据 · ≥90d 零活动）
        if st:
            try:
                last = st.get("last_seen")
                days = None
                if last:
                    d = datetime.strptime(str(last)[:10], "%Y-%m-%d").date()
                    days = (datetime.now().date() - d).days
                if days is not None and days >= RULE["stable_archive_miss_days"]:
                    stale_cands.append((w, days, it))
            except Exception:
                pass

    # ③ 输出候选
    hot_str = "、".join(w for w, _n, _it in hot_cands) or "无"
    stale_str = "、".join(f"{w}({d}d)" for w, d, _it in stale_cands) or "无"
    print(f"-- R4 热度写回候选 --\n  hot 化（30d 命中≥{R4_HOT_HITS}）: {hot_str}\n  "
          f"归档候选（≥{RULE['stable_archive_miss_days']}d 零活动 · 留人工确认）: {stale_str}\n  "
          f"hot 名不副实（提示不降级）: {len(underuse_cands)} 项")

    # ④ dry-run 默认 → 不写
    if "--yes" not in sys.argv:
        print("ℹ️  dry-run：仅展示候选 · 写回需 --yes（hot 化自动执行 · 归档需 --auto-archive 双旗标）")
        return 0

    # ⑤ 实际写回：hot 化 + （可选）90d 零活动自动归档
    changed = []
    for w, n, it in hot_cands:
        it["status"] = "hot"
        it["level"] = "hot"
        changed.append((w, f"→hot（命中 {n} 次）"))
    if auto_archive:
        # 保底（对齐 §11.2 归档语义 · 避免误归档活跃词）：
        #   - 仅 status in (stable, active)（new 未成长期 / hot 豁免不归档）
        #   - 词条必须带 last_seen（空数据不判 · check_r4 同源约束）
        archived = 0
        for w, days, it in stale_cands:
            if it.get("status") not in ("stable", "active"):
                continue  # 保底①：new/hot 不归档
            st = (usage or {}).get(w) or {}
            if not st.get("last_seen"):
                continue  # 保底②：无 last_seen 事实不判
            it["status"] = "archived"
            it["level"] = "base" if it.get("level") == "hot" else it.get("level", "base")
            changed.append((w, f"→archived（{days}d 零活动 · R4 自动归档）"))
            archived += 1
        print(f"  ℹ️  自动归档候选 {len(stale_cands)} → 实际归档 {archived}（保底：仅 stable/active + 有 last_seen）")
    else:
        if stale_cands:
            print(f"  ℹ️  归档候选 {len(stale_cands)} 留人工确认（需 --yes --auto-archive 双旗标自动执行）")
    if changed:
        KEYWORD.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"✅ 已写回 {len(changed)} 个词：")
        for w, tr in changed[:20]:
            print(f"    {w}: {tr}")
    else:
        print("ℹ️  无可写回（--yes 无 hot 化候选且无自动归档）")

    # ⑥ 尾部复检（对齐 --promote：写回不引入断链）
    try:
        from guardian_reverse import check_all
        _ri, _rw = check_all()
        if _rw:
            print(f"⚠️ 尾部复检（反向守卫族）：{len(_rw)} 条警告（写回后需人工复核）:")
            for wm in _rw[:10]:
                print(f"    {wm}")
        else:
            print("✅ 尾部复检（反向守卫族）：R1-R5 全部通过 · 写回无断链")
    except Exception as _e:
        print(f"ℹ️ 尾部复检跳过（guardian_reverse 不可用: {_e}）")
    return 0


def main():
    if "--check" in sys.argv:
        return check()
    if "--backfill" in sys.argv:
        return backfill_created_at()
    if "--promote" in sys.argv:
        return promote()
    if "--apply-r4" in sys.argv:
        return apply_r4()
    return report()


if __name__ == "__main__":
    sys.exit(main())
