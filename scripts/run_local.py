#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 链 A 本地 Skill 主链编排器（V8.6 P4 · R13 蓝图落地 · 链 A 归一点）

背景（R13 拓扑）：
  链 A = 本地 Skill 主链（route → llm_router → assemble · 零工具调用）
  链 B = MCP 工具链（tools · 不经 route/assemble）
  LLM_ROUTER 是两链共享公共件。

本模块是链 A 的「执行语义真源归一点」：
  - 串 route（场景路由）→ llm_router（推理）→ assemble（输出组装）
  - 每步采样统一行为契约（intent/domain/form/objects_used）→ usage_global
  - 薄层：只编排+采样，不重复 assembler 的组件职责（S O L I D · 单一职责）

用法：
  from run_local import run_local
  result = run_local("CNC 镗孔椭圆 0.002mm 怎么办", role="manager")

返回：
  {"route": {...}, "echo": "已识别【意图X】→形态【Y】，如有偏差请纠正",
   "output": str, "form": str, "contract": {...}, "llm_used": bool}
"""
import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 防御导入：任一环节缺失 → 编排该步降级为空（不阻塞整链）
try:
    from core.router import route
except Exception:
    try:
        from router import route
    except Exception:
        route = None

try:
    from scripts.assembler import assemble
except Exception:
    try:
        from assembler import assemble
    except Exception:
        assemble = None

try:
    from scripts.llm_router import LLMRouter
    _llm = LLMRouter()
except Exception:
    try:
        from llm_router import LLMRouter
        _llm = LLMRouter()
    except Exception:
        _llm = None


def _qcm_contract_local(intent: str, domain: list, form: str,
                        objects_used: list, llm_meta: Optional[dict]) -> dict:
    """构造统一行为契约（与链 B _qcm_contract 同构 · 集齐 llm_meta）"""
    return {
        "intent": intent,
        "domain": domain,
        "form": form,
        "objects_used": objects_used,
        "llm_meta": llm_meta or {},
        "version": "1.0",
    }


def _sample(namespace: str, obj: Any):
    """采样（防御降级 · QCM_NO_REPORT 由 record_usage 内部隔离）"""
    try:
        from usage_global import record_usage
        record_usage(namespace, obj)
    except Exception:
        pass


def run_local(query: str, role: str = "manager",
              domain_hint: Optional[str] = None,
              use_llm: bool = True,
              actions: Optional[list] = None) -> Dict[str, Any]:
    """链 A 本地主链：route → (llm) → assemble + 契约采样

    Args:
        query:        用户输入
        role:         assembler 角色密度（exec/manager/executive）
        domain_hint:  路由领域提示
        use_llm:      是否走 LLM 推理（False = 纯规则）
        actions:      可选行动数据（缺省空列表 → assemble 输出骨架）
    Returns:
        {"route": route_result, "output": str, "form": str,
         "contract": contract, "llm_used": bool, "errors": list}
    """
    # 1. 场景路由
    r = (route(query, domain_hint) if route else
         {"intent": "④知识学习", "domain": ["通用"], "form": "quick_response",
          "confidence": 0.5, "gap": False, "need_research": False,
          "entities": [], "capacity_warn": []})
    intent = r.get("intent", "④知识学习")
    domain = r.get("domain", ["通用"])
    form = r.get("form", "quick_response")
    errors = list(r.get("capacity_warn", []) or [])

    # A-① 路由回显（A+B 落地 V8.7 · 意图×形态规范真源 intent-glossary.md）
    # 每次命中向用户回显识别结果，如有偏差可即时纠正（g014 轻量四要素 · 透明性）
    # 优先取 route 内置 echo（router.py 单一构造 · 消费方透传）
    echo = r.get("echo") or f"已识别【{intent}】→ 形态【{form}】，如有偏差请纠正"

    # 2. LLM 推理（公共件 · 与链 B 共享 LLM_ROUTER）
    llm_used = False
    llm_meta = {}
    if use_llm and _llm is not None:
        try:
            resp = _llm.call(
                query,
                task=intent,
                system="你是 QCM 质量方法论输出引擎",
                max_tokens=600,
                temperature=0.3,
            )
            llm_used = True
            llm_meta = {
                "provider": resp.get("provider", ""),
                "mode": resp.get("mode", ""),
                "duration_s": round(resp.get("duration_s", 0), 4),
            }
        except Exception as e:
            errors.append(f"llm 降级: {e}")

    # 3. 组装（actions 缺省空 → 契约+骨架输出）
    output = ""
    if assemble is not None:
        try:
            ass = assemble(r, actions or [], role=role)
            output = ass.get("output", "") or ass.get("action_list", "")
            errors += ass.get("errors", []) or []
        except Exception as e:
            errors.append(f"assemble 降级: {e}")
    else:
        output = f"[{intent}] {form}（组装器缺失 · 骨架输出）"

    # 4. 统一行为契约采样（链 A 归一点 · usage_global 落盘）
    contract = _qcm_contract_local(intent, domain, form,
                                   ["router", "llm_router", "assembler"], llm_meta)
    _sample("intent", intent)
    for d in domain:
        _sample("domain", d)
    _sample("form", form)
    _sample("llm", f"{llm_meta.get('provider', 'none')}:{llm_meta.get('mode', 'none')}")

    return {
        "route": r,
        "echo": echo,          # A-① 路由回显（意图→形态 · 偏差可纠正）
        "output": output,
        "form": form,
        "contract": contract,
        "llm_used": llm_used,
        "errors": errors,
    }


if __name__ == "__main__":
    import json
    demo = sys.argv[1] if len(sys.argv) > 1 else "CNC 镗孔椭圆 0.002mm 怎么办"
    res = run_local(demo, role="manager", use_llm=False)
    print(res['echo'])  # A-① 路由回显
    print(f"意图: {res['route'].get('intent')} · 领域: {res['route'].get('domain')} · 形态: {res['form']}")
    print(f"契约: {json.dumps(res['contract'], ensure_ascii=False)}")
    print(f"输出预览: {str(res['output'])[:120].replace(chr(10), ' / ')}")