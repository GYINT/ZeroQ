#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MIL 管制表 ↔ zero_event 视图映射适配器（P1 · 纯函数 · 零写回）。

设计意图（承接 #63 图示 MIL 管制表映射 zero_event 可行性评估）：
- 把车间级台账「关键工序不良 MIL 管制表」的行记录，归一化为 zero_event 规范结构，
  作为其「前端录入视图 → 治理资产 spine」的转换层。
- **零写回**：本模块不 import record()/save_registry，不读写 zero_events.yaml，
  仅生成合规的事件 dict / 反向渲染 MIL 视图 dict。
- **不替代 schema**：直接替换 D5 判据会破坏 #59-#72 已稳定的 CLI 体系，故本适配器
  只做字段映射，**三道 deposit 门禁（A 有效性 / B 水平展开 / C 责任签名）均不置 ok**，
  生成的事件处于 registered 态、待业务按 --verify-effectiveness/--spread/--sign --apply 推进。
- 「图示」字段仅落 image_ref 占位（文件名/URL），真实图片存储属 P3 高·单独立项，不在本模块。

输入字段（canonical 英文 key，兼容中文表头别名）：
    no            NO
    code          代码        → event_id
    stage         阶段        → current_stage
    source        发生源      → domain（归一化 B设计/D现场/E供应）
    part_no       料号编号    → D2.part_number
    process       工序        → D2.process（+ 合成 title）
    status_now    现状        → D9.current_status
    image         图示        → D9.image_ref（占位）
    actual        实绩        → D9.actual
    target        目标        → D9.target
    risk_level    风险等级    → severity（归一化 重大危机/中度危机/普通）
    lot1/2/3      现象 Lot    → D2.lots[]
    root_cause    原因分析    → D2.root_cause
    corrective    改善措施    → D2.corrective_action
    complete_date 完成日期    → D5.effectiveness_verified.at（仅 at，不置 ok）
    owner         责任人      → owner（登记责任人）
    state         状态        → status（仅透传合法 spine 状态，否则 registered）
    feedback      源流回馈    → D8.feedback_to_source
    spread        水平展开    → D5.h6_spread.targets（仅 targets，不置 ok）
    review_layers 分层审核    → D5.review_layers（待签名单，不填 signed）
    culture       文化教育    → D10.culture_education
    standard      标准化      → D6.standard_ref
