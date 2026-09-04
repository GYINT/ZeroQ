# 8D 报告框架方法论摘要（8D Report Framework）

> **定位**：8D 问题解决法（Eight Disciplines of Problem Solving）的中层摘要，承接 `tools.md ## F01. 8D 问题解决`（D0–D8 详细定义 + 18 步 A–R），承接 `action-orders.md §3 + §4` 的危机判定与触发矩阵。
> **完整中文操作模板**见 `references/contract/8d-report-template.md`。
> **细化方法**（三链根因）见 `methods/3a5why.md`，**流出链下挂**（四性评估）见 `methods/four-aspect-evaluation.md`。

---

## 一、核心思想

8D 是 Ford 主导、IATF 16949 §10.2 强约束的**团队导向结构化问题解决方法**，用于客户投诉、重大/重复质量异常、**逃逸性缺陷**。通过 5 阶段 8 步（D0–D8）形成 CAPA 闭环。

```
D0 准备 → D1 团队 → D2 描述 → D3 遏制 → D4 根因 → D5 纠正 → D6 验证 → D7 预防 → D8 表彰
                                            └──────── 5 阶段归并 ────────┘
```

---

## 二、5 阶段 × 8D 映射

| 阶段 | 8D 步骤 | 关键交付物 | 时间窗 |
|------|---------|----------|--------|
| 界定问题 | D1 团队 + D2 描述 + D3 遏制 | 团队 RACI + 问题陈述 + 遏制记录 | D0–D2 |
| 要因分析 | D4 根因 | 鱼骨图 + 5Why + 真因验证 | D3–D5 |
| 确定方案 | D5 纠正 + D6 验证 | 对策方案 + 中量试作验证 | D5–D7 |
| 落地执行 | D6 验证 + D7 预防 | 效果确认 + 文件更新 | D7–D |
| 总结提升 | D7–D8 | 源流回馈 + 宣传推广 + 分层审核 | D+ |

---

## 三、与 QCM 协议层的映射

| 8D 阶段 | action-orders §3 / §4 | 危机管理动作 |
|---------|----------------------|------------|
| D0–D2 | §3.1 危机判定 D 总分（D1+D2+D3+D4 探测溢价，V8.2 FMEA 维度化） | L1 围堵触发 |
| D3 | §3.3 围堵阶段 第一幕 Tell Quickly | 3T 沟通 / 临时遏制 |
| D4 | §3.4 双归零技术前 3 + 管理前 2 | L1 简版 |
| D5 | §4 消除阶段「8D D5 + 3 维度」| L2 选型简版 |
| D6 | §4 纠正阶段「8D D4–D7 + 5×5 + CIR」| L3 完整版 |
| D7 | §4 预防阶段「经验沉淀 + 4×N」| L4 治理总结版 |
| D8 | §3.3 纠正阶段 第三幕 Tell All | 表彰 / 经验复盘 |

---

## 四、与其他方法的挂接

```
8D（Ford/IATF）→ 3A5WHY（三链：发生/流出/系统）
                ↘ four-aspect-evaluation（流出链下挂）
                ↘ 鱼骨图 4M（人机料法环测）
                ↘ 5Why + DOE（根因验证）
                ↘ FMEA / PFMEA / CP（D7 预防）
                ↘ CIR / COPQ / X-Matrix（治理）
```

**与 3A5WHY 流出链挂接**：
- 8D D4 阶段定位"流出的原因"（为什么没被拦截）= 3A5WHY 流出链探测根因
- 8D D5 设计流出管控方案 → 用 four-aspect-evaluation 验证方案四性（执行/教育/标准/监督）

**与四性评估挂接点**：阶段三/四（确定方案/落地执行）末尾。

---

## 五、关键判据（不可绕过）

1. **根因须经验证**（不是假设）— D4 验证真因四项
2. **遏制措施须有有效性确认** — 可疑品 100% 受控
3. **永久对策须使问题指标归零并经验证** — D6 数据验证
4. **D7 须闭环更新 PFMEA / CP** — 文件级预防
5. **流出管控方案须经四性评估** — 单维红一票否决

---

## 六、术语注册

| 词条 | intent | aliases |
|------|--------|---------|
| 8D | ①危机处置 | 8 Disciplines / 8D 报告 / 全球 8D / eight disciplines |
| 8D 报告 | ①危机处置 | 8D Report / 8D 模板 / 调查分析报告 |
| 因果分析 | ①危机处置 | causal analysis / 鱼骨图 / ishikawa |
| 要因分析 | ①危机处置 | root cause factor analysis |
| 调查分析报告 | ①危机处置 | investigation report / 调查报告 |
| 5W2H | ①危机处置 | 五问二何 / 5W 2H / what-why-how |

均已落盘 `keyword.yaml`。

---

## 七、引用路径

- 完整中文操作模板：`references/contract/8d-report-template.md`
- 方法论权威定义：`references/tools/tools.md ## F01`
- 危机管理协议：`references/protocol/action-orders.md §3 + §4`
- 根因细化：`references/methods/3a5why.md`
- 流出链下挂：`references/methods/four-aspect-evaluation.md`