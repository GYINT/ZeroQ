# 命名契约（Naming Convention）

> v3.3 | 行业背书: ISO9000/CMMI/VDA6.3/QMS 四范式（置信度0.85）| V8.0+ 15 协议术语 + 4 形态 + 5 原则 + 缺口暴露驱动

## 规则

```
所有层级/等级概念 = 维度前缀 + 名称
```

| 前缀 | 含义 | 示例 |
|------|------|------|
| 组织- | 谁做事 | 组织-管理层 |
| 流程- | 在哪生效 | 流程-管理面 |
| 因果- | 为什么 | 因果-系统链 |
| 决策- | 怎么答 | 决策-L3 |
| 状态- | 到哪了 | 状态-成熟度3级 |
| 价值- | 值不值 | 价值-Tier1 |
| 治理- | 多细管 | 治理-车间级 |
| 工具- | 用什么 | 工具-②基础方法论 |
| 价值链- | 哪个环节 | 价值链-主线（如生产制造） |
| 动作- | 行动阶段 | 动作-围堵阶段（V8.0+）|
| 缺口- | 缺口维度 | 缺口-行业（V8.0+）|
| 热词- | 末端触点 | 热词-冷链断点（V8.0+）|

## 受控术语（防歧义 · 单一真源声明）

> **术语三义治理**：同名术语在不同语境含义不同，须按语境消歧；本段为受控定义唯一真源，
> 修改须同步 guardian.yaml 的 g025_terminology 守卫（防回归）。质量领域术语（SPC 范式 /
> TQM 范式 / ISO 四范式）属方法论语境，**非**设计原则，保留不改性。

### 『工具』三义（GAP-T2 · 消除 10/86/87 三义）
| 义项 | 含义 | 计数 | 权威源 | 示例 |
|------|------|------|--------|------|
| ① 代码工具 | MCP/函数级可执行工具（引擎可调用的代码实体） | 10 | `mcp_server` / `scripts/*.py` 导出 | `file_homology` / `grep` |
| ② 质量实例 | 质量方法落地的工具实例（可复用质量工具集合） | 86 | `references/tools.md` | SPC / MSA / AQL |
| ③ 领域分类 | 领域标签下的"工具集"分类（路由维度，非实体） | 87 | 本文件领域 8 标签 | A制造 = SPC/MSA/AQL… |

> 消歧规则：协议层/引擎层语境的"工具"默认指 ①；质量方法论语境指 ②；路由/领域语境指 ③。
> 输出层引用须显式带义项标签，禁止裸用"工具"引发三义漂移。

## 落格引用格式

```
落格物 = [治理-XX级 × 价值链-主线/底座] + [工具-XX档 × 场景-XX] + 置信度(0-1) + 大师(编号)
```

## 行业依据

- ISO 9000:2015: grade = 对功能用途相同的客体按不同要求分类（GB/T 19000 §3.6.3）
- CMMI: Maturity Level ≠ Capability Level 严格分离
- VDA 6.3: 符合率阈值定级 A≥90%/B80-90%/C<80%
- QMS 四阶文件: QM/QP/WI/QR 类型码编号

## V8.0+ 15 协议术语（对齐 action-orders.md §1-§15）

> **索引声明**：本段为术语**索引**（术语名 + § 引用），**定义以 action-orders.md 为权威**——修改定义只改协议层，本段仅更新术语条目名（防双源）。

### §1-§7 基础协议术语（V5.0 引入）