"""
from __future__ import annotations
import re

# 中文表头别名 → canonical key
_CN_ALIAS = {
    "NO": "no", "编号": "no",
    "代码": "code", "事件代码": "code",
    "阶段": "stage",
    "发生源": "source",
    "料号编号": "part_no", "料号": "part_no",
    "工序": "process",
    "现状": "status_now",
    "图示": "image",
    "实绩": "actual",
    "目标": "target",
    "风险等级": "risk_level", "风险": "risk_level",
    "Lot1": "lot1", "批次1": "lot1",
    "Lot2": "lot2", "批次2": "lot2",
    "Lot3": "lot3", "批次3": "lot3",
    "原因分析": "root_cause",
    "改善措施": "corrective", "改善对策": "corrective",
    "完成日期": "complete_date", "改善完成日期": "complete_date",
    "责任人": "owner",
    "状态": "state",
    "源流回馈": "feedback", "源流反馈": "feedback",
    "水平展开": "spread",
    "分层审核": "review_layers", "审核层级": "review_layers",
    "文化教育": "culture",
    "文化教育案例": "culture_case", "案例宣传": "culture_case", "文化案例": "culture_case",
    "标准化": "standard", "标准": "standard",
}

# 合法状态机 spine（zero_event.status 取值域）
_SPINE_STATES = {
    "open", "registered", "analyzing", "correcting",
    "verified", "deposited", "reused", "resolved", "retired",
}


def _normalize_keys(row: dict) -> dict:
    """把中文表头别名统一成 canonical key（原英文 key 保留）。"""
    out = {}
    for k, v in row.items():
        if k is None:
            continue
        ck = _CN_ALIAS.get(str(k).strip(), str(k).strip())
        out[ck] = v
    return out


def _norm_severity(v):
    if not v:
        return "普通"
    s = str(v).strip()
    if s in ("重大危机", "重大", "高", "严重", "high", "H", "A"):
        return "重大危机"
    if s in ("中度危机", "中度", "中", "medium", "M", "B"):
        return "中度危机"
    return "普通"


def _norm_domain(v):
    if not v:
        return ""
    s = str(v).strip()
    if "设计" in s:
        return "B设计"
    if any(w in s for w in ("现场", "产线", "车间", "制造", "D现场")):
        return "D现场"
    if any(w in s for w in ("供应商", "采购", "E供应")):
        return "E供应"
    return s


def _norm_status(v):
    if not v:
        return "registered"
    s = str(v).strip().lower()
    if s in _SPINE_STATES:
        return s
    # MIL 表常见业务态 → 安全回落 registered（不替业务判断 deposited）
    return "registered"


def _as_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [x for x in v if x not in (None, "")]
    if isinstance(v, str):
        # 支持逗号/顿号/分号分隔
        return [p.strip() for p in str(v).replace("；", ";").replace("、", ";").split(";") if p.strip()]
    return [v]


def _parse_batch_yield(v):
    """解析批次良率百分比（如 '98.5%' / '良率98.5' / '98.5' → 98.5）；解析失败返回 None。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def mil_to_event(mil_row: dict, source_ref: str = "") -> dict:
    """MIL 管制表一行 → zero_event 规范事件 dict（零写回 · 三判据未置 ok）。

    返回结构可直接喂给 zero_event.record(event, apply=...) 的 event 参数。
    """
    r = _normalize_keys(mil_row)
    code = (r.get("code") or "").strip()
    if not code:
        raise ValueError("MIL 行缺少「代码」(code) · 无法映射为 event_id")
    process = (r.get("process") or "").strip()
    status_now = (r.get("status_now") or "").strip()
    title = (r.get("title") or "").strip() or (f"{process}：{status_now}" if (process or status_now) else code)

    lots = [r.get(k) for k in ("lot1", "lot2", "lot3") if r.get(k) not in (None, "")]
    spread = _as_list(r.get("spread"))
    review_layers = _as_list(r.get("review_layers"))

    d2 = {
        "part_number": (r.get("part_no") or "").strip(),
        "process": process,
        "lots": lots,
        "root_cause": (r.get("root_cause") or "").strip(),
        "corrective_action": (r.get("corrective") or "").strip(),
    }
    d5 = {
        "effectiveness_verified": {
            "at": (r.get("complete_date") or "").strip(),  # 仅 at，不置 ok（门禁 A 未过）
        },
        "review_layers": review_layers,                   # 待签名单（门禁 C 未过）
        "review_layers_signed": [],                        # 不填签名（红线：不可伪造）
        "h6_spread": {
            "targets": spread,                             # 仅 targets，不置 ok（门禁 B 未过）
        },
        "horizontal_deployed": {"ok": False},
    }
    d6 = {
        "standard_ref": (r.get("standard") or "").strip(),
        "indexed": False,
        "corpus_ref": "",
        "corpus_type": "standard",
    }
    d8 = {
        "feedback_to_source": (r.get("feedback") or "").strip(),
        "recurrence_count": 0,
    }
    d9 = {
        "current_status": status_now,
        "actual": (r.get("actual") or "").strip(),
        "target": (r.get("target") or "").strip(),
        "metric": "批次良率",                              # 实绩/目标语义：批次良率（指令 2026-09-01）
        "actual_yield_pct": _parse_batch_yield(r.get("actual")),
        "target_yield_pct": _parse_batch_yield(r.get("target")),
        "image_ref": (r.get("image") or "").strip(),      # 仅占位（P3 附件能力单独立项）
    }
    d10 = {
        "culture_education": (r.get("culture") or "").strip(),
        "case_promotion": (r.get("culture_case") or "").strip(),  # 案例宣传质量文化（后续拓展·文化教育专项）
        "enrolled_as_corpus": False,
        "corpus_ref": "",
    }

    return {
        "event_id": code,
        "title": title,
        "owner": (r.get("owner") or "").strip(),
        "domain": _norm_domain(r.get("source")),
        "severity": _norm_severity(r.get("risk_level")),
        "intent_route": "①危机处置",
        "f13_confidence": None,
        "source_ref": source_ref,
        "current_stage": (r.get("stage") or "").strip() or "识别",
        "status": _norm_status(r.get("state")),
        "reuse_features": {},  # 可选由调用方 enrich（industry/crisis_type/tools/standards）
        "dimensions": {
            "D2_生命周期": d2,
            "D5_闭环门禁": d5,
            "D6_沉淀": d6,
            "D8_复发": d8,
            "D9_观测": d9,
            "D10_治理闭环": d10,
        },
    }


