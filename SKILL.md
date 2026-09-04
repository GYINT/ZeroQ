---
name: ZeroQ
version: 1.0.1
display_name: 归零（ZeroQ）
description: '归零（ZeroQ）质量管理指导 Skill · 4 层级架构（输出/协议/输入/底层）· 严格分离 · 动作阶段主·时间维度子 · 输出层 4 形态 · 场景路由消费（意图×领域→形态×组件动态组合）· 组件池三机制（归一化/热度/约束映射）· 5 原则 · action-orders.md 15 章协议权威 · 文件层治理（生命周期/守卫 12 检/归档）· 路径归一化（paths/registry）· 插件扩展（plugins/ 热加载）· 回归全绿 · Infoseek 协同 5 维缺口检测 + 混合策略 3 阶段触发'
author: Forka
license: Apache-2.0
entry_point: SKILL.md
protocol_authority: references/protocol/action-orders.md
manifest: manifest.yaml
manifest_sync: scripts/sync_manifest.py
output_validator: core/validator.py
test_engine: 多引擎回归 + 验证器 全绿
---

# 归零（ZeroQ）

> 对外发布版本：**1.0.1**
> 中文名「**归零**」源自质量管理的"问题归零 / 双归零"内核——定位、机理、机理延伸、管理归零、技术归零。
> **一句话**：遇到质量危机、要做问题归零、评估体系成熟度、或想沉淀质量知识时，把问题交给它，它会按权威协议给你**可落地的处置方案**，而不是泛泛而谈。

---

## 目录