| 术语 | 定义 | 来源 |
|------|------|------|
| **动作维度主** | 4×N 表格中"动作阶段"为主维度（默认展示）| action-orders §1 |
| **时间维度子** | 4×N 表格中"时间维度"为子维度（隐含·按需展开）| action-orders §1 |
| **动作阶段 4 阶段** | 围堵阶段 → 消除阶段 → 纠正阶段 → 预防阶段 | action-orders §1 |
| **围堵阶段** | AO-1 围堵遏制（应急·止血）·L1 操作级子标签·24h 内 | action-orders §1.1 |
| **消除阶段** | AO-2 应对方案（选方向·拍板）·L2 选型级子标签·1-2 周（含试点）| action-orders §1.2 |
| **纠正阶段** | AO-3 行动分解（施工·执行）·L3 执行级子标签·2-3 周 | action-orders §1.3 |
| **预防阶段** | AO-4 组织治理（沉淀·组织化）·L4 治理级子标签·贯穿整季+季末 | action-orders §1.4 |
| **L 层子标签** | L1-L4 作为"动作阶段"的子标签（V4.8 主维度 → V5.0 子标签）| action-orders §1 |
| **4×N 维度归一** | 协议层所有 L 层 = 1 层 × N 维度（N 按需）· 主维度=动作阶段 | action-orders §1-§7 |
| **AO-1~AO-4 4×N** | 每张 AO 卡 = 动作阶段（主）+ 8 维度（主）+ 时间维度（子）+ L 层（子标签）| action-orders §1 |
| **L1-L4 触发矩阵 4×N** | 10 维度（动作阶段/L 层子标签/组织归属/输出载体/触发条件/危机子协议/核心工具/展开级别/双归零版本/时间维度子）| action-orders §4 |
| **5 段式 × 动作阶段** | 6 段 × 4 动作阶段映射表 | action-orders §2.2 |
| **D 折叠段契约（V5.0 扩展）** | 默认折叠 + 触发词展开（新增"展开时间轴"）| action-orders §6 |
| **展开时间轴** | V5.0 新增触发词：展开时间维度子段 | action-orders §6.2 |
| **L4 组织治理** | L4 = 组织治理 4 层 × N 维度 | action-orders §7 |
| **责任层 4×N** | 5 维度（动作阶段/L 层子标签/责任层-制造业/责任层-零售/核心一句话）| action-orders §5 |

### V6.0 4 形态术语（P4 扩展）

| 术语 | 定义 | 来源 |
|------|------|------|
| **输出层 4 形态** | ① 案例应用 ② 决策卡片 ③ 评估报告 ④ 快速响应 | action-orders §2.3 |
| **① 案例应用** | Token ~700 · 长期 · 实战案例 · 完整 5 段式 | `outputs/case-application.md` |
| **② 决策卡片** | Token ~50 · 即时 · 应急/选型/治理决策 · 3 段精简 | `outputs/decision-card.md` |
| **③ 评估报告** | Token ~120 · 季度 · 治理水平评分 · 4 层 × 25 分 | `outputs/assessment-report.md` |
| **④ 快速响应** | Token ~30 · 即时 · 现场判定/应急处置 · 1-2 段式 | `outputs/quick-response.md` |

### V6.1-6.3 5 原则术语（Skill 标准化）

| 术语 | 定义 | 来源 |
|------|------|------|
| **5 原则** | 单一职责/契约驱动/渐进增强/可观测设计/防御性输出 | SKILL.md §0.2 |
| **严格分离** | 协议层（4×N 表格）· 输出层（5 段式 + 案例数据）· 底层（库）三层职责严格分离 | action-orders §0 严格分离声明 |
| **不复述** | 输出层严禁逐行复述协议层 4×N 表格 · 仅引用标签 | action-orders §0 严格分离声明 |
| **不展开** | 输出层严禁展开底层工具/标准/大师详情 · 仅引用标签 | action-orders §0 严格分离声明 |
| **D 折叠段严禁展开** | 输出层严禁展开 D 段内容 · 默认折叠状态即可 | action-orders §6.2 |
| **时间维度默认折叠** | 输出层时间维度默认 ⏳ 折叠 · 触发词 `展开时间轴` 展开 | action-orders §1 |
| **input_schema** | 4 形态输入契约（YAML/JSON Schema）| `outputs/*.md` V6.2 增强 |
| **output_schema** | 4 形态输出契约（YAML/JSON Schema）| `outputs/*.md` V6.2 增强 |
| **side_effects** | 4 形态副作用声明（changes/rollback/idempotent）| `outputs/*.md` V6.1 增强 |
| **degradation_paths** | 4 形态降级路径（完整/部分/模糊/极简）| `outputs/*.md` V6.2 增强 |
| **execution_trace** | 4 形态执行轨迹（V6.3 新增）| `outputs/*.md` V6.3 增强 |
| **boundary_declaration** | 4 形态边界声明（不适用场景/Token 边界）| `outputs/*.md` V6.1 增强 |
| **forbidden_content_list** | 4 形态禁止内容清单（财务预测/内部数据等）| `outputs/*.md` V6.2 增强 |
| **[unverified] 标注** | 4 形态未验证数据标注规则 | `outputs/*.md` V6.2 增强 |
| **data_freshness** | 4 形态数据时效声明 | `outputs/*.md` V6.2 增强 |

