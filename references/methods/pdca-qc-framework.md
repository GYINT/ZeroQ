# PDCA + 5W1H + QC/CDA 框架方法论摘要

> **定位**：PDCA 循环 + 5W1H 计划工具 + QC 活动（品管圈）+ CDA 活动（持续改善）的方法论摘要。
> **完整中文操作模板**见 `references/contract/pdca-qc-template.md`。
> **QC 七工具**（检查表/管制图/柏拉图/鱼骨图等）见 `tools.md ## A01–A08`。

---

## 一、核心思想

PDCA（Plan-Do-Check-Act，戴明环）是质量改进的**通用循环节奏**：任何改进活动都以此为骨架。**5W1H** 把 Plan 阶段拆成可执行要素，**QC 活动**（品管圈/QC Story）把 PDCA 落到 8 步组织形式，**CDA 活动**（Confirm-Do-Act）是 PDCA 在"持续滚动课题"场景的强化版。

```
PDCA 骨架（戴明环）
  ├─ Plan：用 5W1H 拆解（What 数据基线 / Why 根因 / How 对策 / When 何时 / Who 谁 / Where 何地）
  ├─ Do：执行改善方案（推移图追踪）
  ├─ Check：效果确认（管制图 + 雷达图）
  └─ Action：标准化 + 报告 + 横向推广
```

---

## 二、5W1H 与 5W2H：同族工具的不同应用

| 框架 | 含义 | intent | QCM 词库 |
|------|------|--------|---------|
| **5W1H**（What/Why/How/When/Who/Where）| PDCA Plan 阶段计划工具 | ②流程优化 | `5W1H` |
| **5W2H**（5W1H + How much）| 8D D2 问题陈述 / 含财务维度的扩展 | ②流程优化 | `5W2H` |

**经验**：5W1H 与 5W2H 是**同族工具的不同应用**——5W2H = 5W1H + How much（财务/规模维度）。意图统一归 **②流程优化**（PDCA 计划 / 8D 问题陈述 / 流程梳理通用工具），不按使用场景分裂。

---

## 三、QC 七工具在 PDCA 阶段的对应

| 工具 | PDCA 阶段 | tools.md 条目 |
|------|----------|---------------|
| 检查表 | Plan（What 数据采集）| A08 |
| 柏拉图 | Plan（What 现况分析）| A03 |
| 鱼骨图（因果图）| Plan（Why 根因）| A03 |
| 直方图 | Plan/Check（数据分布）| A06 |
| 散布图 | Plan/Check（相关性）| A07 |
| 层别法 | Plan（数据分层）| A09 |
| 管制图（控制图）| Plan/Check（过程稳定）| A01 SPC |
| 推移图 | Do（实时追踪）| （常用 SPC 时序图）|

---

## 四、与 QCM 协议层的映射

| PDCA 阶段 | action-orders § |
|----------|----------------|
| Plan | §2 5 段式结构（行动要项/事态导航/危机沟通/行动措施/双归零 + 后续）|
| Do | §4 L1-L4 触发矩阵（围堵/消除/纠正/预防 → 执行阶段）|
| Check | §3.3 危机沟通 3T × 3 列表（验证沟通成效）|
| Action | §5 责任层定义 + §6 D 折叠段契约（标准化 + 5 触发词展开）|

**与危机版 PDCA 映射**：
- AO-1 围堵（①危机处置）= PDCA 的应急 Do
- AO-2 应对 = PDCA 的 Plan + Do（短期）
- AO-3 分解 = PDCA 的 Check + Action（中期）
- AO-4 治理 = PDCA 的 Action（长期）+ 体系闭环

---

## 五、与其他方法的挂接

```
PDCA（通用骨架）
  ├─ 8D（Ford 客户投诉/重大异常专用 · D0-D8）→ 见 contract/8d-report-template.md
  ├─ 3A5WHY（根因细化 · 三链：发生/流出/系统）→ 见 methods/3a5why.md
  ├─ four-aspect-evaluation（流出链下挂 · 四性验证）→ 见 methods/four-aspect-evaluation.md
  ├─ DMAIC（六西格玛 · Define-Measure-Analyze-Improve-Control）→ 见 tools B07 关联
  ├─ A3（丰田一页式报告）→ 见 tools F02
  └─ QC Story（品管圈 8 步）→ 与 PDCA 高度同构
```

---

## 六、关键判据

1. **Plan 必填 What 数据基线**（无数据 = 无 PDCA）
2. **Do 阶段推移图**至少 ≥ 4 周数据点（短期数据无统计意义）
3. **Check 必须量化**（基线 → 改善后百分比 + 达标 ✅/❌）
4. **Action 标准化落地**（SOP/PFMEA/CP 至少 1 项）
5. **横向推广**是 Action 的高阶要求（防止"局部最佳实践"）

---

## 七、术语注册

| 词条 | intent | aliases |
|------|--------|---------|
| PDCA | ②流程优化 | plan-do-check-Act / 戴明环 / deming cycle |
| 5W1H | ②流程优化 | 五问一何 / what-why-how-when-who-where |
| QC 活动 | ②流程优化 | QC Story / 品管圈 / QCC |
| CDA 活动 | ②流程优化 | Confirm-Do-Act / 持续改善 |
| 推移图 | ②流程优化 | run chart / trend chart |
| 雷达图 | ②流程优化 | radar chart / spider chart |
| 管制图 | ②流程优化 | control chart / SPC 控制图 |
| 标准化 | ②流程优化 | standardization / SOP 标准化 |

均已落盘 `keyword.yaml`。

---

## 八、引用路径

- 完整操作模板：`references/contract/pdca-qc-template.md`
- QC 七工具：`references/tools/tools.md ## A01–A08`
- 5 段式结构协议：`references/protocol/action-orders.md §2`
- 危机 PDCA 协议：`references/protocol/action-orders.md §3 + §4`
- 8D 报告模板：`references/contract/8d-report-template.md`
- 根因细化：`references/methods/3a5why.md`