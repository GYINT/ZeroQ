---
fields:
  intent: {type: string, required: true}
  form:   {type: string, required: true}
---
【意图词典】已识别【{intent}】→ 形态【{form}】

> 意图×形态 规范真源：`core/ambiguity_resolver.py` INTENTS（6 类）· `core/router.py` FORM_MAP（形态映射）。
> 意图表（naming-convention §意图类）与 `router.INTENTS` 由 `scripts/gen_intent_table.py` 派生对齐（g025 校验）。
> 消费者：`core/router.py` route() 命中回显 / `core/assembler.py` 装配 / `scripts/run_local.py` 链 A 归一点。

| 意图 | 平白释义 | 触发词（示例） | 典型场景 | 输出形态 | 边界 |
|------|---------|---------------|---------|---------|------|
| ①危机处置 | 质量事故/超标/客诉等紧急问题，需立即围堵处置 | 失效、缺陷、客诉、召回、报废、超标、停线、客退 | 现场异常件处置、客诉投诉、召回停线 | case_application（D≥4）/ quick_response（D<4）/ decision_card（决策）| 仅真正紧急/异常信号；优化改善类不归此类 |
| ②流程优化 | 质量流程/指标需系统性改善，走 PDCA 闭环 | 提升、改善、提高、优化、缩短、降低 | 良率提升、周期缩短、不良改善 | case_application（PDCA 骨架）| 有明确优化动词或改善诉求；非紧急 |
| ③评估审计 | 对质量水平/体系/供应商做评估评分，输出报告 | 评估、审计、评分、诊断、现状、成熟度 | 季度评估、体系审核、供应商评审 | assessment_report（评分→缺口→路线图）| 以评分为目的；非处置/非改善 |
| ④知识学习 | 查询质量知识/方法/工具的定义与要点 | 是什么、定义、怎么用、方法、工具、七步法 | 查术语、查工具用法、查流程标准 | quick_response（定义→要点→工具→依据）| 无命中的默认兜底；以获知为目的 |
| ⑤知识沉淀 | 将经验/案例/方案沉淀为可复用知识资产 | 沉淀、固化、蒸馏、总结、最佳实践、经验 | 案例归档、经验固化、最佳实践入库 | case_application（distill 骨架 · gap 联动 Infoseek）| 以产出知识资产为目的；非单一查询 |
| ⑥质量文化 | 建设/评估质量文化（意识-行为-制度-氛围） | 质量文化、氛围、意识、ISO 10010、文化评估 | 文化评估、文化案例、全员质量意识建设 | assessment_report（四层评估）/ case_application（文化案例）| 以组织行为/文化为对象；非个体操作 |

> 回显协议：路由/校准层每次命中输出上一行（意图/形态如有偏差请纠正）。