### §8 QCM-Infoseek 归因协议术语（V7.0 引入）

| 术语 | 定义 | 来源 |
|------|------|------|
| **QCM-Infoseek 归因** | QCM 5 维触发 → Infoseek 5 端点调研 → 4 形态路由 | action-orders §8 |
| **5 维触发信号** | 行业/危机类型/工具/标准/大师 5 维 | action-orders §8.1 |
| **attribution_id** | 归因结果唯一标识 UUID | action-orders §8.2 |
| **matched_qcm_form** | 归因结果推荐的 QCM 输出形态（case_application/decision_card/assessment_report/quick_response）| action-orders §8.2 |
| **Infoseek 5 端点** | anchor_discovery + anchor_score + research + entity_profile + conflict_detection | action-orders §8.3 |
| **5 维评分（Anchor_Score）** | 互动/主题/可信/可读性/活跃度 | action-orders §8.3 |
| **5 维置信度阈值** | ≥70 自动 / 40-69 确认 / <40 不归因 | action-orders §8.4 |
| **Infoseek 5 接口** | QCM 调用的 Infoseek 5 个核心端点 | action-orders §8.3 |

### §9 案例资产化协议术语（V8.0 引入）

| 术语 | 定义 | 来源 |
|------|------|------|
| **case_asset（案例资产）** | 案例作为组织运行资产（V8.0 重新定位）| action-orders §9.1 |
| **case_lifecycle（案例生命周期）** | 新建 → 活跃 → 稳定 → 归档 → 淘汰 | action-orders §9.3 |
| **case_reuse（案例复用）** | 同类问题复用已有案例（V8.0 核心机制）| action-orders §9.4 |
| **case_dynamic_management（动态管理）** | 防臃肿机制（V8.0 核心）| action-orders §9.5 |
| **同类问题复用算法** | 特征向量匹配（industry 30% + crisis_type 50% + tools+standards 20%）| action-orders §9.4 |
| **匹配度阈值** | ≥0.7 高 · 0.5-0.7 中 · 0.3-0.5 低 · <0.3 不复用 | action-orders §9.4 |
| **健康指标** | 归档率 <30% · 重复率 <5% · 月增长 <10% | action-orders §9.5 |
| **主动归档阈值** | 使用频率 <5% 持续 90 天 → 归档 | action-orders §9.3 |
| **淘汰阈值** | 使用频率 <5% 持续 365 天 → 淘汰 | action-orders §9.3 |

### §10 Infoseek 收敛协议术语（V8.0 引入）

| 术语 | 定义 | 来源 |
|------|------|------|
| **convergence_level（收敛级别）** | Level 1-3 调研级别 | action-orders §10.1 |
| **convergence_depth（收敛深度）** | 1-3 调研深度 | action-orders §10.2 |
| **归因置信度阈值** | ≥70 终止 · <70 进入下一级 | action-orders §10.3 |
| **max_depth** | 最大收敛深度 3 | action-orders §10.2 |
| **max_total_query** | 总最大 query 数 9 | action-orders §10.2 |
| **max_tokens_total** | 总最大 Token 15000 | action-orders §10.2 |