1. [这是什么（给你）](#1-这是什么给你)
2. [你怎么用（快速上手）](#2-你怎么用快速上手)
3. [你能拿到什么（4 种输出形态）](#3-你能拿到什么4-种输出形态)
4. [典型用法场景（可直接抄）](#4-典型用法场景可直接抄)
5. [它怎么工作（简化流水线）](#5-它怎么工作简化流水线)
6. [你能自己改什么（用户主导域）](#6-你能自己改什么用户主导域)
7. [边界与纪律（什么它不干 + 守卫规则）](#7-边界与纪律什么它不干--守卫规则)
8. [进阶：架构与模块（技术定位）](#8-进阶架构与模块技术定位)
9. [兼容性](#9-兼容性)
10. [路线图](#10-路线图)
11. [触发词](#11-触发词)
12. [配套文档](#12-配套文档)
13. [测试与质量](#13-测试与质量)

---

## 1. 这是什么（给你）

归零（ZeroQ）是一个面向**全行业质量管理与问题归零**的指导 Skill。它把"质量危机处置 → 问题归零（双归零）→ 体系治理评估 → 知识沉淀"封装为一套可复用的结构化问题解决流水线。

你说清楚「**什么领域、出了什么事、危机到哪一步**」，它会：

1. **意图路由** — 按意图×领域匹配场景，自动选输出形态与组件
2. **协议匹配** — 落到 `action-orders.md` 15 章权威协议（AO-1~AO-4 行动指令卡 + 5 段式 + 危机管理）
3. **四形态输出** — 案例应用 / 决策卡片 / 评估报告 / 快速响应，按场景自动选
4. **缺口协同** — 五维（行业/危机类型/工具/标准/大师）缺口达标 → 触发 Infoseek 归因与收敛
5. **防御性交付** — `[unverified]` 标注 + 数据时效 + 边界声明，不编造
6. **资产沉淀** — 案例蒸馏回组件池，知识入库，悬空/废弃经 R4R 环治理

### 1.1 适用场景（你会在这些时候用它）

✅ 质量危机处置（围堵/消除/纠正/预防）· 问题归零（双归零：管理归零+技术归零）· 8D / 5Why / FMEA 实战 · 体系成熟度评估 · 质量工具选型 · 质量文化建设 · 知识沉淀与行业拓展

### 1.2 不适用场景（它明确不干）

❌ 纯财务/法务/营销问题 · 单一工具问答（无质量问题语境）· 实时新闻监控 · 浏览器自动化爬取

---

## 2. 你怎么用（快速上手）

### 2.1 方式一：直接对话说需求（最常见）

你不需要懂它的内部架构。像跟同事交代任务一样，说清楚 **「领域 + 事件 + 危机阶段」** 即可。例如：

- "产线出现批量焊点虚焊，怎么围堵和归零？"
- "帮我们做一次供应商质量管理成熟度评估"
- "把这个客诉案例沉淀成知识库条目"

它会自动路由到对应协议与输出形态。若意图模糊，它会**回显识别结果**（"已识别【意图X】→ 形态【Y】，如有偏差请纠正"），你纠正一句即可。

### 2.2 方式二：作为 Skill 加载给 Agent

Agent 读取本 `SKILL.md` 后，按输入结构体（见 `references/contract/mds-input.md`）承接你的请求：

```
3 步启动归零：
① 输入结构体（mds-input.md）→ 意图 / 领域 / 危机等级
② 协议层（action-orders.md）→ 14 协议自动匹配
③ 输出层（4 形态）→ 按场景输出（决策卡/案例/评估/快响）
```

**快速判定**（你也可直接点名要哪种形态）：
- D 总分 ≥4 → AO-1 围堵（决策卡）
- 危机期 + 关键决策 → AO-2 应对（案例应用）
- 危机后 + ≥2 次同类 → AO-4 治理（评估报告）
- 缺口暴露 → 触发 Infoseek 协同

### 2.3 方式三：作为 MCP Server 接入

如果你在自己的系统里调用它（而非通过对话），以 stdio / HTTP 方式启动：

```bash
pip install -r requirements.txt

# stdio（本地）
python scripts/mcp_server.py

# HTTP/SSE（Claude Desktop / Cursor）
python scripts/mcp_server.py --transport http --port 8080
```

**14 个 MCP 工具**（按你能做什么分类）：

| 类别 | 工具 | 你用它来 |
|------|------|---------|
| 研究/检索 | `qcm_research` / `qcm_score_source` | 协同调研 / 给信源评分 |
| 决策/求解 | `qcm_decide` / `qcm_solve_problem` | 危机判定 / 问题求解 |
| 审计/验证 | `qcm_audit` / `qcm_validate` | 决策审计 / 4 形态校验 |
| 归因/缺口 | `qcm_attribution` / `qcm_attribution_phase` / `qcm_gap_detect` | 失效维度归因 / 缺口检测 |
| 契约/路由 | `qcm_contract` / `qcm_failure_dimensions` | 输入契约校验 / 失效维度 |
| 守卫/运维 | `qcm_guardian` / `qcm_nightrun` | 守卫触发 / 夜巡决策环 |
| 采样/统计 | `qcm_sampled` | 抽样统计 |
| 语料读取 | `qcm_corpus_read` / `qcm_corpus_search` | capture 感知读取/检索 `references/**`（喂热度回灌 · M0.a） |

> **语料读取（capture 感知 · M0.a）**：MCP 形态下读取/检索 `references/**` 请优先用
> `qcm_corpus_read(stem, title)` / `qcm_corpus_search(query)` —— 两者已接入引用热度埋点，
> 其访问会被月度回灌脚本（`scripts/ref_heat.py --aggregate --backfill`）采集，用于校准 M3 同根阈值。
> Skill-only 形态（无 MCP）下直接读 `references/**` 为兼容退化路径，访问不入热度统计。

### 2.4 环境变量（按需设置）

| 变量 | 用途 | 默认 |
|------|------|------|
| `QCM_ROOT` | ZeroQ 安装根（路径归一化）| 自身推导 |
| `INFOSEEK_ROOT` | Infoseek 安装根（跨 Skill 协同）| 探测列表 |
| `QCM_KEYWORDS` | 词库路径覆盖 | references/config/keyword.yaml |
| `QCM_AUTH_TOKEN` | MCP 认证 Token | — |

---

## 3. 你能拿到什么（4 种输出形态）

同样一个问题，因**危机阶段**不同，它会给你不同的成品。理解这四种形态，你就能在提需求时点名要哪种。

| 形态 | 令牌 | 周期 | 什么时候用它 | 出来是什么样 | 给你什么 |
|------|------|------|------------|-------------|---------|
| ① **案例应用** | ~700 字 | 长期 | 实战案例复盘、知识沉淀 | 「背景 → 危机 → 处置 → 归零 → 复盘」完整叙事 | 一个可借鉴的真实解法 + 5 段式结构 |
| ② **决策卡片** | ~50 字 | 即时 | 应急/选型/治理现场 | 一页纸要点（围堵/纠正/预防）| 立刻能用的决策依据 |
| ③ **评估报告** | ~120 字 | 季度 | 治理水平评分、体系审计 | 打分 + 缺口清单 + 改进路线图 | 当下成熟度定位与下一步 |
| ④ **快速响应** | ~30 字 | 即时 | 现场秒级判定、应急处置 | 一句结论 + 关键动作 | 马上能执行的动作指令 |

每形态都经过 10 项自动校验（`core/validator.py`）：段模板 / 副作用声明 / 输入契约 / 输出契约 / 降级路径 / 执行轨迹 / `[unverified]` 标注 / 数据时效 / 边界声明 / 禁止内容清单——**所以你拿到的成品结构完整、带溯源、不编造**。

---

## 4. 典型用法场景（可直接抄）

| # | 你的场景 | 你可以直接说 | 它会给你 |
|---|---------|------------|---------|
| A | 产线突发质量危机 | "产线出现批量焊点虚焊，怎么围堵和归零？" | AO-1 围堵 + 案例应用/决策卡 |
| B | 不知该用哪个质量工具 | "想做供应商质量评估，该用哪个工具？" | 工具选型路由 + 决策卡片 |
| C | 想摸清体系家底 | "帮我们做一次质量管理成熟度评估" | 评估报告（评分→缺口→路线图）|
| D | 有个好案例想留档 | "把这个客诉案例沉淀成知识库条目" | 案例应用 + 入库（R4R 治理）|
| E | 怀疑某领域覆盖不足 | "我们半导体行业在 ZeroQ 里覆盖够吗？" | 五维缺口检测 → 触发 Infoseek 协同调研 |

> 提示：场景 E 这类"缺口类"请求，当它判定**≥2 维缺口**时会自动进入 Infoseek 归因流程；深层调研（"展开 D"）需要你确认后才执行，不会擅自联网深挖。

---

## 5. 它怎么工作（简化流水线）

```
你描述问题（意图/领域/危机等级）
   ↓
① 意图路由  → 意图×领域 → 形态×组件 动态组合
   ↓
② 协议匹配  → 落到 action-orders.md 15 章权威协议
   ↓
③ 组件装配  → 归一化 / 热度识别 / 约束映射（防模板爆炸）
   ↓
④ 四形态输出 → 案例应用 / 决策卡 / 评估报告 / 快响（带执行轨迹）
   ↓
⑤（条件）缺口协同 → 五维缺口 ≥2 → Infoseek 归因 → 置信度≥70 入库
   ↓
⑥（后台）资产治理 → 孤儿/悬空/废弃扫描 → R4R 环 → 季度清理
```

| 阶段 | 你感知到的 | 背后在做 |
|------|-----------|---------|
| 意图路由 | 回显"已识别意图X→形态Y" | `router.py` + `keyword.yaml` |
| 协议匹配 | 命中对应的处置协议 | `action-orders.md` 15 章 |
| 组件装配 | 内容精准、不套空模板 | 组件池三机制（归一化/热度/约束映射）|
| 四形态输出 | 结构完整的成品 | `validator.py` 10 项校验 |
| 缺口协同 | 必要时提示"发现缺口，是否深挖" | `infoseek_bridge.py`（可选依赖）|
| 资产治理 | 几乎无感（后台）| `asset_retirement.py` + `config_sync.py` |

---

## 6. 你能自己改什么（用户主导域）

> **核心原则**：越靠**表层/下游**（输出模板、提示词）你随便改，错了被校验器拦住、影响局部；越靠**底层/上游**（意图路由、行业包）改动会沿"路由→协议→装配→输出"放大，须守门验证。

| 模块 | 架构层 | 文件 / 入口 | 风险 | 优先级 | 说明 |
|------|--------|------------|------|--------|------|
| **语料挂载** | L1 底层 | `references/config/corpus_manifest.yaml` | 低–中 | **高** | 登记新语料、生成索引；g018 守门 |
| **输入契约** | L0 入口 | `references/contract/*.md` | 低 | 中 | 扩展分级输入模板 |
| **意图路由** | L2 输入层 | `references/config/keyword.yaml` | 中–高 | 中 | 增删意图×领域映射；**须路由冒烟+回归** |
| **组件池** | L2→L4 | `components.yaml` + `constraint.yaml` | 中 | 中 | 注册组件、调约束映射 |
| **行业包** | L1 底层 | `references/industry/*.md` | 中 | 中 | 新增行业适配；须登记 index + 关键词注入 |
| **插件** | L-2 协同 | `plugins/*.py` | 中–高 | 中 | 热加载自定义工具（`@register_tool`）|
| **提示词** | L3 协议 | `references/prompts/*.md` | 低 | 低 | 话术微调 |
| **输出模板** | L4 输出 | `outputs/*.md` | 中 | 低 | 4 形态模板微调（10 项结构不可破）|
| **环境变量** | 运行态 | `.env` / shell | 低 | 低 | 路径/Key 指向 |
| **自动化频率** | 调度 | `automation_manifest.yaml` | 中 | 低 | 调 rrule / prompt（须回写 manifest）|

**自定义安全要点**：
- **首选（零风险上手）**：仅改**语料挂载**——局部影响、有守门，改后跑 `python3 scripts/config_sync.py --check` 零问题即可上线。
- **须守门验证**：意图路由 / 组件池 / 行业包 / 插件 / 输入契约——改后必须 `validator.py` + 路由冒烟 + 回归。
- **按需微调**：提示词 / 输出模板 / 环境变量 / 自动化频率。
- 全部自定义受 M0.4 守卫保护：守卫只告警、不改写你的文件。

**按你的角色**：
- **普通用户**：直接改输出模板 / 提示词 / 语料挂载，跑 `config_sync.py --check` 即可，零风险上手。
- **深度定制者**：改路由 / 组件池 / 行业包 / 插件前，先理解四层级依赖，改后必须 `validator.py` + 路由冒烟 + 黄金用例回归，再上线。

---

## 7. 边界与纪律（什么它不干 + 守卫规则）

### 7.1 它明确不做什么
- 不处理纯财务/法务/营销问题
- 不做单一工具问答（脱离质量问题语境）
- 不监控实时新闻、不自动化爬取网页
- 不擅自联网深挖（深层调研须你确认）

### 7.2 守卫默认 report-only（M0.4）
全部注册守卫（g000~g030 + g_capacity，含 g017 反向族 r1~r8，共 **41 项**）默认**仅报告、不改写内容**。任何自主改写须你显式授权或观察期人工核准。这意味着：**它的自动化动作不会悄悄改坏你的文件**。

### 7.3 关键纪律（你改动时要守）
- **manifest 双绑**：`SKILL.md` frontmatter 与 `manifest.yaml` / `skill_meta.json` 字节级一致，改其一须跑 `python3 scripts/sync_manifest.py`。
- **路径零硬编码**：内部路径一律经 `paths.py` / `registry.py`，禁止在脚本写死绝对路径。
- **自动化回写**：WorkBuddy 定时器改 rrule/prompt 时，须同步回写 `automation_manifest.yaml`。

---

## 8. 进阶：架构与模块（技术定位）

> 本章供需要深度定制或接入系统的用户 / Agent 参考。普通使用者可止步于 §7。

### 8.1 四层级架构

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 0 · 入口层   SKILL.md · manifest.yaml · skill_meta.json          │
│ Layer 3 · 协议层   references/protocol/action-orders.md（15 章 · 权威） │
│ Layer 2 · 输入层   references/config/keyword.yaml（意图×领域）         │
│ Layer 4 · 输出层   4 形态（案例应用/决策卡/评估报告/快响）             │
│ Layer 1 · 底层     tools/masters/books/scenarios（知识资产）           │
│ Layer -1 · 验证层  多引擎回归 + 验证器 + 守卫体系（41 项）             │
│ Layer -2 · 协同层  Infoseek 接口 + 插件扩展                           │
└──────────────────────────────────────────────────────────────────────┘
```

### 8.2 核心能力模块

| 职能 | 模块 | 文件 |
|------|------|------|
| 入口与路由 | `router.py` / `intent_calibrator.py` / `ambiguity_resolver.py` | `core/` |
| 协议权威 | 15 章唯一权威协议 + 输入契约（L0–L3）| `references/protocol/action-orders.md` · `references/contract/*.md` |
| 组件池三机制 | 归一化（components.yaml）/ 热度（component_scan.py）/ 约束映射（constraint.yaml）| `references/config/` · `scripts/` |
| 协同接口 | `infoseek_bridge.py` + `infoseek_zerodep_nlp.py`（可选依赖，未装自动降级）| `scripts/` |
| 治理守卫 | 41 项守卫（g000~g030 + g_capacity）| `references/config/guardian.yaml`（单一真源）|
| 插件扩展 | `PluginLoader.load_all()` / `hot_reload()` | `plugins/*.py` |

> **意图词典**：`components/intent-glossary.md`（6 类意图平白释义 + 触发词 + 形态 + 边界）；路由/校准层命中回显「已识别【意图X】→ 形态【Y】」。

### 8.3 场景路由与五维缺口

```
意图 × 领域 → 形态 × 组件 动态组合
① 危机处置 → 案例应用/决策卡/快响（D≥7 完整归零 / D<4 快响判定）
② 流程优化 → 案例应用（PDCA 闭环）
③ 评估审计 → 评估报告（评分→缺口→路线图）
④ 知识学习 → 快响（定义→要点→工具→依据）
⑤ 知识沉淀 → 案例应用（蒸馏 + gap 联动 Infoseek）
⑥ 质量文化 → 评估报告/案例应用（ISO 10010 对齐）
```

五维缺口协同：`行业 → 工艺 → 工具 → 方法论 → 大师/思维`（调研深度 1→3）。**≥2 维失败 → 触发 Infoseek 归因**。混合策略三阶段：Phase 1 自动浅层 → Phase 2 关键中层 → Phase 3 用户深层（"展开 D"）。写入策略：置信度 ≥70 入库 / 40–69 归因历史 / <40 终止。

### 8.4 文件层治理与路径归一化
- `scripts/paths.py`：ZeroQ 内部路径单一真源（`QCM_ROOT` > `__file__` 推导 > 默认）
- `scripts/registry.py`：跨 Skill 依赖解析（`INFOSEEK_ROOT` > 探测列表 > 验证 > None）
- 守卫文件健康⑦⑨：ZeroQ 路径与跨 Skill 路径硬编码零容忍

### 8.5 自动化闭环
`scripts/word_evolution.sh` 词源自进化闭环（8 段全链路 + ±1H 抖动），由 `automation_manifest.yaml` 登记 5 个定时器（周检/月夜巡/R4 月评/热度回灌/周三孤儿专项）。

---

## 9. 兼容性

- **双形态运行**：Skill 形态（Agent 直接加载）与 MCP Server 形态（stdio/http/ws）独立并存
- **跨生态**：frontmatter 通用字段兼容 Anthropic Claude Skills / CodeBuddy；ZeroQ 增强字段其他宿主宽松忽略
- **Infoseek 可选**：未安装自动降级，不报错
- **运行时数据**：状态落 `outputs/.runtime/`，技能更新不丢数据
- **升级方式**：备份 → 替换目录 → 跑 `python3 scripts/sync_manifest.py` + `python3 scripts/config_sync.py --check` 验证

详见 `PLATFORM.md`（多生态平台适用性）。

---

## 10. 路线图

- **近期**：守卫体系扩展（g023+ 语义孤儿）、组件池热度自校准
- **中期（v2.x）**：Infoseek 协同深化（图谱/同义词）、多模态案例起步
- **长期**：编排协同、合规审计自动化、实时协作
- **设计边界（不做）**：实时新闻监控 / 学术文献综述 / 浏览器自动化爬取 / 即时聊天对话


---

## 11. 触发词

### 11.1 场景类
`质量危机` · `问题归零` · `双归零` · `8D` · `5Why` · `FMEA` · `SPC` · `围堵` · `纠正预防` · `体系评估` · `质量文化` · `工具选型` · `案例沉淀`

### 11.2 技术类
`场景路由` · `意图×领域` · `AO 卡` · `5 段式` · `触发矩阵` · `责任层` · `组件池` · `文件同源` · `ref_graph` · `守卫 12 检` · `R4R 资产退休` · `Infoseek 协同` · `路径归一化` · `插件热加载`

### 11.3 能力类
`qcm_decide` · `qcm_solve_problem` · `qcm_research` · `qcm_audit` · `qcm_validate` · `qcm_attribution` · `qcm_gap_detect` · `qcm_guardian` · `router.py` · `assembler.py` · `component_scan.py` · `validator.py` · `asset_retirement.py` · `config_sync.py` · `word_evolution.sh`

---

## 12. 配套文档

| 文档 | 路径 | 用途 |
|------|------|------|
| README | `README.md` | 快速导航 + 5 秒看懂 |
| 协议权威 | `references/protocol/action-orders.md` | 15 章协议（输出层唯一权威） |
| 输入契约 | `references/contract/*.md` | L0–L3 分级输入模板 |
| 词库 | `references/config/keyword.yaml` | 意图×领域映射 |
| 语料清单 | `references/config/corpus_manifest.yaml` | 语料单一真源 |
| 守卫注册 | `references/config/guardian.yaml` | 41 项守卫定义（单一真源） |
| 自动化 | `references/config/automation_manifest.yaml` | 5 定时器真源备份 |
| 治理规范 | `references/governance/*.md` | 资产生命周期 / 冲突解决 |
| 依赖/密钥 | `DEPENDENCIES.md` / `API_KEYS.md` | 外部依赖与 Key 声明 |
| 平台适配 | `PLATFORM.md` | 多生态兼容性 |
| 核心模块 | `core/` | 验证/路由/解析核心（22 模块） |
| 适配层 | `scripts/` | MCP server + 工具 + 守卫 + 进化闭环 |
| 知识资产 | `references/` | 协议/词库/配置/行业包/知识库/大师/方法 |

---

## 13. 测试与质量

- **验证脚本**：
  - `python3 scripts/sync_manifest.py` — Manifest 双绑
  - `python3 core/validator.py` — 4 形态结构校验
  - `python3 scripts/config_sync.py --check` — 配置+文件健康（守卫体系）
  - `python3 scripts/gen_corpus_index.py --check` — 语料索引自洽
  - `python3 scripts/qcm_ref_query.py --orphan / --dangling` — 孤儿/悬空查询
- **测试归档**：`tests/`（basic / protocol / engines）
- **质量基线**：回归全绿 · 4 形态验证全绿 · 守卫体系 0 问题（文件健康 12 检①~⑫ + 全 41 项） · 语料自洽（orphans=0 / dangling=0）
- **健康指标**：缺口暴露率 30–50% · 缺口闭合率 ≥80% · 行业覆盖 100%

---

> **核心设计原则**：4 层级架构 + 5 原则 + 15 章协议 + 4 形态 + 场景路由消费 + 组件池三机制 + 文件层治理 = 归零（ZeroQ）终极架构。
>
> **5 原则（Skill 工程设计准则）**：
> | # | 原则 | 实施 |
> |---|------|------|
> | ① | **单一职责** | ZeroQ = 质量管理 · `action-orders.md` = 协议层单一权威 |
> | ② | **契约驱动** | MDS 22 字段契约 + `action-orders.md §1–§7` + 4 形态 `input_schema`/`output_schema` |
> | ③ | **渐进增强** | MDS T1→T2→T3→T4 + 4 形态降级路径（完整 / 部分 / 缺失）|
> | ④ | **可观测设计** | 8 引擎回归 + 4 形态 `execution_trace` + `qcm_output_validator.py` |
> | ⑤ | **防御性输出** | `[unverified]` 标注 + 数据时效声明 + 边界声明 + 禁止内容清单 |
> **应用范围**：全行业 × 全工艺 × 全触点 × 全危机（依赖 §12 行业适配性 + §8.3 缺口暴露驱动 Infoseek 协同）。
> **版本说明**：对外发布版本固定为 `1.0.1`，全链路版本唯一（SKILL.md / manifest / skill_meta / SERVER_VERSION / 镜像标签统一）。
