#!/usr/bin/env python3
"""qcm_prompts.py — QCM MCP Prompts API

MCP Prompts API:
  - prompts/list: 列出预设 prompt 模板
  - prompts/get: 获取填充后的 prompt messages

预设模板：
  - qcm_research_default: 通用研究
  - qcm_decide_emergency: 紧急决策
  - qcm_audit_quick: 快速审计
  - qcm_solve_5why: 5Why 求解
"""
from typing import List, Dict, Any


# 预设 prompt 模板
PROMPT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "qcm_research_default": {
        "description": "QCM 默认研究 prompt · 适用于 T1-T4 输入深度",
        "arguments": [
            {"name": "query", "description": "用户问题/场景描述", "required": True},
            {"name": "level_hint", "description": "T1/T2/T3/T4 · 默认 T2", "required": False},
            {"name": "context", "description": "行业/工艺上下文", "required": False},
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "template",
                    "template": """你是 QCM + 质量管控专家。按 action-orders.md 协议给出 5 段式输出：

【问题】{query}
【输入深度】{level_hint}
【上下文】{context}

输出要求：
1. 行动要项（围堵/消除/纠正/预防）
2. 事态导航（时间线 + 决策点）
3. 危机沟通（ITIL P1-P4）
4. 行动措施（具体步骤 + 责任人）
5. 双归零（技术归零 + 管理归零）

要求：专业、严谨、有数据支撑、引用大师观点。"""
                }
            }
        ],
    },
    "qcm_decide_emergency": {
        "description": "QCM 紧急决策 prompt · 24h 围堵",
        "arguments": [
            {"name": "problem_text", "description": "紧急问题描述", "required": True},
            {"name": "urgency", "description": "紧急/重要/常规/例行 · 默认紧急", "required": False},
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "template",
                    "template": """【紧急问题】{problem_text}
【紧急度】{urgency}

请按 QCM T1 决策路由（24h 围堵）：
1. 立即识别主要风险（D 总分）
2. 围堵遏制（24h 内）：具体动作
3. 责任分工（工序级/现场级）
4. 升级路径（ITIL P1-P4）
5. 复盘时间表

要求：可立即执行、可量化、可追溯。"""
                }
            }
        ],
    },
    "qcm_audit_quick": {
        "description": "QCM 快速审计 prompt · 5 维风险评估",
        "arguments": [
            {"name": "decision_output", "description": "待审计的决策输出 JSON", "required": True},
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "template",
                    "template": """【待审计决策】
{decision_output}

请按 QCM + §12 五维风险审计：
1. 覆盖（数据完整性）
2. 有效性（方案可行性）
3. 可追溯（引用链）
4. 可重复（标准化）
5. 可持续（长期效果）

给出 0-100 分审计评分 + 改进建议。"""
                }
            }
        ],
    },
    "qcm_solve_5why": {
        "description": "QCM 5Why 求解 prompt · 系统链根因分析",
        "arguments": [
            {"name": "problem", "description": "问题描述", "required": True},
            {"name": "level", "description": "求解深度（建议 5 层）", "required": False},
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "template",
                    "template": """【问题】{problem}
【深度】{level}（默认 5 层）

请用 5Why 方法逐层追问：
- Why 1: 表层原因
- Why 2: 流程原因
- Why 3: 系统原因
- Why 4: 治理原因
- Why 5: 文化/战略原因

输出：
- 每层追问 + 答案
- 系统链根因
- 双归零建议"""
                }
            }
        ],
    },
    "qcm_clarify_input": {
        "description": "QCM 输入引导 prompt · 最小必要信息集(F1-F4)澄清（M2 · 不复用 5Why）",
        "arguments": [
            {"name": "intent", "description": "已识别意图", "required": True},
            {"name": "domain", "description": "已识别领域", "required": False},
        ],
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "template",
                    "template": """已识别意图【{intent}】· 领域【{domain}】，但输入语义/语境不全，请补充最小必要信息：

· F1 场景描述（实战问题/危机现象）
· F2 涉及范围（行业/工艺/危机类型）
· F3 影响对象（客户端/内部/供应链）
· F4 期望产出（决策/案例/评估/快响）

请按上述 4 项补齐后重述，便于精准路由与处置。"""
                }
            }
        ],
    },
}


def list_prompts() -> List[Dict[str, Any]]:
    """列出所有 prompt 模板"""
    prompts = []
    for name, tmpl in PROMPT_TEMPLATES.items():
        prompts.append({
            "name": name,
            "description": tmpl["description"],
            "arguments": tmpl["arguments"],
        })
    return prompts


class PromptNotFoundError(Exception):
    """Prompt 不存在异常"""
    def __init__(self, name):
        self.name = name
        super().__init__(f"prompt not found: {name}")


def get_prompt(name: str, arguments: Dict[str, str]) -> Dict[str, Any]:
    """获取填充后的 prompt messages"""
    if name not in PROMPT_TEMPLATES:
        raise PromptNotFoundError(name)

    tmpl = PROMPT_TEMPLATES[name]

    # 填充 messages
    filled_messages = []
    for msg in tmpl["messages"]:
        content_template = msg["content"]["template"]
        # 简单模板替换（{var} → value）
        filled_text = content_template
        for arg_name, arg_value in arguments.items():
            filled_text = filled_text.replace("{" + arg_name + "}", str(arg_value))
        # 未提供的参数填充默认值
        import re
        for m in re.finditer(r"\{(\w+)\}", filled_text):
            filled_text = filled_text.replace(m.group(0), "")

        filled_messages.append({
            "role": msg["role"],
            "content": {"type": "text", "text": filled_text},
        })

    return {
        "description": tmpl["description"],
        "messages": filled_messages,
    }


if __name__ == "__main__":
    print("=== Prompts 列表 ===")
    for p in list_prompts():
        print(f"  - {p['name']}: {p['description'][:60]}...")

    print()
    print("=== qcm_research_default（参数：query=test）===")
    result = get_prompt("qcm_research_default", {"query": "焊接虚焊客诉复发", "level_hint": "T2"})
    if "messages" in result:
        for msg in result["messages"]:
            print(f"  [{msg['role']}]")
            print(f"  {msg['content']['text'][:300]}...")