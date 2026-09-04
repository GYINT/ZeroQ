# RACI 角色责任矩阵框架方法论摘要

> **定位**：RACI（Responsible 执行 · Accountable 责任 · Consulted 咨询 · Informed 知情）四角色 + 4 层级（决策/管理/支持/执行）× 5 列（执行/责任/咨询/知情/标准化协作）的中层摘要。
> **完整中文操作模板**见 `references/contract/raci-matrix-template.md`。
> **责任层协议**（动作阶段 × 责任主体）见 `references/protocol/action-orders.md §5`。

---

## 一、核心思想

RACI 是**职责分配的标准矩阵**，回答"这件事由谁做/谁最终负责/谁需被咨询/谁只需知情"。在 QCM 中：

- **与 PDCA 配合**：RACI 是 PDCA Plan 阶段 Who 维度的具体化工具
- **与 5W1H/5W2H 同族**：5W 工具族 + RACI = "谁在什么层级做什么"
- **与责任层协议配合**：action-orders §5 是"动作阶段 × 责任主体"协议，RACI 是其**操作化工具**

```
RACI 4 角色        R（谁做）A（谁最终负责）C（双向咨询）I（单向知情）
       ↓
4 层级（决策/管理/支持/执行） → 矩阵填充
       ↓
每行只能 1 个 A → 责任清晰可追溯
```

---

## 二、关键原则

1. **每行只能 1 个 A**——多人 A = 无人 A
2. **A 与 R 应合并**——A 既是执行者 → 减少"最终责任真空"
3. **C 应在早期介入**——事前咨询 > 事后通知
4. **I 要节制**——只对关键节点知情，避免信息过载
5. **跨层级协作**用"标准化"列，避免职责真空

---

## 三、与 QCM 协议层的映射

| RACI 角色 | QCM 协议 |
|---------|---------|
| R · 执行 | 各级层的"主责"动作（如 §5 L1 操作级 = 车间主任+主操） |
| A · 责任 | 各级层的"终责"动作（如 §5 L4 治理级 = 质量经理 + 设备主管） |
| C · 咨询 | 3T 沟通表 + 危机判定 D 总分（§3.1 D1+D2+D3+D4 探测溢价） |
| I · 知情 | §4 L1–L4 触发矩阵 + §3.3 3T 阶段升级 |
| 协作 · 标准化 | §5 责任层定义 + §6 D 折叠段契约 |

---

## 四、与其他工具的挂接

```
PDCA Plan (5W1H)
  ├─ What / Why / How / When / Where → SPC / 鱼骨图 / 时间表 / VSM
  └─ Who → RACI（4 角色 × 4 层级 × 5 列）
       ↓
8D D1 团队组建 → RACI（Ford 8D 模板直接用 RACI）
       ↓
action-orders §3 §5 责任层协议 → RACI 落地
       ↓
PDCA Action 标准化 + 横向推广（避免 RACI 局部最佳实践）
```

---

## 五、关键判据

1. **A 唯一**——每任务仅 1 个最终负责人
2. **A 与 R 合并**——A 必须亲手执行（避免责任/执行分离）
3. **C 不晚于 R 启动前**——事前咨询 > 事后追责
4. **I 节点精简**——不超过 R/C 节点数的 1.5 倍
5. **跨层级协作**有 SOP（避免 RACI 真空）

---

## 六、术语注册

| 词条 | intent | aliases |
|------|--------|---------|
| RACI | ②流程优化 | Responsible Accountable Consulted Informed / 角色责任矩阵 / Responsibility Matrix |

均已落盘 `keyword.yaml`。

---

## 七、引用路径

- 完整操作模板：`references/contract/raci-matrix-template.md`
- 责任层协议：`references/protocol/action-orders.md §5`
- 危机沟通升级：`references/protocol/action-orders.md §3.3`
- 触发矩阵：`references/protocol/action-orders.md §4`
- PDCA 配合：`references/methods/pdca-qc-framework.md`
- 8D 团队组建：`references/contract/8d-report-template.md` § 阶段一