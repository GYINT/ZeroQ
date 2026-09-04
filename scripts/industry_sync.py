#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 行业词条归一化注入（V8.5 · 登记 → 词库自动注入，消除双写漂移）

背景：industry/index.yaml 登记的行业包 keywords 只存在于注册表，未自动进 keyword.yaml →
      行业查询路由不命中（B5 行业扩展前置阻塞项）。本脚本打通「登记 → 注入」闭环。

设计：
  - 数据源：references/industry/index.yaml 的 industry_packs[].keywords
  - 目标：references/config/keyword.yaml（intent 从 pack 的 intent[0] 映射，domain 从 domain[0] 映射）
  - 溯源：词条加 source: industry + origin: <pack_id> 标记（可追溯 · 幂等主键）
  - 幂等：以 origin 为键去重——重复运行不重复注入；pack 删除时同步清理
  - 护栏：注入前检查词库容量（意图≤40 / 领域≤20，对齐 router.py 口径：hot 不占容量）
  - 模式：--dry-run 只报告不写回；--apply 执行写回

用法：
  python3 scripts/industry_sync.py --dry-run   # 只读预览注入计划
  python3 scripts/industry_sync.py --apply     # 执行注入
"""
import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "references" / "industry" / "index.yaml"
KEYWORD = ROOT / "references" / "config" / "keyword.yaml"

INTENT_MAP = {"①": "①危机处置", "②": "②流程优化", "③": "③评估审计",
              "④": "④知识学习", "⑤": "⑤知识沉淀"}
# 容量限值（S1 容量容器：统一从 core/capacity.py 读取路由器 capacity 配置 · 差异化覆盖 + adaptive）
# 兜底 40/20（容器不可用时零回归）
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
    from capacity import get_limit as _get_limit
    CAP_INTENT = _get_limit("intent")      # 意图容量（对齐 router.py：仅 base 层计）
    CAP_DOMAIN = _get_limit("domain")
    _CAP_FN = _get_limit
except Exception:
    CAP_INTENT = 40
    CAP_DOMAIN = 20
    _CAP_FN = None


def _load_yaml(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def load_packs():
    """读 industry/index.yaml → 归一化的注入计划列表"""
    data = _load_yaml(INDEX) or {}
    packs = data.get("industry_packs", []) if isinstance(data, dict) else []
    plan = []  # (word, intent, domain, pack_id)
    for p in packs:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id", "")).strip()
        kws = p.get("keywords") or []
        # intent/domain 为 YAML 列表（如 [①危机处置, ②流程优化, ⑤知识沉淀]）
        # 默认：行业特征词本质是"知识路由词" → 优先归 ④知识学习/⑤知识沉淀，
        #       无知识类意图才退到列表第一项（避免压爆意图①容量；语义也更贴切）
        # S8 机制修正：pack 可声明 keyword_intents 词级意图覆盖（如危机语境词显式归①），
        #       尊重行业语义——覆盖优先于知识偏好（修正原「一律偏好④/⑤」导致的危机词误标）
        intents = p.get("intent") or ["④知识学习"]
        if isinstance(intents, list) and intents:
            intent = next((x for x in intents if "④" in str(x) or "⑤" in str(x)), intents[0])
        else:
            intent = str(intents)
        intent_full = INTENT_MAP.get(intent[:1], intent)  # 简写映射：① → ①危机处置
        kw_intents = p.get("keyword_intents") or {}  # S8：{词: 意图} 覆盖表（word 级专用意图）
        kw_domains = p.get("keyword_domains") or {}  # L1：{词: 领域} 覆盖表（词级 domain · 跨域词精确路由）
        doms = p.get("domain") or ["A制造"]
        dom = doms[0] if isinstance(doms, list) and doms else str(doms)  # 取第一领域（消费电子→B设计 · 新能源→C供应链）
        for kw in kws:
            kw = str(kw).strip()
            if not kw:
                continue
            kw_intent = intent_full
            if kw in kw_intents:  # S8：词级覆盖优先（危机词 → ①危机处置）
                _ov = str(kw_intents[kw]).strip()
                _ov_full = INTENT_MAP.get(_ov[:1], _ov)
                if _ov_full in INTENT_MAP.values():  # 校验为合法意图
                    kw_intent = _ov_full
            dom_kw = kw_domains.get(kw, dom) if isinstance(kw_domains, dict) else dom  # L1：词级 domain 覆盖
            plan.append((kw, kw_intent, dom_kw, pid))
    return plan


def load_keywords():
    """读 keyword.yaml → (items, has_version_head)"""
    raw = KEYWORD.read_text(encoding="utf-8")
    data = _load_yaml(KEYWORD)
    if isinstance(data, dict):
        items = data.get("keywords", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return items, raw


def capacity_check(existing, incoming_plan):
    """容量护栏：意图/领域容量检查（对齐 router 口径：base 层计，hot 不占）

    修复（2026-09-02）：重复计数 bug——此前第二段把 incoming_plan 全量再次计入，
    含已注入词（同一 origin 已在 existing），致 B设计 14+8=22 误报超限；
    现改为仅对「真正待注入」plan 词计数（origin 不在 existing），与 build_injections 同源。
    L2/L3 对齐：跨 origin 同词（example: word 已在库但不同包）同样跳过（build_injections 已跳过 →
    容量不重复计入）。返回 (超限列表, 建议)
    """
    from collections import Counter
    intent_cnt = Counter()
    domain_cnt = Counter()
    existing_words = set()
    for it in existing:
        if not isinstance(it, dict):
            continue
        if it.get("word"):
            existing_words.add(str(it["word"]))
        if it.get("status") == "archived":
            continue
        if it.get("level") == "hot":
            continue  # hot 不占容量（router.py 口径）
        if it.get("intent"):
            intent_cnt[it["intent"]] += 1
        if it.get("domain"):
            domain_cnt[it["domain"]] += 1
    # 仅计「真正待注入」：origin 不在 existing，且词未被已有词条占用（避免把已注入/已存在词
    # 重复计入 → 误报超限 / 双写）。对齐 build_injections L2 判定。
    existing_origins = set()
    for it in existing:
        if isinstance(it, dict) and it.get("origin"):
            existing_origins.add(str(it["origin"]))
    for (word, intent, dom, pid) in incoming_plan:
        if f"{pid}:{word}" in existing_origins or word in existing_words:
            continue  # 已注入（幂等命中）或词已存在（L2）→ 不再计入
        intent_cnt[intent] += 1
        domain_cnt[dom] += 1
    # S1 容量容器：按具体意图/领域取差异化限值（①危机处置→60 · 领域默认→20）；容器不可用回退 40/20
    def _lim(dim, key):
        if _CAP_FN is not None:
            try:
                return _CAP_FN(dim, key)
            except Exception:
                pass
        return CAP_INTENT if dim == "intent" else CAP_DOMAIN
    over_i = {k: v for k, v in intent_cnt.items() if v > _lim("intent", k)}
    over_d = {k: v for k, v in domain_cnt.items() if v > _lim("domain", k)}
    return over_i, over_d


def build_injections(plan, existing):
    """按幂等键（origin）计算需注入/需清理 + L2/L3 词已存在保护

    修复（2026-09-02）：
      - 重复注入防护：仅以 origin 幂等不足——同词不同 origin（跨包）会双写；
        改为若「词已在 keyword.yaml」（任意 origin/任意 level/歧义 role）→ 跳过注入，
        记入 skipped，reason=已存在/歧义词（L2 · 防覆盖动态路由）。
      - 歧义词保护（L3 前置）：词已是 role: ambiguous → 跳过（保持歧义动态路由，不钉死意图）。
    返回 (to_add, to_clean, skipped)
    """
    existing_origins = set()
    existing_words = set()
    for it in existing:
        if not isinstance(it, dict):
            continue
        if it.get("origin"):
            existing_origins.add(str(it["origin"]))
        if it.get("word"):
            existing_words.add(str(it["word"]))
        if it.get("aliases"):
            for a in it.get("aliases") or []:
                existing_words.add(str(a)) if a else None
    plan_origins = {f"{pid}:{w}" for (w, _i, _d, pid) in plan}
    to_add = []
    skipped = []
    for (word, intent, dom, pid) in plan:
        origin = f"{pid}:{word}"
        if origin in existing_origins:
            continue  # 幂等命中（同包同词已存在）→ 静默跳过（正常幂等）
        existing_word = next((k for k in existing if isinstance(k, dict) and k.get("word") == word), None)
        if existing_word:
            reason = "歧义词已存在" if existing_word.get("role") == "ambiguous" else "词已存在"
            skipped.append({"word": word, "origin": origin, "reason": reason,
                            "existing_intent": existing_word.get("intent"),
                            "existing_domain": existing_word.get("domain")})
            continue  # L2：同词不同 origin / 歧义词 → 跳过注入，防双写/防覆盖
        to_add.append({
            "word": word, "intent": intent, "level": "base",
            "status": "new", "domain": dom,
            "source": "industry", "origin": origin,
            # S4 R5 注入链双向：显式 pack_ref（pack 登记 ←→ 词条引用闭环）
            "pack_ref": pid,
            "created_at": date.today().isoformat(),
            "aliases": [],
        })
    to_clean = sorted(existing_origins - plan_origins)
    return to_add, to_clean, skipped


def backfill_pack_ref(items, packs):
    """S4 R5 补写：存量 source: industry 词条缺 pack_ref → 从 origin 推导补齐
    幂等：有 pack_ref 不动；无 origin 不动（无法推导）；pack 已删则标记（不自动删）"""
    pack_ids = {str(p.get("id", "")) for p in packs if isinstance(p, dict)}
    changed = []
    for it in items:
        if not (isinstance(it, dict) and it.get("source") == "industry"):
            continue
        if it.get("pack_ref"):
            continue
        origin = str(it.get("origin") or "")
        if ":" in origin:
            pid = origin.split(":", 1)[0]
            if pid in pack_ids:
                it["pack_ref"] = pid
                changed.append((it.get("word"), pid))
        elif it.get("word"):
            # 无 origin → 无法推导（保持缺省 · 留 R5 告警）
            pass
    return changed


def write_keyword(items, raw):
    """写回 keyword.yaml（若原文件是 keywords: 键结构则保持，仅替换列表部分）
    注意：原文件结构为 `keywords:\n- word: ...`（dict 键 keywords → 列表）"""
    import yaml
    if raw.lstrip().startswith("keywords:"):
        # 保持 dict 结构：{"keywords": items}
        return yaml.safe_dump({"keywords": items}, allow_unicode=True, sort_keys=False)
    return yaml.safe_dump(items, allow_unicode=True, sort_keys=False)


def _dump_items(items):
    import yaml
    return yaml.safe_dump(items, allow_unicode=True, sort_keys=False)


def sync_stats():
    """运行环：读 hit_stats.json（未命中词统计）≠——注意 hit_stats 记录的是未命中。
    V8.5 命中观测：统计 keyword.yaml 中 source: industry 词条的命中情况。
    数据源受限（hit_tracker 只记未命中），故此处以「词条被路由加载」为基线 +
    手动/定时回灌未命中计数（未来可接真实命中日志）。
    输出：每个 pack 的 hit_count/last_hit（当前基线 + 未命中提示）。
    """
    import json
    hit_stats = ROOT / "references" / "hit_stats.json"
    misses = {}
    if hit_stats.exists():
        try:
            misses = json.loads(hit_stats.read_text(encoding="utf-8"))
        except Exception:
            misses = {}
    data = _load_yaml(INDEX) or {}
    packs = data.get("industry_packs", []) if isinstance(data, dict) else []
    today = date.today().isoformat()
    changed = False
    lines = []
    for p in packs:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id", ""))
        kws = [str(k) for k in (p.get("keywords") or [])]
        # 未命中词（行业词被查询但未命中路由 → 说明词条未生效或需补充）
        miss_words = [w for w in misses.keys() if any(w in k or k in w for k in kws)]
        hit_count = int(p.get("hit_count") or 0)
        last_hit = p.get("last_hit") or "-"
        if miss_words:
            # 有未命中 → 提示（不自动改 hit_count，留人工确认）
            lines.append(f"  {pid}: hit={hit_count} last={last_hit} ⚠️ 未命中词 {miss_words[:3]}")
        else:
            lines.append(f"  {pid}: hit={hit_count} last={last_hit} ✅ 无待补词")
    print("行业包命中观测（参考 hit_stats.json）：")
    print("\n".join(lines))
    return 0


def main():
    ap = argparse.ArgumentParser(description="QCM 行业词条归一化注入")
    ap.add_argument("--dry-run", action="store_true", help="只读预览，不写回")
    ap.add_argument("--apply", action="store_true", help="执行写回")
    ap.add_argument("--stats", action="store_true", help="行业包命中观测（读 hit_stats）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    if args.stats:
        return sync_stats()

    if not INDEX.exists():
        print(f"❌ 缺行业包注册中心: {INDEX}")
        return 1
    if not KEYWORD.exists():
        print(f"❌ 缺词库: {KEYWORD}")
        return 1

    plan = load_packs()
    items, raw = load_keywords()
    to_add, to_clean, skipped = build_injections(plan, items)
    over_i, over_d = capacity_check(items, plan)

    out_lines = [f"行业包关键词: {len(plan)} 个 · 需注入: {len(to_add)} · 需清理: {len(to_clean)}"]
    if to_add:
        out_lines.append("待注入词条:")
        for it in to_add:
            out_lines.append(f"  + {it['word']} ← {it['origin']} (intent={it['intent']} domain={it['domain']})")
    if skipped:
        out_lines.append("跳过（词已存在 · L2/L3 防双写/防覆盖）:")
        for s in skipped:
            out_lines.append(f"  - {s['word']} ({s['reason']} · 已存在 intent={s['existing_intent']} domain={s['existing_domain']})")
    if to_clean:
        out_lines.append("待清理(源已删): " + ", ".join(to_clean))
    if over_i:
        out_lines.append(f"⚠️ 意图容量超限: {over_i}")
    if over_d:
        out_lines.append(f"⚠️ 领域容量超限: {over_d}")

    if args.json:
        import json
        print(json.dumps({"plan": len(plan), "to_add": len(to_add), "to_clean": len(to_clean),
                          "skipped": skipped or [],
                          "over_intent": over_i, "over_domain": over_d,
                          "added": [it["word"] for it in to_add]}, ensure_ascii=False, indent=1))
        return 0

    print("\n".join(out_lines))

    if over_i or over_d:
        print("❌ 容量超限，请先人工分流（--apply 中止）")
        return 1 if args.apply else 0

    if not args.apply:
        print("\n(dry-run：以上为注入计划 · 使用 --apply 执行)")
        return 0

    # S4 R5：存量 industry 词条缺 pack_ref → 从 origin 补写（幂等 · 原地修改 items）
    packs = _load_yaml(INDEX) or {}
    pack_list = packs.get("industry_packs", []) if isinstance(packs, dict) else []
    bk = backfill_pack_ref(items, pack_list)

    if not to_add and not to_clean and not bk:
        print("✅ 无需变更（幂等：已全部注入 · 无 pack_ref 待补写）")
        return 0

    # 构造新词条列表：保留已有 + 追加新增 + 剔除清理
    new_items = [it for it in items if not (isinstance(it, dict) and it.get("origin") in set(to_clean))]
    existing_origins = {str(it.get("origin")) for it in new_items if isinstance(it, dict) and it.get("origin")}
    for it in to_add:
        if it["origin"] not in existing_origins:
            new_items.append(it)
            existing_origins.add(it["origin"])

    KEYWORD.write_text(write_keyword(new_items, raw), encoding="utf-8")
    print(f"\n✅ 注入完成：新增 {len(to_add)} · 补写 pack_ref {len(bk)} · 清理 {len(to_clean)} → {KEYWORD}")
    if bk:
        print("  补写明细（前 10）: " + ", ".join(f"{w}→{p}" for w, p in bk[:10]))

    # S5a 分发接线：apply 尾部复检（R5 注入链双向闭环 · 写回不引入断链）
    try:
        import sys as _sys2
        _sys2.path.insert(0, str(ROOT / "core"))
        from guardian_reverse import check_r5
        _r5_i, _r5_w = check_r5(new_items, pack_list)
        if _r5_w:
            print(f"⚠️ 尾部复检（R5）：仍 {len(_r5_w)} 条未闭环（写入后需人工处理）:")
            for wm in _r5_w[:10]:
                print(f"    {wm}")
        else:
            print("✅ 尾部复检（R5）：注入链双向引用完整 · 零断链")
    except Exception as _e:
        print(f"ℹ️ 尾部复检跳过（guardian_reverse 不可用: {_e}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())