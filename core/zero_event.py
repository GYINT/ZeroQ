#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归零事件全景维度子模块（QCM sub-module · zero_event）

默认关闭（enabled=false）：不挂 nightrun、不自动记录、治理守卫不主动扫描。
用户主动触发（--trigger）时实施记录。

全景维度模型 ZE-PDM（10 维度）：
  D1 登记 / D2 生命周期 / D3 能力层覆盖 / D4 状态机 / D5 闭环门禁 /
  D6 沉淀 / D7 复用 / D8 复发 / D9 观测 / D10 治理闭环。

设计来源：前序评估（实施状况 / 覆盖范围 / 闭环沉淀复用三评）沉淀的 GAP-QE 系列。
安全契约：与 QCM 守卫一致——report-only、默认关闭、用户主动触发才记录；无任何静默改写。
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
CFG = SKILL_ROOT / "references/config/zero_event.yaml"
REG = SKILL_ROOT / "references/data/zero_events.yaml"
ASSET_DIR = SKILL_ROOT / "references/data/zero_event"   # M4：zero_event 动态资产落地目录（事件级沉淀/复用报告/退休交接）

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _load_yaml(p):
    if yaml is None:
        raise RuntimeError("PyYAML 不可用（请用 venv python 运行）")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _save_yaml(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_config():
    if not CFG.exists():
        return {"schema_version": 1, "enabled": False}
    return _load_yaml(CFG)


def save_config(cfg):
    _save_yaml(CFG, cfg)


def is_enabled(cfg=None):
    cfg = cfg or load_config()
    return bool(cfg.get("enabled", False))


def load_registry():
    if not REG.exists():
        return {"meta": {"schema_version": 1,
                          "created_at": datetime.now().isoformat(timespec="seconds")},
                "events": []}
    return _load_yaml(REG)


def save_registry(reg):
    _save_yaml(REG, reg)


def now():
    return datetime.now().isoformat(timespec="seconds")


def _as_list(v):
    """MIL 多值字段 → list（支持逗号/顿号/分号分隔 / 已是 list）。"""
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [x for x in v if x not in (None, "")]
    if isinstance(v, str):
        return [p.strip() for p in str(v).replace("；", ";").replace("、", ";").split(";") if p.strip()]
    return [v]


def _parse_yield_pct(v):
    """从文本解析良率百分比（如 '98.5%'/'良率98.5'/'98.5' → 98.5）；失败返回 None。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def _normalize_dimensions(event):
    """P2-a：对所有维度块做复制透传，并对 D2/D9/D10 子字段补默认 + 类型校正（不碰 D5 判据 ok）。

    兼容两种输入形态：
      - mil_adapter 的 nested「dimensions」字典
      - --trigger/HTML 的顶层 D2_生命周期..D10_治理闭环 键
    返回完整规范化后的 {dim_key: dict}（含 D3/D5/D6/D7/D8 透传）。
    """
    ALL = ("D2_生命周期", "D3_能力层覆盖", "D5_闭环门禁", "D6_沉淀",
           "D7_复用", "D8_复发", "D9_观测", "D10_治理闭环")
    out = {}
    for k in ALL:
        if k in event and event[k] is not None:
            out[k] = dict(event[k]) if isinstance(event[k], dict) else event[k]
    # D2
    if "D2_生命周期" in out:
        d2 = out["D2_生命周期"]
        for k in ("part_number", "process", "root_cause", "corrective_action"):
            d2.setdefault(k, ""); d2[k] = "" if d2[k] is None else str(d2[k])
        d2.setdefault("lots", [])
        if not isinstance(d2["lots"], list):
            d2["lots"] = _as_list(d2["lots"])
    # D9
    if "D9_观测" in out:
        d9 = out["D9_观测"]
        for k in ("current_status", "actual", "target", "image_ref", "metric"):
            d9.setdefault(k, ""); d9[k] = "" if d9[k] is None else str(d9[k])
        if "actual_yield_pct" not in d9:
            d9["actual_yield_pct"] = _parse_yield_pct(d9.get("actual"))
        if "target_yield_pct" not in d9:
            d9["target_yield_pct"] = _parse_yield_pct(d9.get("target"))
    # D6（C5-P4 · G-STD-1：标准化→②流程优化 语料检入状态，additive 不破坏既有）
    if "D6_沉淀" in out:
        d6n = out["D6_沉淀"]
        d6n.setdefault("standard_ref", "")
        d6n.setdefault("indexed", False)
        d6n.setdefault("corpus_ref", "")
        d6n.setdefault("corpus_type", "standard")
        d6n["standard_ref"] = "" if d6n.get("standard_ref") is None else str(d6n["standard_ref"])
        if not isinstance(d6n.get("indexed"), bool):
            d6n["indexed"] = bool(d6n.get("indexed"))
    # D10
    if "D10_治理闭环" in out:
        d10 = out["D10_治理闭环"]
        d10.setdefault("culture_education", ""); d10.setdefault("case_promotion", "")
        # C5-P4 · G-CULT-1：语料检入状态（⑥质量文化路由触发→corpus 承载），additive
        d10.setdefault("enrolled_as_corpus", False)
        d10.setdefault("corpus_ref", "")
        for k in ("culture_education", "case_promotion", "corpus_ref"):
            d10[k] = "" if d10[k] is None else str(d10[k])
        if not isinstance(d10.get("enrolled_as_corpus"), bool):
            d10["enrolled_as_corpus"] = bool(d10.get("enrolled_as_corpus"))
    return out


def _collect_raw_dims(event):
    """收集维度块：优先 mil_adapter 的 nested「dimensions」，再用顶层 D2..D10 键覆盖。"""
    _raw = {}
    if isinstance(event.get("dimensions"), dict):
        _raw.update(event["dimensions"])
    for _k in ("D2_生命周期", "D3_能力层覆盖", "D5_闭环门禁", "D6_沉淀",
               "D7_复用", "D8_复发", "D9_观测", "D10_治理闭环"):
        if _k in event:
            _raw[_k] = event[_k]
    return _raw


def from_mil(path, force=False, apply=False):
    """P2-c：MIL 行 JSON 文件 → mil_to_event → record（复用适配器单一路径，零写回重复逻辑）。

    红线：复用 record(apply=...) 既有 --apply 门控，无新写回面；多行批量逐条 record。
    """
    try:
        from mil_adapter import mil_to_event as _m2e
    except ImportError:
        sys.path.insert(0, str(SKILL_ROOT / "scripts"))
        from mil_adapter import mil_to_event as _m2e
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else [data]
    ok = True
    for row in rows:
        evt = _m2e(row, source_ref=str(path))
        if not record(evt, force=force, apply=apply):
            ok = False
    return ok


def record(event, force=False, apply=False):
    """用户主动触发时实施记录。默认关闭下仅手动 --trigger（或 --force）可写。"""
    cfg = load_config()
    enabled = is_enabled(cfg)
    if enabled:
        print("[zero_event] enabled=true · 执行记录")
    elif force:
        print("[zero_event] 默认关闭；本次为您的主动触发（--trigger --force），将记录事件")
    else:
        print("[zero_event] 默认关闭（enabled=false）；本次 --trigger 视为主动触发，将记录事件")
        print("             （如需常驻开启请用 --enable；强制单次用 --trigger --force）")

    eid = event.get("event_id") or event.get("id")
    title = event.get("title")
    if not eid or not title:
        print("❌ 记录失败：event_id 与 title 为必填（最小必要集）")
        return False

    # D2/D9/D10 子字段规范化（P2-a · 不碰 D5 判据 · 保留既有未知 key）
    event = dict(event)
    for _dk, _dv in _normalize_dimensions(event).items():
        event[_dk] = _dv

    # D2/D9/D10 子字段规范化（P2-a · 不碰 D5 判据 · 兼容 nested/顶层两种形态）
    event = dict(event)

    reg = load_registry()
    events = reg.setdefault("events", [])
    ts = now()
    existing = next((e for e in events if e.get("event_id") == eid), None)

    if existing is None:
        evt = {
            "event_id": eid,
            "title": title,
            "registered_at": ts,
            "owner": event.get("owner", ""),
            "domain": event.get("domain", ""),
            "severity": event.get("severity", ""),
            "intent_route": event.get("intent_route", ""),
            "f13_confidence": event.get("f13_confidence"),
            "source_ref": event.get("source_ref", ""),
            "reuse_features": event.get("reuse_features", {}),  # L1: 复用匹配向量(industry/crisis_type/tools/standards)
            "status": "registered",                       # 状态机 spine：open → registered
            "current_stage": event.get("current_stage", "识别"),
            "associations": event.get("associations", {}),  # 数据关联（parent_event_id/related_event_ids）
            "dimensions": _normalize_dimensions(_collect_raw_dims(event)),
            "audit_trail": [{"at": ts, "action": "record", "via": "trigger"}],
        }
        events.append(evt)
        print("✅ 新建事件并登记：%s（status=registered）" % eid)
    else:
        for k in ("title", "owner", "domain", "severity", "intent_route",
                  "f13_confidence", "source_ref", "current_stage", "status", "associations"):
            if k in event:
                existing[k] = event[k]
        existing.setdefault("audit_trail", []).append(
            {"at": ts, "action": "update", "via": "trigger"})
        print("✅ 更新事件：%s（status=%s）" % (eid, existing.get("status")))

    reg["meta"]["updated_at"] = ts
    if apply:
        save_registry(reg)
        return True
    print("[dry-run] 未写回 registry（须 --apply 实际持久化）")
    return True


def panorama(eid=None):
    reg = load_registry()
    events = reg.get("events", [])
    if not events:
        print("（无已登记事件；子模块默认关闭，待 --trigger 主动记录）")
        return
    target = [e for e in events if eid is None or e.get("event_id") == eid]
    if eid and not target:
        print("❌ 未找到事件：%s" % eid)
        return
    for e in target:
        print("=" * 64)
        print("归零事件全景 · %s" % e.get("event_id"))
        print("-" * 64)
        print("标题         : %s" % e.get("title"))
        print("登记         : owner=%s | domain=%s | severity=%s | intent=%s | f13=%s"
              % (e.get("owner"), e.get("domain"), e.get("severity"),
                 e.get("intent_route"), e.get("f13_confidence")))
        print("状态机(spine): %s" % e.get("status"))
        print("当前阶段      : %s" % e.get("current_stage"))
        print("来源         : %s" % e.get("source_ref"))
        rf = e.get("reuse_features")
        if rf:
            print("复用向量(D7) : industry=%s | crisis_type=%s | tools=%s | standards=%s"
                  % (rf.get("industry"), rf.get("crisis_type"), rf.get("tools"), rf.get("standards")))
        for dk in ("D2_生命周期", "D3_能力层覆盖", "D5_闭环门禁",
                   "D6_沉淀", "D7_复用", "D8_复发", "D9_观测", "D10_治理闭环"):
            if dk in e.get("dimensions", {}):
                print("  %s: %s" % (dk, e["dimensions"][dk]))
        print("审计轨迹      : %s" % e.get("audit_trail"))
    print("=" * 64)


def _sim(a, b):
    """§9.4 同类问题复用相似度：crisis_type 50% + industry 30% + (tools+standards)/2 20%（0-1）。

    #61 扩展：当双方 reuse_features 含 spread_targets（水平展开推广对象：product/process/line/supplier）
    时，在 §9.4 基准上叠加 15% 推广目标相似度（base*0.85 + spread_sim*0.15），使「水平展开语义」可计量；
    无 spread_targets 时严格保持 §9.4 原值（向后兼容）。
    """
    if not a or not b:
        return 0.0
    crisis = 1.0 if a.get("crisis_type") and a["crisis_type"] == b.get("crisis_type") else 0.0
    ind = 1.0 if a.get("industry") and a["industry"] == b.get("industry") else 0.0
    ta, tb = set(a.get("tools", []) or []), set(b.get("tools", []) or [])
    sa, sb = set(a.get("standards", []) or []), set(b.get("standards", []) or [])
    tool_sim = (len(ta & tb) / len(ta | tb)) if (ta | tb) else 0.0
    std_sim = (len(sa & sb) / len(sa | sb)) if (sa | sb) else 0.0
    base = 0.5 * crisis + 0.3 * ind + 0.2 * ((tool_sim + std_sim) / 2.0)
    pa, pb = set(a.get("spread_targets", []) or []), set(b.get("spread_targets", []) or [])
    # #61：仅当双方均含 spread_targets（水平展开推广对象）才叠加推广相似度，
    #      单侧缺失则保持 §9.4 原值（避免单侧缺失被 base*0.85 误惩罚）
    if pa and pb:
        spread_sim = (len(pa & pb) / len(pa | pb)) if (pa | pb) else 0.0
        return round(base * 0.85 + spread_sim * 0.15, 3)
    return round(base, 3)


def match_reuse(event_id, apply=False):
    """M3：按 §9.4 同类问题复用算法计算目标事件与注册表其他事件的相似度，回填 D7_复用。"""
    reg = load_registry()
    events = reg.get("events", [])
    target = next((e for e in events if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    rf = target.get("reuse_features", {})
    hits = []
    for e in events:
        if e.get("event_id") == event_id:
            continue
        s = _sim(rf, e.get("reuse_features", {}))
        if s >= 0.3:
            hits.append({"event_id": e["event_id"], "similarity": s,
                         "level": "高" if s >= 0.7 else ("中" if s >= 0.5 else "低")})
    hits.sort(key=lambda h: h["similarity"], reverse=True)
    d7 = target.setdefault("dimensions", {}).setdefault("D7_复用", {})
    d7["similarity_hits"] = hits
    d7["reuse_rate"] = round(sum(h["similarity"] for h in hits) / len(hits), 3) if hits else 0.0
    reg["meta"]["updated_at"] = now()
    if apply:
        save_registry(reg)
        print("✅ %s 复用匹配 %d 命中（§9.4 · crisis50/ind30/tools+std20）：" % (event_id, len(hits)))
        for h in hits:
            print("   - %s · sim=%.2f · %s" % (h["event_id"], h["similarity"], h["level"]))
        return True
    print("[dry-run] %s 复用匹配 %d 命中，未写回 registry（须 --apply）" % (event_id, len(hits)))
    return True


# ============ A1 只读复用查询（S1 建议层 · 路由热路径调用 · 不写回 registry） ============
def extract_query_features(text: str) -> dict:
    """从查询文本提取复用特征（零新增词表，复用 registry reuse_features 反查）。

    匹配词典 = 各已登记事件 reuse_features：industry 取 '/' 末段、crisis_type 取完整串（含 '-' 末段）、
    tools/standards 取列表元素 → 任一词出现在 text 即视为命中该特征维度。
    防御降级：registry 不可读 → 返回空特征（不影响路由）。
    """
    feats = {"industry": set(), "crisis_type": set(), "tools": set(), "standards": set(), "spread_targets": set()}
    try:
        reg = load_registry()
    except Exception:
        return {k: ("" if k in ("industry", "crisis_type") else []) for k in feats}
    text_low = text.lower()
    for e in reg.get("events", []):
        rf = e.get("reuse_features", {}) or {}
        ind = (rf.get("industry") or "")
        for k in (ind.split("/") if "/" in ind else [ind]):
            if k and k.lower() in text_low:
                feats["industry"].add(ind)
        ct = (rf.get("crisis_type") or "")
        if ct and ct.lower() in text_low:
            feats["crisis_type"].add(ct)
        for t in (rf.get("tools") or []):
            if t and t.lower() in text_low:
                feats["tools"].add(t)
        for s in (rf.get("standards") or []):
            if s and s.lower() in text_low:
                feats["standards"].add(s)
        for st in (rf.get("spread_targets") or []):   # #61：水平展开推广对象亦作特征反查
            if st and st.lower() in text_low:
                feats["spread_targets"].add(st)
    return {
        "industry": next(iter(feats["industry"]), ""),
        "crisis_type": next(iter(feats["crisis_type"]), ""),
        "tools": list(feats["tools"]),
        "standards": list(feats["standards"]),
        "spread_targets": list(feats["spread_targets"]),
    }


def query_reuse(features: dict, min_sim: float = 0.5) -> list:
    """A1 只读复用查询：给定查询特征向量，返回注册表中可复用同类事件（**不写回 registry**）。

    与写回型 match_reuse 语义分离（解决 GAP-QE-r2）：
      - 纯只读（load_registry 不 save_registry）→ 路由热路径安全调用
      - 状态机前置（解决 GAP-QE-r4）：仅 status in (deposited/reused/resolved) 参与，
        未闭环事件(registered/analyzing/correcting/verified) 不可被建议复用
      - 返回 [{event_id, similarity, level, title, archive_ref}]
    """
    reg = load_registry()
    allow = {"deposited", "reused", "resolved"}
    hits = []
    for e in reg.get("events", []):
        if e.get("status") not in allow:
            continue
        s = _sim(features, e.get("reuse_features", {}) or {})
        if s >= min_sim:
            d6 = e.get("dimensions", {}).get("D6_沉淀", {})
            cr = resolve_case_ref(e.get("event_id"))
            hits.append({
                "event_id": e.get("event_id"),
                "similarity": s,
                "level": "高" if s >= 0.7 else ("中" if s >= 0.5 else "低"),
                "title": e.get("title", ""),
                "archive_ref": d6.get("archive_ref", ""),
                "case_ref": cr["anchor_id"] if cr else "",
            })
    hits.sort(key=lambda h: h["similarity"], reverse=True)
    return hits


def suggest_reuse(text: str, min_sim: float = 0.5) -> list:
    """A1 封装：提取查询特征 → query_reuse（只读 · 供 router.route() ①危机处置热路径调用）。"""
    return query_reuse(extract_query_features(text), min_sim)


# ============ A3/resolver：event_id → cases.md 锚点段（审核/水平展开案例输入真源解析） ============
def resolve_case_ref(event_id):
    """event_id → cases.md 锚点段（id: case-ze-qe2026-00X）。

    供 route 命中后回指 cases.md 真源（S1 建议层 · 不写回）。
    返回 {anchor_id, title, pointer} 或 None（未找到/解析失败防御降级）。
    """
    try:
        cases_path = SKILL_ROOT / "references/scenarios/cases.md"
        if not cases_path.exists():
            return None
        lines = cases_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    ev = event_id.lower().replace("qe-", "qe")
    anchor = "case-ze-" + ev
    for i, line in enumerate(lines):
        if anchor in line:
            title, pointer = "", ""
            for nxt in lines[i:i + 30]:
                if nxt.startswith("#") and not title:
                    title = nxt.lstrip("#").strip()
                if "🔗" in nxt or "已注册归零事件" in nxt:
                    pointer = nxt.strip()
            return {"anchor_id": anchor, "title": title, "pointer": pointer}
    return None


def register_recurrence(event_id, increment=1, apply=False):
    """M2：复发自动计数 + AO-4（复发预防）路由触发。"""
    reg = load_registry()
    target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    d8 = target.setdefault("dimensions", {}).setdefault("D8_复发", {})
    d8["recurrence_count"] = d8.get("recurrence_count", 0) + increment
    d8["ao4_trigger"] = d8["recurrence_count"] >= 2
    if d8["ao4_trigger"]:
        target["intent_route"] = "②流程优化"
        target["current_stage"] = "复发预防"
    target.setdefault("audit_trail", []).append(
        {"at": now(), "action": "recurrence", "count": d8["recurrence_count"], "ao4": d8["ao4_trigger"]})
    reg["meta"]["updated_at"] = now()
    if apply:
        save_registry(reg)
        print("✅ %s 复发计数→%d · AO-4 触发=%s" % (event_id, d8["recurrence_count"], d8["ao4_trigger"]))
        return True
    print("[dry-run] %s 复发计数→%d，未写回 registry（须 --apply）" % (event_id, d8["recurrence_count"]))
    return True


def sign_review(event_id, layer, apply=False):
    """H1：责任层签名（闭环门禁 review_layers_signed 累加）。"""
    reg = load_registry()
    target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    d5 = target.setdefault("dimensions", {}).setdefault("D5_闭环门禁", {})
    signed = d5.setdefault("review_layers_signed", [])
    if layer not in signed:
        signed.append(layer)
    reg["meta"]["updated_at"] = now()
    if apply:
        save_registry(reg)
        print("✅ %s 责任层签名：%s（已签 %s）" % (event_id, layer, "、".join(signed)))
        return True
    print("[dry-run] %s 责任层签名：%s，未写回 registry（须 --apply）" % (event_id, layer))
    return True


def verify_effectiveness(event_id, by=None, at=None, evidence=None, apply=False):
    """H1：有效性验证置位（闭环门禁 gate A · 原缺口 G5 补全）。

    置位 effectiveness_verified.ok=true；可选审计附加 by/at/evidence（代码不校验、仅存证）。
    写回：须 --apply 互锁（红线：与 --spread/--sign 同构的 --apply 门控写回入口）。
    闭环：gate_close 仅校验 .ok；本 setter 使门禁 A 不再依赖手改 YAML（闭合 G5 红线缺口）。
    """
    reg = load_registry()
    target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    d5 = target.setdefault("dimensions", {}).setdefault("D5_闭环门禁", {})
    ev = d5.setdefault("effectiveness_verified", {})
    ev["ok"] = True
    if by:
        ev["verified_by"] = by
    if at:
        ev["verified_at"] = at
    if evidence:
        ev["evidence"] = evidence
    target.setdefault("audit_trail", []).append(
        {"at": now(), "action": "verify_effectiveness", "ok": True,
         "by": by, "via": "CLI-apply" if apply else "CLI-dryrun"})
    reg["meta"]["updated_at"] = now()
    if apply:
        save_registry(reg)
        extra = (" · 责任人=%s" % by) if by else ""
        print("✅ %s 有效性验证通过（ok=true%s · 闭环门禁 gate A 已就绪）" % (event_id, extra))
        return True
    print("[dry-run] %s 有效性验证将置 ok=true，未写回 registry（须 --apply）" % event_id)
    return True


def gate_close(event_id, target=None):
    """H1：闭环门禁实体化——verified 须 effectiveness_verified.ok 且水平展开 ok 且责任层全签。

    target 可选：传入已修改的内存事件（如 close_deposit dry-run），避免重新读盘导致
    刚写入的 D5 不可见（否则 dry-run 门禁预测失真）。缺省则从 registry 重新加载。
    """
    reg = None
    if target is None:
        reg = load_registry()
        target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    d5 = target.get("dimensions", {}).get("D5_闭环门禁", {})
    reasons = []
    if not d5.get("effectiveness_verified", {}).get("ok"):
        reasons.append("有效性未验证(effectiveness_verified.ok=false)")
    # #61：水平展开确认（h6_spread 规范字段；legacy horizontal_deployed 兼容）
    spread = d5.get("h6_spread") or d5.get("horizontal_deployed") or {}
    if not spread.get("ok"):
        reasons.append("水平展开未确认(h6_spread.ok=false)")
    layers = d5.get("review_layers", []) or []
    signed = set(d5.get("review_layers_signed", []) or [])
    missing = [l for l in layers if l not in signed]
    if missing:
        reasons.append("责任层未全签：缺 %s" % "、".join(missing))
    ok = len(reasons) == 0
    print("%s 闭环门禁：%s%s" % (event_id, "✅ 通过" if ok else "❌ 未通过",
          "" if ok else "（" + "；".join(reasons) + "）"))
    return ok


def retire(event_id, apply=False):
    """H3：状态机整合 R4R——registered→…→retired（案例资产交 scripts/asset_retirement.py 退休环）。"""
    reg = load_registry()
    target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    target["status"] = "retired"
    target.setdefault("audit_trail", []).append(
        {"at": now(), "action": "retire", "via": "R4R-bridge",
         "note": "案例资产交 asset_retirement.py 退休环（new→observing→retire_candidate→retired）"})
    reg["meta"]["updated_at"] = now()
    if apply:
        save_registry(reg)
        _bridge_retire_r4r(event_id)   # #68-A 逻辑层桥接 R4R 观察环（仅登记 observe · 非物理 mv）
        print("✅ %s 状态→retired（R4R 桥接：相关案例资产纳入资产退休环观察）" % event_id)
        return True
    print("[dry-run] %s 状态→retired，未写回 registry（须 --apply）" % event_id)
    return True


def _bridge_retire_r4r(event_id):
    """#68-A：retire 逻辑层桥接 R4R 观察环（仅登记 observe，不物理 mv）。

    在 asset_retirement.json observe 登记 ze|{event_id}（source="zero_event"），
    使逻辑 retired 状态与 R4R 观察环对账可见（闭环 #67 infer_retire_sync）。
    隔离命名空间：source="zero_event" → R4R --retire 按文件名 stem 查找不匹配 event_id，
    不触发物理 mv；observe() 清理循环（#68-B）跳过该 source 防 stale_passed 污染。
    """
    try:
        import asset_retirement as ar
    except Exception:
        return False
    st = ar._load_state()
    obs = st.setdefault("observe", {})
    key = "ze|%s" % event_id
    if key in obs:
        return True  # 幂等
    from datetime import timedelta
    today = datetime.now().date().isoformat()
    due = (datetime.now().date() + timedelta(days=ar.OBSERVE_DAYS)).isoformat()
    obs[key] = {"stem": event_id, "source": "zero_event",
                "since": today, "review_due": due, "status": "retire_candidate"}
    ar._save(st)
    return True


def deposit(event_id, apply=False):
    """将事件状态推进至 deposited（D6 沉淀资产化后置位 · 闭环门禁通过后释放复用价值）。

    前置：须 gate_close 三判据全过（effectiveness_verified.ok + 水平展开 ok + 责任层全签），
    否则拒绝（防误推 · 对应前评 C1 / #51 弱推演边界）。
    写回：须 --apply 互锁（红线：写回须 --apply + R3 互锁）。
    """
    reg = load_registry()
    target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    if not gate_close(event_id):
        print("❌ 闭环门禁未通过，禁止 deposit（须 effectiveness_verified + 水平展开 + 责任层全签）")
        return False
    target["status"] = "deposited"
    target["current_stage"] = "沉淀资产化"
    target.setdefault("audit_trail", []).append(
        {"at": now(), "action": "deposit", "via": "R4R-deposit",
         "note": "D6 沉淀资产化完成 · 释放 reuse_suggest 候选（query_reuse 状态门纳入）"})
    # C5-P4 · G-CULT-3/G-STD-3：deposit 后提示语料化检入（路由感知 · 不自动直写·守红线）
    _tags = _route_tags(target)
    if _tags:
        print("ℹ️ 路由命中语料意图（tags=%s）：可运行 `python core/zero_event.py --enroll %s --apply` "
              "完成语料化检入（须 --apply 门禁）" % (_tags, event_id))
    reg["meta"]["updated_at"] = now()
    if apply:
        save_registry(reg)
        print("✅ %s 状态→deposited（闭环门禁已通过 · D6 沉淀资产化完成 · 复用候选已释放）" % event_id)
        return True
    print("[dry-run] %s 闭环门禁已通过，将置位 deposited；未写回 registry（须 --apply）" % event_id)
    return True


def close_deposit(event_id, payload=None, apply=False):
    """#63 闭包：原子写入 D5 闭环门禁三判据 → gate_close 通过 → 置位 deposited（须 --apply）。

    仅暴露「责任方填证的业务真值」写入入口（红线：业务真值由责任方填，agent 不代填/不伪造）。
    payload 经 --json 传入（来自 HTML 填写表单），结构：
      {"effectiveness_verified": {"ok": true, "verified_by": str, "verified_at": str, "evidence": str},
       "h6_spread": {"ok": true, "targets": [str,...]},
       "review_layers": [str,...],
       "review_layers_signed": [str,...]}
    - review_layers 缺失则不改动（保留既有）；review_layers_signed 须为 review_layers 子集（防越签）。
    - 写回：须 --apply 互锁；dry-run 仅报告将要写入内容 + 门禁预测，不写回。
    """
    reg = load_registry()
    target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    d5 = target.setdefault("dimensions", {}).setdefault("D5_闭环门禁", {})
    p = payload or {}
    # 仅当显式出现在 payload 才写入（空 payload → 门禁保持未通过 → deposit 拒绝，防空表单越权闭环）
    if "effectiveness_verified" in p:
        ev_in = p["effectiveness_verified"] or {}
        ev = d5.setdefault("effectiveness_verified", {})
        ev["ok"] = bool(ev_in.get("ok", True))
        for k in ("verified_by", "verified_at", "evidence"):
            if ev_in.get(k) is not None:
                ev[k] = ev_in[k]
    if "h6_spread" in p:
        sp_in = p["h6_spread"] or {}
        d5["h6_spread"] = {"targets": sp_in.get("targets", []) or [], "ok": bool(sp_in.get("ok", True))}
    if "review_layers" in p and p["review_layers"]:
        d5["review_layers"] = list(p["review_layers"])
    if "review_layers_signed" in p and p["review_layers_signed"]:
        base = set(d5.get("review_layers", []) or [])
        d5["review_layers_signed"] = [s for s in p["review_layers_signed"] if (not base or s in base)]
    target.setdefault("audit_trail", []).append(
        {"at": now(), "action": "close_deposit_fill", "via": "HTML-form",
         "note": "D5 闭环门禁三判据填证（业务真值由责任方填·agent 不代填）"})
    reg["meta"]["updated_at"] = now()
    if not apply:
        print("[dry-run] %s 将写入 D5 闭环门禁三判据，未写回 registry（须 --apply）" % event_id)
        _ev = d5.get("effectiveness_verified", {}) or {}
        print("  有效性: ok=%s | 责任人=%s | 日期=%s" % (_ev.get("ok"), _ev.get("verified_by"), _ev.get("verified_at")))
        _sp = d5.get("h6_spread", {}) or {}
        print("  水平展开: ok=%s | 推广对象=%s" % (_sp.get("ok"), _sp.get("targets")))
        print("  责任层: %s | 已签: %s" % (d5.get("review_layers"), d5.get("review_layers_signed")))
        gate_close(event_id, target=target)
        return True
    save_registry(reg)
    print("✅ %s D5 闭环门禁三判据已写入（业务真值·--apply 门禁）" % event_id)
    return deposit(event_id, apply=True)


def record_spread(event_id, targets=None, ok=False, apply=False):
    """#61：记录水平展开证据（h6_spread）— 推广对象清单（product/process/line/supplier）。

    写回：须 --apply 互锁（红线）。gate_close 以 h6_spread.ok 作为水平展开确认判据。
    """
    reg = load_registry()
    target = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if target is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    d5 = target.setdefault("dimensions", {}).setdefault("D5_闭环门禁", {})
    d5["h6_spread"] = {"targets": targets or [], "ok": ok}
    target.setdefault("audit_trail", []).append(
        {"at": now(), "action": "spread", "targets": targets or [], "ok": ok})
    reg["meta"]["updated_at"] = now()
    if apply:
        save_registry(reg)
        print("✅ %s 水平展开证据已记录（推广目标 %d · ok=%s）" % (event_id, len(targets or []), ok))
        return True
    print("[dry-run] %s 水平展开证据将记录（推广目标 %d），未写回 registry（须 --apply）" % (event_id, len(targets or [])))
    return True


def infer_depositable():
    """#62-A：自动推演 deposited 就绪态（只读·S1 建议层）。

    扫描注册表事件，判定哪些已满足 gate_close 三判据（effectiveness_verified.ok
    + 水平展开 h6_spread.ok + review_layers 全签）且尚未 deposited，返回就绪事件清单。
    纯只读：不写回；推进须人工 `deposit(event_id, apply=True)`（--deposit --apply）。
    与 deposit() 的 gate_close 判据同源，但不触发 print / 不 save_registry。
    """
    reg = load_registry()
    ready = []
    for e in reg.get("events", []):
        eid = e.get("event_id")
        if e.get("status") in ("deposited", "reused", "resolved", "retired"):
            continue
        d5 = e.get("dimensions", {}).get("D5_闭环门禁", {})
        eff = d5.get("effectiveness_verified", {}).get("ok")
        spread = (d5.get("h6_spread") or d5.get("horizontal_deployed") or {}).get("ok")
        layers = d5.get("review_layers", []) or []
        signed = set(d5.get("review_layers_signed", []) or [])
        missing = [l for l in layers if l not in signed]
        if eff and spread and not missing:
            ready.append(eid)
    return ready


def infer_retire_sync():
    """#67：零事件 retire/resolved 状态 ↔ R4R 观察环 只读对账（#62 残留缺口可观测化）。

    遍历 registry 中 status∈{retired,resolved} 事件，对照 asset_retirement 状态机的
    observe 记录，检测"逻辑已退休但 R4R 未纳入观察"的断裂项。零写回，仅 S1 建议层报告。
    """
    import re as _re
    try:
        import asset_retirement as ar
    except Exception:
        ar = None
    reg = load_registry()
    events = reg.get("events", [])
    retired = [e for e in events if e.get("status") in ("retired", "resolved")]
    if not retired:
        print("零事件 retire/resolved ↔ R4R 观察环 对账（只读）：")
        print("  （无 retired/resolved 事件 · 无需桥接 R4R 观察环）")
        return []
    observed_ids = set()
    if ar is not None:
        st = ar._load_state()
        for v in st.get("observe", {}).values():
            blob = "%s %s" % (v.get("stem", ""), v.get("note", ""))
            for m in _re.findall(r"QE-2026-\d+", blob):
                observed_ids.add(m)
    synced, broken = [], []
    for e in retired:
        eid = e.get("event_id")
        (synced if eid in observed_ids else broken).append(eid)
    print("零事件 retire/resolved ↔ R4R 观察环 对账（只读）：")
    print("  已桥接(%d)：%s" % (len(synced), synced or "无"))
    print("  断裂(%d)：%s" % (len(broken), broken or "无"))
    if broken:
        print("  ⚠️  断裂项：逻辑层已退休但 R4R 观察环无记录（须 #68 桥接或人工 --retire 核准）")
    return broken


# ---------------------------------------------------------------------------
# C5 · event 语料化检入统一闭环（route-aware enroll_corpus）
# ---------------------------------------------------------------------------
# 四层资产模型：data/zero_events.yaml(P0·真源·excluded) ⊕ sources/events/(P2·原始证据·corpus)
#   ⊕ scenarios/events/(P3·归一化入口·corpus) ⊕ index/(索引)。
# event_id 为跨层唯一主键；P0 单向派生 P3、P2 单向支撑 P0；检索仅触 P2/P3。
# 状态门：仅 {deposited,reused,resolved} 可入 corpus（对齐 query_reuse 状态门 · G-EVT-3）。
# 索引：per-event 小文件 <30KB 不被 auto_checkin 收录（G-EVT-2）→ 显式 gen_index 绕过。
# 红线：写回（scenarios 文件 + manifest 登记）须 apply=True 门控；不代填业务真值 / 不伪造签名。
# ---------------------------------------------------------------------------

# 路由 → 语料 tag 映射（G-UNI-1 · route-aware，非写死⑥）
ROUTE_TAG_MAP = {
    "②": ["standard", "流程治理"],       # 标准化/流程优化 → D6.standard_ref
    "③": ["audit", "评估审计"],          # 评估审计/源流回馈 → D8.feedback_to_source
    "⑤": ["spread", "知识沉淀"],         # 水平展开/知识沉淀 → D5.h6_spread
    "⑥": ["culture", "质量文化"],        # 文化教育/案例宣传 → D10.culture_education
}

# 可语料化检入的状态集（对齐 query_reuse 状态门）
_ENROLL_ALLOW = {"deposited", "reused", "resolved"}

SCENARIOS_EVENTS_DIR = SKILL_ROOT / "references" / "scenarios" / "events"
SOURCES_EVENTS_DIR = SKILL_ROOT / "references" / "sources" / "events"


def _route_tags(ev: dict) -> list:
    """G-UNI-1：由 event 维度/路由推断语料 tag 集（route-aware，②/③/⑤/⑥ 多意图派发）。

    优先读 intent_route / corpus_intent；否则由维度存在性回退推断：
      D10.culture_education 存在 → ⑥ culture；D6.standard_ref 存在 → ② standard；
      D8.feedback_to_source 存在 → ③ feedback；D5.h6_spread/horizontal_deployed 存在 → ⑤ spread。
    去重保序。
    """
    tags = []
    dims = ev.get("dimensions", {})
    intent = ev.get("intent_route") or ev.get("corpus_intent") or ""
    if intent:
        for k, v in ROUTE_TAG_MAP.items():
            if k in intent or any(tok in intent for tok in v):
                tags.extend(v)
    d10 = dims.get("D10_治理闭环", {}) or {}
    if d10.get("culture_education"):
        tags.extend(ROUTE_TAG_MAP["⑥"])
    if (dims.get("D6_沉淀", {}) or {}).get("standard_ref"):
        tags.extend(ROUTE_TAG_MAP["②"])
    if (dims.get("D8_复发", {}) or {}).get("feedback_to_source"):
        tags.extend(ROUTE_TAG_MAP["③"])
    _h = (dims.get("D5_闭环门禁", {}) or {}).get("h6_spread") or \
         (dims.get("D5_闭环门禁", {}) or {}).get("horizontal_deployed")
    if _h:
        tags.extend(ROUTE_TAG_MAP["⑤"])
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _build_corpus_block(ev: dict) -> str:
    """生成归一化 corpus 入口块（id + tags + 🔗回链 + 四固定子结构）。纯函数（不 IO）· G-EVT-5。"""
    eid = ev.get("event_id", "?")
    title = ev.get("title", eid)
    tags = _route_tags(ev) or ["internal"]
    intent = ev.get("intent_route") or ev.get("corpus_intent") or "未指定"
    domain = ev.get("domain", "未指定")
    severity = ev.get("severity") or (ev.get("D1_登记", {}) or {}).get("severity", "未指定")
    status = ev.get("status", "registered")
    src_lines = ""
    if SOURCES_EVENTS_DIR.exists():
        for p in sorted(SOURCES_EVENTS_DIR.glob("%s_*.md" % eid)):
            src_lines += "\n- 🔗 原始证据: references/sources/events/%s" % p.name
    d5 = (ev.get("dimensions", {}) or {}).get("D5_闭环门禁", {}) or {}
    eff = (d5.get("effectiveness_verified") or {}).get("ok")
    spread = ((d5.get("h6_spread") or d5.get("horizontal_deployed")) or {}).get("ok")
    b = [
        "# %s · 归零事件资产化入口" % eid, "",
        "<!-- id: case-ze-%s; tags: %s -->" % (eid, ", ".join(tags)), "",
        "> 本块由 `enroll_corpus` 自动派生（只读回链 · 真源唯一）；状态: %s · 路由: %s" % (status, intent), "",
        "## 核心画像",
        "- 标题: %s" % title,
        "- 领域: %s · 严重度: %s" % (domain, severity),
        "- 路由意图: %s" % intent,
        "- 关联标签: %s" % (", ".join(tags) or "（无）"), "",
        "## 治理闭环",
        "- 有效性验证: %s" % ("已验证" if eff else "未验证"),
        "- 水平展开: %s" % ("已展开" if spread else "未展开"), "",
        "## 可借鉴点",
        "- （由 D6 沉淀 / D7 复用特征填充；deposit 后 enrich）", "",
        "## 来源",
        "- 🔗 真源(唯一可写): references/data/zero_events.yaml#%s" % eid,
    ]
    if src_lines:
        b.append(src_lines)
    b.append("")
    return "\n".join(b) + "\n"


def _gen_event_index(rel: str, note: str, apply: bool = True) -> bool:
    """显式为 event 小文件生成锚点索引 + 登记进 manifest corpus 段（绕 30KB 自动跳过 · G-EVT-2）。

    apply=False 仅报告（dry-run）；apply=True 写 index yaml + manifest。
    """
    try:
        from gen_corpus_index import gen_index, _dump_manifest
        from corpus_manifest import load_manifest
    except Exception as ex:  # pragma: no cover
        print("⚠ _gen_event_index 依赖导入失败：%s" % ex)
        return False
    if not apply:
        print("  [dry] 将为 %s 生成索引 + 登记 manifest（须 --apply）" % rel)
        return False
    gen_index(rel, note)
    m = load_manifest()
    corpus = list(m.get("corpus", []))
    if any(e["rel"] == rel for e in corpus):
        return True  # 已登记，跳过
    corpus.append({"rel": rel, "level": "chapter", "group": "事件证据族",
                   "freq": "low", "note": note})
    m["corpus"] = corpus
    _dump_manifest(m)
    print("✅ 已登记 corpus: %s" % rel)
    return True


def enroll_corpus(event_id, apply=False):
    """C5：将已 deposited 事件语料化检入（归一化入口→scenarios/events + 索引 + manifest）。

    状态门：仅 {deposited,reused,resolved}（G-EVT-3，对齐 query_reuse）。
    写入：scenarios/events/<id>.md（归一化块，route-aware tags）+ manifest corpus 登记 + gen_index（绕 30KB · G-EVT-2）。
    写回须 apply=True（红线）；dry-run 仅报告并返回 False（未写）。
    """
    reg = load_registry()
    ev = next((e for e in reg.get("events", []) if e.get("event_id") == event_id), None)
    if ev is None:
        print("❌ 未找到事件：%s" % event_id)
        return False
    status = ev.get("status")
    if status not in _ENROLL_ALLOW:
        print("❌ 状态门拦截：%s 状态=%s（仅 %s 可语料化检入 · G-EVT-3）"
              % (event_id, status, sorted(_ENROLL_ALLOW)))
        return False
    rel = "references/scenarios/events/%s.md" % event_id
    target = SCENARIOS_EVENTS_DIR / ("%s.md" % event_id)
    block = _build_corpus_block(ev)
    if not apply:
        print("[dry-run] %s 满足状态门，将生成归一化入口 %s + 索引 + manifest 登记；未写回（须 --apply）"
              % (event_id, rel))
        return False
    SCENARIOS_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(block, encoding="utf-8")
    _gen_event_index(rel, "事件归零资产化入口（归一化·route-aware）", apply=True)
    ev.setdefault("audit_trail", []).append(
        {"at": now(), "action": "enroll_corpus", "via": "R4R-enroll",
         "note": "语料化检入（scenarios/events 入口+索引+manifest·route-aware）"})
    reg["meta"]["updated_at"] = now()
    save_registry(reg)
    print("✅ %s 语料化检入完成（入口=%s · 索引+manifest 已登记）" % (event_id, rel))
    return True


def index_event_sources(event_id, apply=False):
    """C5：显式索引 sources/events/<id>*.md 原始证据（绕 30KB · G-EVT-2）。

    classify 规则已使 /sources/events/ → corpus，但 per-event 小文件不被 auto_checkin 自动收录；
    须显式 gen_index + manifest 登记。apply=False 仅报告。
    """
    if not SOURCES_EVENTS_DIR.exists():
        print("⚠ 无 sources/events 目录（%s）" % SOURCES_EVENTS_DIR)
        return False
    files = sorted(SOURCES_EVENTS_DIR.glob("%s_*.md" % event_id))
    if not files:
        print("⚠ %s 无 sources/events 原始证据文件" % event_id)
        return False
    ok = True
    for p in files:
        rel = "references/sources/events/%s" % p.name
        if not apply:
            print("[dry-run] 将为 %s 生成索引 + 登记 manifest（须 --apply）" % rel)
            ok = False
            continue
        _gen_event_index(rel, "事件原始证据（corpus·事件证据族）", apply=True)
    return ok


def event_assets_stale():
    """C5：检测"真源(P0)变更但 corpus 入口(P3)/原始证据(P2)未重生"的滞后（G-EVT-1 缓解）。

    只读：比对 zero_events.yaml mtime vs scenarios/events/<id>.md vs sources/events/<id>_*.md。
    返回滞后 event_id 列表（供 enroll_corpus --apply / index_event_sources --apply 重生）。
    """
    reg = load_registry()
    p0_mt = REG.stat().st_mtime if REG.exists() else 0
    lag = []
    for ev in reg.get("events", []):
        eid = ev.get("event_id")
        if ev.get("status") not in _ENROLL_ALLOW:
            continue
        p3 = SCENARIOS_EVENTS_DIR / ("%s.md" % eid)
        p2s = sorted(SOURCES_EVENTS_DIR.glob("%s_*.md" % eid)) if SOURCES_EVENTS_DIR.exists() else []
        stale = (not p3.exists()) or (p3.exists() and p3.stat().st_mtime < p0_mt)
        if not stale and p2s:
            stale = any(p.stat().st_mtime < p0_mt for p in p2s)
        if stale:
            lag.append(eid)
    print("event 资产滞后检测（真源 vs corpus 入口/原始证据）：")
    if lag:
        for eid in lag:
            print("  ⚠ %s 滞后（须 enroll_corpus --apply 重生 P3 / index_event_sources --apply 索引 P2）" % eid)
    else:
        print("  ✅ 无滞后（已 deposited 事件的 corpus 入口与原始证据均最新）")
    return lag


def plan():
    cfg = load_config()
    print("归零事件全景维度子模块 · 体系化规划（QCM sub-module）")
    print("=" * 64)
    print("默认状态      : enabled=%s（默认关闭：不挂 nightrun、不自动记录）" % cfg.get("enabled"))
    print("触发协议      : 用户主动 `--trigger` → 实施记录；`--enable/--disable` 持久开关")
    print("状态机 spine  : open → registered → analyzing → correcting → verified → deposited → reused → resolved/retired")
    print("闭环门禁      : verified 须 effectiveness_verified.ok==true 且 review_layers 全签")
    print("全景维度 ZE-PDM（10 维）：")
    for d in cfg.get("dimensions", {}):
        print("  - %s: %s" % (d, cfg["dimensions"][d]))
    print("=" * 64)


def set_enabled(v):
    cfg = load_config()
    cfg["enabled"] = v
    save_config(cfg)
    print("✅ 归零事件子模块 enabled=%s（%s）"
          % (v, "已开启·可常驻记录" if v else "已关闭·仅 --trigger 显式记录"))


def status():
    cfg = load_config()
    reg = load_registry()
    print("enabled=%s | 已登记事件数=%d | registry=%s"
          % (cfg.get("enabled"), len(reg.get("events", [])), REG))


def main():
    ap = argparse.ArgumentParser(description="归零事件全景维度子模块（QCM）")
    ap.add_argument("--plan", action="store_true", help="打印体系化规划")
    ap.add_argument("--trigger", action="store_true", help="用户主动触发·记录事件")
    ap.add_argument("--json", help="事件 JSON（--trigger 时必填）")
    ap.add_argument("--panorama", nargs="?", const="__all__", default=None, help="全景视图 [event_id]")
    ap.add_argument("--enable", action="store_true", help="持久开启")
    ap.add_argument("--disable", action="store_true", help="持久关闭")
    ap.add_argument("--status", action="store_true", help="状态")
    ap.add_argument("--force", action="store_true", help="默认关闭时仍显式记录（与 --trigger 同义安全提示）")
    ap.add_argument("--apply", action="store_true", help="写回门禁：实际持久化写 registry（缺省为 dry-run 仅报告不写回）")
    # M2/M3/H1/H3 闭环操作（默认关闭下仍可对已登记事件执行，report-only 友好）
    ap.add_argument("--recur", metavar="EVENT", help="M2 复发计数+1（达 2 触发 AO-4）")
    ap.add_argument("--match", metavar="EVENT", help="M3 复用相似度匹配（§9.4）")
    ap.add_argument("--sign", nargs=2, metavar=("EVENT", "LAYER"), help="H1 责任层签名")
    ap.add_argument("--verify", metavar="EVENT", help="H1 闭环门禁校验")
    ap.add_argument("--verify-effectiveness", metavar="EVENT",
                    help="H1 有效性验证置位(effectiveness_verified.ok=true · --apply 写回 · 闭合 G5)")
    ap.add_argument("--by", help="有效性验证责任人(配合 --verify-effectiveness)")
    ap.add_argument("--at", help="验证日期 YYYY-MM-DD(配合 --verify-effectiveness)")
    ap.add_argument("--evidence", help="有效性验证证据(配合 --verify-effectiveness)")
    ap.add_argument("--retire", metavar="EVENT", help="H3 状态→retired（R4R 桥接）")
    ap.add_argument("--deposit", metavar="EVENT", help="状态→deposited（须 gate_close 三判据通过 · --apply 写回）")
    ap.add_argument("--close-deposit", metavar="EVENT", help="#63 闭包：原子填 D5 三判据→gate→deposited（--json 载荷·--apply 写回）")
    ap.add_argument("--spread", metavar="EVENT", help="#61 记录水平展开证据(h6_spread · --apply 写回)")
    ap.add_argument("--targets", help="水平展开推广对象(逗号分隔 · 配合 --spread)")
    ap.add_argument("--infer-deposit", action="store_true", help="#62-A 自动推演 deposited 就绪态（只读·S1 建议层）")
    ap.add_argument("--infer-retire-sync", action="store_true", help="#67 零事件 retire/resolved ↔ R4R 观察环 只读对账")
    ap.add_argument("--from-mil", metavar="FILE", help="P2-c MIL 行 JSON → mil_to_event → record（复用适配器·--apply 写回）")
    # C5 · event 语料化检入统一闭环
    ap.add_argument("--enroll", metavar="EVENT", help="C5 语料化检入（deposited 事件→scenarios/events 归一化入口 + 索引 + manifest · --apply 写回）")
    ap.add_argument("--index-sources", metavar="EVENT", help="C5 显式索引 sources/events 原始证据（绕 30KB · --apply 写回）")
    ap.add_argument("--stale", action="store_true", help="C5 检测 event 资产滞后（真源 vs corpus 入口/原始证据 · 只读）")
    args = ap.parse_args()

    if args.plan:
        plan()
        return
    if args.status:
        status()
        return
    if args.enable:
        set_enabled(True)
        return
    if args.disable:
        set_enabled(False)
        return
    if args.panorama is not None:
        panorama(None if args.panorama == "__all__" else args.panorama)
        return
    if args.retire:
        retire(args.retire, apply=args.apply)
        return
    if args.verify:
        gate_close(args.verify)
        return
    if args.sign:
        sign_review(args.sign[0], args.sign[1], apply=args.apply)
        return
    if args.verify_effectiveness:
        verify_effectiveness(args.verify_effectiveness, by=args.by, at=args.at,
                             evidence=args.evidence, apply=args.apply)
        return
    if args.match:
        match_reuse(args.match, apply=args.apply)
        return
    if args.recur:
        register_recurrence(args.recur, apply=args.apply)
        return
    if args.deposit:
        deposit(args.deposit, apply=args.apply)
        return
    if args.close_deposit:
        payload = None
        if args.json:
            try:
                payload = json.loads(args.json)
            except Exception as ex:
                print("❌ --json 解析失败：%s" % ex)
                sys.exit(2)
        close_deposit(args.close_deposit, payload=payload, apply=args.apply)
        return
    if args.spread:
        tgs = [t.strip() for t in (args.targets or "").split(",") if t.strip()]
        record_spread(args.spread, targets=tgs, ok=True, apply=args.apply)
        return
    if args.infer_deposit:
        ready = infer_depositable()
        print("自动推演 deposited 就绪事件（满足闭环门禁三判据·尚未 deposited · 只读建议）：")
        if ready:
            for eid in ready:
                print("  ✓ %s（可推进：zero_event.py --deposit %s --apply）" % (eid, eid))
        else:
            print("  （无就绪事件 · 须先补 effectiveness_verified + 水平展开 h6_spread + review_layers 责任层签名）")
        return
    if args.infer_retire_sync:
        broken = infer_retire_sync()
        sys.exit(0 if not broken else 1)
    if args.from_mil:
        ok = from_mil(args.from_mil, force=args.force, apply=args.apply)
        sys.exit(0 if ok else 1)
    if args.stale:
        lag = event_assets_stale()
        sys.exit(0 if not lag else 1)
    if args.enroll:
        enroll_corpus(args.enroll, apply=args.apply)
        return
    if args.index_sources:
        index_event_sources(args.index_sources, apply=args.apply)
        return
    if args.trigger:
        if not args.json:
            print("❌ --trigger 需 --json '<事件JSON>'")
            sys.exit(2)
        try:
            evt = json.loads(args.json)
        except Exception as ex:
            print("❌ JSON 解析失败：%s" % ex)
            sys.exit(2)
        ok = record(evt, force=args.force, apply=args.apply)
        sys.exit(0 if ok else 1)
    # 默认：展示规划
    plan()


if __name__ == "__main__":
    main()
