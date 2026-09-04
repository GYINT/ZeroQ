#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 全局对象域采样核心（V8.6 P0 · 采集出口归一化）

功能：record_usage(namespace, obj) 统一采样 API —— 采集出口归一化的核心设施。
     R8/R12 蓝图：4 适配器（tool/intent/domain/word/component/form/role/llm …）全部
     经本入口落盘 references/usage_global.json（count/t30d/t7d/first_seen/last_seen）。

数据：references/usage_global.json
    {
      "namespace": {
        "obj": {"count": n, "t30d": n, "t7d": n, "first_seen": iso, "last_seen": iso}
      }
    }

设计（复用 hit_tracker 模板）：
  - 锁：threading.Lock 原子写（多线程 MCP 并发安全）
  - 容量：单词条上限 5000 · 单 namespace 上限 2000（防膨胀）
  - 隔离：QCM_NO_REPORT=1 时跳过写盘（ci_core/word_evolution 制造测试调用不污染运行观测）
  - 降级：文件读写异常静默（观测环失败不影响主流程）
  - 时间窗：t30d/t7d 按 last_seen 滚动（nightrun 统一清零重算）

用法：
  from usage_global import record_usage, usage_global_stats
  record_usage("tool", "qcm_research")
  record_usage("intent", "①危机处置")
  usage_global_stats()                 # 全量摘要
"""
import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
USAGE_GLOBAL = ROOT / "references" / "usage_global.json"

MAX_ENTRIES_TOTAL = 5000   # 全局条数上限（防膨胀）
MAX_ENTRIES_NS = 2000      # 单 namespace 条数上限
VALID_NS = {"tool", "intent", "domain", "word", "component", "form", "role", "llm", "chapter",
             "clarify", "input"}  # M4：补 clarify(澄清事件)/input(MDS字段缺失) 维 · 供 M2/M3/L3 自反馈
_lock = threading.Lock()

# time-window 采用滚动计数（t30d/t7d 每次采样自增 · nightrun 统一清零重算）

def _load() -> dict:
    try:
        if USAGE_GLOBAL.exists():
            return json.loads(USAGE_GLOBAL.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        USAGE_GLOBAL.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_usage(namespace: str, obj: object, meta: Dict = None) -> dict:
    """统一采样：记录一次对象使用（出口归一化核心 API）

    Args:
        namespace: 对象域 ∈ {tool,intent,domain,word,component,form,role,llm,chapter,clarify,input}
        obj:       对象标识（str/int · 自动归一为小写 str）
        meta:      附加元数据（可选 · 写入 entry["meta"]，只增不改）
    Returns:
        {"namespace": ns, "obj": o, "count": n}（本次采样后聚合）· 隔离或被拒时 {}
    """
    if os.environ.get("QCM_NO_REPORT") == "1":
        return {}
    if namespace not in VALID_NS:
        return {}
    o = str(obj).strip().lower()
    if not o:
        return {}
    with _lock:
        data = _load()
        now = datetime.now()
        now_s = now.isoformat(timespec="seconds")
        ns_map = data.setdefault(namespace, {})
        e = ns_map.setdefault(o, {
            "count": 0, "t30d": 0, "t7d": 0, "first_seen": now_s, "last_seen": now_s,
        })
        e["count"] += 1
        e["t30d"] += 1
        e["t7d"] += 1
        e["last_seen"] = now_s
        # 只增不改：meta 首次携带才写入（不覆盖既有观测）
        if meta:
            old = e.get("meta")
            if not isinstance(old, dict):
                old = {}
            for k, v in meta.items():
                old.setdefault(k, v)
            e["meta"] = old
        # 容量治理：超出单 namespace 上限淘汰最旧
        if len(ns_map) > MAX_ENTRIES_NS:
            for k in sorted(ns_map, key=lambda k: (ns_map[k].get("last_seen", "") or ""))[:len(ns_map) - MAX_ENTRIES_NS]:
                ns_map.pop(k, None)
        if len(data) > MAX_ENTRIES_TOTAL:
            for ns in data:
                over = len(data[ns]) - MAX_ENTRIES_NS
                if over > 0:
                    for k in sorted(data[ns], key=lambda k: (data[ns][k].get("last_seen", "") or ""))[:over]:
                        data[ns].pop(k, None)
        _save(data)
        return {"namespace": namespace, "obj": o, "count": e["count"]}


def usage_global_stats(window: str = "all") -> dict:
    """全量/分窗摘要（供对账 qcm_reconcile 与观测报告消费）

    Args:
        window: "all" | "30d" | "7d"
    Returns:
        {"namespaces": n, "total_entries": n, "total_count": n, "namespaces_detail": {ns: {obj: entry}}}
    """
    data = _load()
    detail = {}
    total_count = 0
    for ns, objs in data.items():
        if not isinstance(objs, dict):
            continue
        dd = {}
        for o, e in objs.items():
            if not isinstance(e, dict):
                continue
            if window == "30d":
                e2 = {"count": e.get("t30d", 0), "t30d": e.get("t30d", 0), "t7d": e.get("t7d", 0),
                      "first_seen": e.get("first_seen", ""), "last_seen": e.get("last_seen", "")}
            elif window == "7d":
                e2 = {"count": e.get("t7d", 0), "t30d": e.get("t30d", 0), "t7d": e.get("t7d", 0),
                      "first_seen": e.get("first_seen", ""), "last_seen": e.get("last_seen", "")}
            else:
                e2 = e
            dd[o] = e2
            total_count += e2.get("count", 0)
        detail[ns] = dd
    return {
        "namespaces": len(detail),
        "total_entries": sum(len(v) for v in detail.values()),
        "total_count": total_count,
        "namespaces_detail": detail,
    }


def reset_namespace(namespace: str = None) -> None:
    """清零（nightrun 时间窗重算 / 测试隔离）· namespace=None 全清"""
    with _lock:
        data = _load()
        if namespace:
            data.pop(namespace, None)
        else:
            data.clear()
        _save(data)


def main():
    if "--stats" in sys.argv:
        s = usage_global_stats()
        print(f"全局使用采样（usage_global.json）：{s['namespaces']} 域 · "
              f"{s['total_entries']} 条 · {s['total_count']} 次")
        for ns, objs in s["namespaces_detail"].items():
            top = sorted(objs.items(), key=lambda x: -x[1].get("count", 0))[:5]
            print(f"  [{ns}] " + " · ".join(f"{o}:{e.get('count', 0)}" for o, e in top))
        return 0
    if len(sys.argv) >= 4 and sys.argv[1] == "--record":
        # --record <namespace> <obj>
        r = record_usage(sys.argv[2], sys.argv[3])
        print(f"record_usage({sys.argv[2]}, {sys.argv[3]}) → count={r.get('count', '-')}")
        return 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--reset":
        reset_namespace(sys.argv[2] if len(sys.argv) > 2 else None)
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())