def mil_rows_to_events(rows: list, source_ref: str = "") -> list:
    """批量：MIL 行列表 → zero_event 事件 dict 列表（零写回）。"""
    return [mil_to_event(row, source_ref=source_ref) for row in rows]


def event_to_mil(event_dict: dict) -> dict:
    """反向渲染：zero_event 事件 dict → MIL 管制表视图 dict（含中文表头 key）。"""
    dims = event_dict.get("dimensions", {}) or {}
    d2 = dims.get("D2_生命周期", {}) or {}
    d5 = dims.get("D5_闭环门禁", {}) or {}
    d6 = dims.get("D6_沉淀", {}) or {}
    d8 = dims.get("D8_复发", {}) or {}
    d9 = dims.get("D9_观测", {}) or {}
    d10 = dims.get("D10_治理闭环", {}) or {}

    ev = d5.get("effectiveness_verified", {}) or {}
    h6 = d5.get("h6_spread", {}) or {}
    lots = d2.get("lots", []) or []
    review_layers = d5.get("review_layers", []) or []

    return {
        "NO": "",
        "代码": event_dict.get("event_id", ""),
        "阶段": event_dict.get("current_stage", ""),
        "发生源": event_dict.get("domain", ""),
        "料号编号": d2.get("part_number", ""),
        "工序": d2.get("process", ""),
        "现状": d9.get("current_status", ""),
        "图示": d9.get("image_ref", ""),
        "实绩": d9.get("actual", ""),
        "目标": d9.get("target", ""),
        "风险等级": event_dict.get("severity", ""),
        "Lot1": lots[0] if len(lots) > 0 else "",
        "Lot2": lots[1] if len(lots) > 1 else "",
        "Lot3": lots[2] if len(lots) > 2 else "",
        "原因分析": d2.get("root_cause", ""),
        "改善措施": d2.get("corrective_action", ""),
        "完成日期": ev.get("at", ""),
        "责任人": event_dict.get("owner", ""),
        "状态": event_dict.get("status", ""),
        "源流回馈": d8.get("feedback_to_source", ""),
        "水平展开": "、".join(h6.get("targets", []) or []),
        "分层审核": "、".join(review_layers),
        "文化教育": d10.get("culture_education", ""),
        "文化教育案例": d10.get("case_promotion", ""),
        "标准化": d6.get("standard_ref", ""),
        "标准化语料检入": ("已检入:%s" % d6.get("corpus_ref", "")) if d6.get("indexed") else "否",
        "文化语料检入": ("已检入:%s" % d10.get("corpus_ref", "")) if d10.get("enrolled_as_corpus") else "否",
    }


if __name__ == "__main__":
    import json
    import sys

    # 简易 CLI：从 JSON 文件读 MIL 行，输出 zero_event 事件 JSON（零写回 · 仅打印）
    if len(sys.argv) > 1:
        path = sys.argv[1]
        data = json.loads(open(path, encoding="utf-8").read())
        rows = data if isinstance(data, list) else [data]
        out = mil_rows_to_events(rows)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        # 演示
        demo = {
            "代码": "QE-2026-901", "阶段": "验证闭环", "发生源": "D现场冲压车间",
            "料号编号": "P-7712", "工序": "冲压清洗", "现状": "产品发白",
            "图示": "assets/qe-901-white.jpg", "实绩": "98.5%", "目标": "99.5%",
            "风险等级": "中", "Lot1": "L240801", "Lot2": "L240802",
            "原因分析": "脱脂温度不足", "改善措施": "升温至 65℃", "完成日期": "2026-09-10",
            "责任人": "工艺员甲", "状态": "进行中", "源流回馈": "修订 SOP",
            "水平展开": "同类产线A、供应商B", "分层审核": "工艺副总、质量部",
            "文化教育": "语料检入(⑥质量文化触发)", "文化教育案例": "文化宣传(可选衍生)", "标准化": "WI-CT-009",
        }
        ev = mil_to_event(demo)
        print(json.dumps(ev, ensure_ascii=False, indent=2))
        print("\n--- 反向渲染 MIL 视图 ---")
        print(json.dumps(event_to_mil(ev), ensure_ascii=False, indent=2))