### §11 热词与末端触点协议术语（V8.0+ 引入）

| 术语 | 定义 | 来源 |
|------|------|------|
| **hot_word（热词）** | 行业/工艺/末端触点的高频活跃标签（V8.0+ 核心）| action-orders §11.2 |
| **endpoint_hot_word（末端触点热词）** | L3 层末端触点热词（V8.0+ 核心机制）| action-orders §11.2 |
| **hot_word_layer** | L1 行业 / L2 工艺 / L3 末端触点（3 层）| action-orders §11.2 |
| **qcm_granularity（QCM 颗粒度）** | QCM 4 层颗粒度（L1 行业 / L2 工艺 / L3 工序 / L4 末端触点）| action-orders §11.1 |
| **convergence_level（收敛级别）** | Infoseek 收敛级别（Level 1-4 · 与 QCM 颗粒度对应）| action-orders §11.1 |
| **blind_spot（核心盲点）** | QCM 协议层规则未覆盖的颗粒度层（V8.0+ 识别 = L4 末端触点）| action-orders §11.3 |
| **L4 末端触点盲点收敛** | 触发：末端触点不在热词库 L3 → 兜底：Infoseek 收敛 Level 4 | action-orders §11.3 |
| **degradation_consistency（降级一致性）** | 触发/兜底/输出/资源 一致性原则（4 维度）| action-orders §11.4 |
| **降级一致性 4 维度** | 触发一致性 / 兜底一致性 / 输出一致性 / 资源一致性 | action-orders §11.4 |

### §12 三要素新鲜度与行业适配性协议术语（V8.0+ 引入）

| 术语 | 定义 | 来源 |
|------|------|------|
| **freshness（新鲜度）** | 当代要素占比（人物/方法论/工具）| action-orders §12.2 |
| **people_freshness** | 当代人物 / 总人物 ≥50%（V8.0+ 6 个月目标）| action-orders §12.2 |
| **methodology_freshness** | 当代方法论 / 总方法论 ≥50% | action-orders §12.2 |
| **tool_freshness** | 当代工具 / 总工具 ≥30% | action-orders §12.2 |
| **standard_freshness** | 当代标准 / 总标准 ≥50% | action-orders §12.2 |
| **industry_coverage** | 8/8 行业 = 100%（V8.0+ 12 个月目标）| action-orders §12.3 |
| **classic 标签** | 经典要素（20 世纪 · 不淘汰）| action-orders §12.2 |
| **contemporary 标签** | 当代要素（2020+ · Infoseek 调研）| action-orders §12.2 |
| **3 大要素库** | 人物思维（masters.md）· 方法论（knowledge-base.md + methods.md）· 工具（tools.md）| action-orders §12.1 |
| **人物 6 维档案** | 方法论/核心观点/语言风格/反共识/决策史/人格底色 | action-orders §12.4 |

### §13 缺口暴露驱动 Infoseek 协同协议术语（V8.0+ 引入）

