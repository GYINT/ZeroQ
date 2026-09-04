#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 容量自适应容器（S1 · 容量限值归一化动态自适应）

背景：容量限值 40/20 曾 4 处硬编码（router/industry_sync/lifecycle/boundary_test）——
     本模块收敛为单一配置源（references/config/router.yaml 的 capacity: 段），
     四消费方统一 from capacity import get_limit 读取。

配置结构（router.yaml capacity: 段）：
  capacity:
    mode: fixed | adaptive          # fixed=固定值（默认·零回归）；adaptive=按 base 词总量比例
    defaults: {intent: {limit, unit}, domain: {limit, unit}, industry: {limit, unit}}
    intent_overrides: {"①危机处置": {limit: 60}}   # 差异化覆盖（意图/领域/行业）
    adaptive: {base_ratio, min_limit, max_limit}
    lifecycle: {new: pre_allocate, active: count, stable: count, hot: exempt, archived: release}

语义（对齐 §11.2 / router.py / industry_sync.py 口径）：
  - 仅 base 层计容量，hot 豁免（§11 生命周期天然管理），archived 退出路由不计
  - 缺失配置/解析失败 → 内置默认（40/20），与现状完全等价（零回归）
"""
import os
import json as _json
from datetime import datetime as _dt
from pathlib import Path
from paths import REF_CONFIG, KEYWORD_YAML

ROUTER_CFG = os.environ.get("QCM_ROUTER_CFG", str(REF_CONFIG / "router.yaml"))

# 内置默认（缺失配置时兜底 · 与历史 40/20 完全等价）
DEFAULT_CAPACITY = {
    "mode": "fixed",
    "defaults": {
        "intent": {"limit": 40, "unit": "count"},
        "domain": {"limit": 20, "unit": "count"},
        "industry": {"limit": 50, "unit": "count"},
    },
    "intent_overrides": {"①危机处置": {"limit": 60}},
    "domain_overrides": {},
    "industry_overrides": {},
    "adaptive": {"base_ratio": 0.10, "min_limit": 10, "max_limit": 120},
    "lifecycle": {"new": "pre_allocate", "active": "count", "stable": "count",
                  "hot": "exempt", "archived": "release"},
}

_loaded = False
_cfg = dict(DEFAULT_CAPACITY)


def _deep_merge(base: dict, extra: dict) -> dict:
    """浅合并默认配置与 yaml 配置（只覆盖存在的键 · 缺失用默认兜底）"""
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _deep_merge(base[k], v)
        else:
            out[k] = v
    return out


def load_capacity(force: bool = False) -> dict:
    """加载容量配置（router.yaml capacity: 段 · 配置驱动对齐 load_thresholds 范式）

    缺失/解析失败 → 内置默认（零回归）。幂等：重复调用只加载一次。
    """
    global _cfg, _loaded
    if _loaded and not force:
        return _cfg
    _loaded = True
    if not os.path.exists(ROUTER_CFG):
        return _cfg
    try:
        import yaml
        data = yaml.safe_load(open(ROUTER_CFG, encoding="utf-8")) or {}
        cap = data.get("capacity")
        if isinstance(cap, dict):
            _cfg = _deep_merge(DEFAULT_CAPACITY, cap)
    except Exception:
        pass  # 配置失败 → 默认值
    return _cfg


def get_limit(dim: str, key: str = None, base_total: int = 0) -> int:
    """按维度取容量限值（覆盖 > 默认 · adaptive 模式按 base 词总量比例计算）

    Args:
        dim:         intent | domain | industry
        key:        具体意图/领域/行业名（如 "①危机处置"）——有 overrides 覆盖时用之
        base_total: adaptive 模式的 base 词总量（限值 = base_total × base_ratio）

    Returns:
        int 限值（≥1）
    """
    load_capacity()
    defaults = _cfg.get("defaults", {})
    dim_cfg = defaults.get(dim, {})
    if not isinstance(dim_cfg, dict):
        dim_cfg = {"limit": dim_cfg if isinstance(dim_cfg, int) else 40, "unit": "count"}
    limit = int(dim_cfg.get("limit", 40))
    unit = dim_cfg.get("unit", "count")

    # 差异化覆盖（key 匹配 overrides）
    if key:
        overrides = _cfg.get(f"{dim}_overrides") or {}
        ov = overrides.get(key) if isinstance(overrides, dict) else None
        if isinstance(ov, dict) and ov.get("limit"):
            limit = int(ov["limit"])

    # adaptive 模式：限值 = base 词总量 × base_ratio（min/max 保护）
    if _cfg.get("mode") == "adaptive" and base_total > 0:
        ap = _cfg.get("adaptive", {})
        ratio = float(ap.get("base_ratio", 0.10))
        calc = int(base_total * ratio)
        calc = max(calc, int(ap.get("min_limit", 10)))
        calc = min(calc, int(ap.get("max_limit", 120)))
        # adaptive 覆盖默认 + overrides（overrides 显式指定则不压缩）
        if not (key and ( _cfg.get(f"{dim}_overrides") or {}).get(key)):
            limit = calc
        else:
            limit = max(limit, calc)  # overrides 显式高于自适应时取大

    return max(limit, 1)


def lifecycle_capacity(status: str, level: str = "base") -> str:
    """生命周期容量语义（new/active/stable=计 · hot=豁免 · archived=释放）

    对齐 router.py / industry_sync.py / keyword_lifecycle.py 口径（base 层计，hot 不占）。
    """
    load_capacity()
    if level == "hot":
        return "exempt"
    if status == "archived":
        return "release"
    lc = _cfg.get("lifecycle", {})
    return lc.get("new", "pre_allocate") if status == "new" else "count"


def counts(items: list) -> dict:
    """统计 base 层容量计数（对齐 router 口径：hot 豁免 · archived 不计）

    Args:
        items: keyword.yaml 词条列表
    Returns:
        {"intent": {intent: cnt}, "domain": {domain: cnt}}
    """
    intent_cnt, domain_cnt = {}, {}
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("status") == "archived":
            continue  # archived 退出路由不计容量
        if it.get("level") == "hot":
            continue  # hot 由 §11 生命周期管理，不占容量
        if it.get("intent"):
            intent_cnt[it["intent"]] = intent_cnt.get(it["intent"], 0) + 1
        if it.get("domain"):
            domain_cnt[it["domain"]] = domain_cnt.get(it["domain"], 0) + 1
    return {"intent": intent_cnt, "domain": domain_cnt}


def over_limits(items: list, base_total: int = 0) -> dict:
    """容量超限检测（消费方统一入口）

    Args:
        items:      词条列表
        base_total: base 词总量（adaptive 模式限值计算用）
    Returns:
        {"intent": {intent: (cnt, limit)}, "domain": {domain: (cnt, limit)}}
    """
    cs = counts(items)
    over = {"intent": {}, "domain": {}}
    for intent, cnt in cs["intent"].items():
        lim = get_limit("intent", intent, base_total)
        if cnt > lim:
            over["intent"][intent] = (cnt, lim)
    for domain, cnt in cs["domain"].items():
        lim = get_limit("domain", domain, base_total)
        if cnt > lim:
            over["domain"][domain] = (cnt, lim)
    return over


# ── M4 · 容器 runtime 台账（持久化 + 漂移 + 生命周期快照轮转） ──
# Q4 评估结论：counts/over_limits 纯瞬时计算，无持久台账/漂移基线 → 此处补齐。
# 台账落 outputs/.runtime/capacity_ledger.json（受管子目录 · 与运行态缓存同源）。
_LEDGER_PATH = None


def ledger_path():
    """容量台账路径（outputs/.runtime/capacity_ledger.json）"""
    global _LEDGER_PATH
    if _LEDGER_PATH is None:
        skill = Path(__file__).resolve().parent.parent
        _LEDGER_PATH = skill / "outputs" / ".runtime" / "capacity_ledger.json"
    return _LEDGER_PATH


def _load_keyword_items() -> list:
    """读取 keyword.yaml 词条（消费方数据 · 失败返回空）"""
    try:
        import yaml
        d = yaml.safe_load(KEYWORD_YAML.read_text(encoding="utf-8")) or {}
        return d.get("keywords", [])
    except Exception:
        return []


def update_ledger(items: list = None, base_total: int = 0, keep: int = 12,
                  rebaseline: bool = False) -> dict:
    """写入容量台账快照（当前计数）+ 计算与基线漂移。

    rebaseline=True：以当前实时计数重置基线(baseline=current)并清空漂移，
                     用于运维显式「重校准」（避免过期基线导致的持续误报）。
    Returns: {"drift": [...], "current": {"intent":{}, "domain":{}}}
    """
    items = items if items is not None else _load_keyword_items()
    cs = counts(items)
    cur = {"intent": cs["intent"], "domain": cs["domain"]}
    # 历史基线（上次台账 / 或 rebaseline 重置）
    base, drift = {}, []
    if rebaseline:
        base = cur                      # 重校准：基线对齐当前，漂移清零
    else:
        try:
            if ledger_path().exists():
                old = _json.loads(ledger_path().read_text(encoding="utf-8"))
                base = old.get("current", {})
                for dim in ("intent", "domain"):
                    for k, v in cur.get(dim, {}).items():
                        bv = base.get(dim, {}).get(k)
                        if bv is not None and bv != v:
                            drift.append({"dim": dim, "key": k, "base": bv, "current": v})
        except Exception:
            pass
    # 快照轮转（保留近 keep 份 · 全生命周期归档）
    snap = []
    try:
        if ledger_path().exists():
            snap = _json.loads(ledger_path().read_text(encoding="utf-8")).get("snapshots", [])
    except Exception:
        pass
    snap.append({"ts": _dt.now().isoformat(), "current": cur})
    snap = snap[-keep:]
    ledger_path().parent.mkdir(parents=True, exist_ok=True)
    # 原子写（tmp + rename）：崩溃中途不产生半写坏台账（M1.2 稳定性加固）
    _tmp = ledger_path().with_suffix(".json.tmp")
    _json.dump({"current": cur, "baseline": base, "drift": drift, "snapshots": snap},
               _tmp.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(_tmp, ledger_path())
    return {"drift": drift, "current": cur}


def check_ledger(items: list = None, base_total: int = 0):
    """M5 守卫实质化入口：返回 (over_limits, drift)。

    - over：当前词条相对容量限值的超限（核心容器语义）
    - drift：当前计数 vs 台账基线不一致（生命周期/注入漂移）
    - 台账损坏/缺失时不静默失明：返回一条 _corrupt 漂移标记，供上层告警
      （g_capacity 守卫可见性 · M1.2 稳定性加固，修复「损坏→空报」空壳再现）
    """
    items = items if items is not None else _load_keyword_items()
    over = over_limits(items, base_total)
    drift = []
    try:
        if ledger_path().exists():
            base = _json.loads(ledger_path().read_text(encoding="utf-8")).get("current", {})
            cs = counts(items)
            for dim in ("intent", "domain"):
                for k, v in cs.get(dim, {}).items():
                    bv = base.get(dim, {}).get(k)
                    if bv is not None and bv != v:
                        drift.append({"dim": dim, "key": k, "base": bv, "current": v})
    except Exception as e:
        # 台账损坏：不再静默吞异常，显式标记以便上层告警并引导重建
        drift.append({"_corrupt": True, "dim": "ledger", "key": "capacity_ledger.json",
                      "error": str(e)[:120]})
    return over, drift


def rotate_ledger(keep: int = 12) -> int:
    """台账快照轮转（保留近 keep 份），返回保留数"""
    try:
        if ledger_path().exists():
            d = _json.loads(ledger_path().read_text(encoding="utf-8"))
            before = len(d.get("snapshots", []))
            d["snapshots"] = d.get("snapshots", [])[:keep]
            _json.dump(d, ledger_path().open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
            return before - len(d["snapshots"])
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    C = load_capacity()
    print(f"容量容器 mode={C['mode']}")
    print(f"  意图默认 {get_limit('intent')} · ①危机处置 {get_limit('intent', '①危机处置')} · 领域默认 {get_limit('domain')}")
    print(f"  industry 默认 {get_limit('industry')}")
    print(f"  lifecycle: {C.get('lifecycle')}")
    ad = {}
    for total in (100, 300, 1000):
        ad[total] = get_limit("intent", None, total)
    print(f"  adaptive(base_ratio 0.10): base100→{ad[100]} · base300→{ad[300]} · base1000→{ad[1000]}")