| 术语 | 定义 | 来源 |
|------|------|------|
| **gap_exposure（缺口暴露）** | QCM 应用时经典要素未覆盖的场景 | action-orders §13.1 |
| **gap_score（缺口评分）** | 5 维缺口评分之和（0-10）| action-orders §13.1 |
| **gap_closure（缺口闭合）** | Infoseek 调研后部分闭合 | action-orders §13.7 |
| **gap_ingestion（缺口入库）** | Infoseek 调研结果写入主库 | action-orders §13.6 |
| **infoseek_synergy（Infoseek 协同）** | 缺口暴露 → Infoseek 调研 → 闭合 → 入库闭环 | action-orders §13.2 |
| **混合策略 3 阶段触发** | Phase 1 自动浅层 + Phase 2 关键中层 + Phase 3 用户深层 | action-orders §13.3 |
| **Phase 1（自动浅层）** | 缺口出现 → 立即触发 · 深度 1 · ~3000 Token | action-orders §13.3 |
| **Phase 2（关键中层）** | 关键缺口 → 自动升级 · 深度 2 · ~2000-3000 Token | action-orders §13.3 |
| **Phase 3（用户深层）** | 用户触发 · 深度 3 · ~2000-3000 Token | action-orders §13.3 |
| **5 维层级归一化映射** | QCM 颗粒度（L1-L4）↔ Infoseek 调研层级（Level 1-4）| action-orders §13.4 |
| **自顶向下调研** | 行业 → 工艺 → 工具 → 方法论 → 大师 | action-orders §13.4 |
| **缺口标注协议** | [Infoseek 补充 · 置信度 X%] | action-orders §13.5 |
| **缺口 → 调研 → 进化闭环** | 缺口暴露 → Infoseek 调研 → 当代要素入库 → 缺口减少 | action-orders §13.8 |

## V8.2 新增术语（V8.2 · 领域/意图/字段）

### 领域 8 标签（P1-1 · 资产身份 · alias 权威表）

> **单一权威**：本表为领域定义唯一真源（alias|name|工具集|场景）。
> keyword.yaml / asset_routing_index.yaml 的 domain 字段只用 **alias**（单向引用 · 无环）。

| alias | name | 工具集 | 场景 |
|-------|------|--------|------|
| A制造 | 制造工序 | SPC/MSA/AQL/控制计划/Poka-Yoke | workshop §1-§8 |
| B设计 | 设计/NPI | FMEA/DOE/DFSS/APQP/PPAP/质量门 | design-planning §1 |
| C供应链 | 供应链/供应商 | E 组全套（VDA6.3/记分卡/AQL/SQE）| workshop §7 |
| D现场 | 现场管理 | 5S/TPM/安灯/标准作业/GK/IPQC | workshop §1-§6 |
| E体系 | 体系审核合规 | ISO9001/VDA6.3/6.5/分层审核 | 体系审核 |
| F战略 | 战略规划 | Hoshin/X-Matrix/COPQ/BSC | design-planning §2 |
| R风险 | 风险管理 | FMEA/FTA/FMECA/风险矩阵/CAPA | 危机判定（P0-1）|
| Q客户 | 客户质量 | KANO/VOC/NPS/8D/客诉分析 | workshop §8 |

### 意图 6 类（P2-1 · 用户动作）

<!-- GEN-INTENT-TABLE:BEGIN -->
①危机处置 / ②流程优化 / ③评估审计 / ④知识学习 / ⑤知识沉淀 / ⑥质量文化
<!-- GEN-INTENT-TABLE:END -->
> 形态映射（派生 · ①危机处置→case_application · ②流程优化→case_application · ③评估审计→assessment_report · ④知识学习→quick_response · ⑤知识沉淀→case_application · ⑥质量文化→assessment_report）

> **单一权威**：意图真源为 `core/ambiguity_resolver.py` 的 `INTENTS`（6 类）· 形态映射见 `core/router.py` `FORM_MAP`。
> 本表由 `scripts/gen_intent_table.py` 派生并断言对齐（g025 校验）；意图×形态规范真源见 [意图词典](components/intent-glossary.md)（\`components/intent-glossary.md\`）。

### MDS 新字段（P0-1）

- F25 严重度（FMEA S 1-10）→ D2 映射（可选）
- F26 探测度（FMEA D 1-10）→ ≥8 触发 D 总分 +1 溢价（可选）
- F27 缺陷等级（严重/主要/次要）→ 处置深度（可选）

### 触发词新增（P1-2）

- `展开定位` / `show positioning` → 定位探针段（V8.2）
