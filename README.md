# 归零（ZeroQ）

> **归零（ZeroQ）质量管理指导 Skill · 对外发布版本 1.0.1**
> 4 层级架构 · 15 章协议 · 场景路由消费 · 组件池三机制 · 文件层治理 · 路径归一化 · 插件扩展
> 验证基线：多引擎回归全绿 · 4 形态验证全绿 · 守卫体系 0 问题（文件健康 12 检①~⑫）

[![Version](https://img.shields.io/badge/version-1.0.1-blue.svg)](docs/CHANGELOG.md)
[![License](https://img.shields.io/badge/license-Apache_2.0-green.svg)](LICENSE)

---

## 一、定位

归零（ZeroQ）是面向**全行业质量管理与问题归零**的指导 Skill：从现场危机处置、问题归零（双归零）到体系治理评估，从知识学习到行业拓展，覆盖多类意图 × 多类领域，按场景路由动态组合输出。中文名「归零」源自质量管理的"问题归零 / 双归零"内核。

**应用范围**：全行业 × 全工艺 × 全触点 × 全危机（依赖 §12 行业适配性 + §13 缺口暴露驱动 Infoseek 协同）。

## 二、核心架构（4 层级）

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 0 · 入口层   SKILL.md · manifest.yaml · skill_meta.json │
│ Layer 3 · 协议层   references/protocol/action-orders.md（15 章 权威）│
│ Layer 2 · 输入层   references/config/keyword.yaml（意图×领域）  │
│ Layer 4 · 输出层   4 形态（案例应用/决策卡/评估报告/快响）       │
│ Layer 1 · 底层     tools/masters/books/scenarios（知识资产）   │
│ Layer -1 · 验证层  多引擎 + 验证器 + 守卫体系（41 项）          │
│ Layer -2 · 协同层  Infoseek 接口 + 插件扩展                    │
└─────────────────────────────────────────────────────────────┘
```

## 三、意图 × 形态（场景路由消费）

| 意图 | 路由形态 | 说明 |
|------|---------|------|
| ① 危机处置 | 案例应用/决策卡/快响 | D 总分驱动（D≥7 完整归零 / D<4 快响判定）|
| ② 流程优化 | 案例应用 | PDCA 闭环骨架 |
| ③ 评估审计 | 评估报告 | 评分→缺口→路线图 |
| ④ 知识学习 | 快响 | 定义→要点→工具→依据 |
| ⑤ 知识沉淀 | 案例应用 | 蒸馏清单组件 + gap 联动 Infoseek（§13）|
| ⑥ 质量文化 | 评估报告/案例应用 | ISO 10010 对齐 |

## 四、组件池三机制（防模板爆炸）

```
① 归一化：references/config/components.yaml 注册表（容量约束）
② 热度识别：core/component_scan.py（ref_count → new/active/stable 分级）
③ 动态映射：references/config/constraint.yaml（意图×D×复杂度 → 组件序列）
```

## 五、文件层治理

### 5.1 目录分区
```
references/  协议+词库+配置    components/  组件池
outputs/     4 形态模板        scripts/     运行脚本（paths/registry）
tests/       测试归档          plugins/     插件扩展
deploy/      部署资产          docs/        文档
archive/     归档（deprecated 头注重定向）
.file-manifest.yaml  子层级治理元数据
```

### 5.2 路径归一化（零硬编码）
- `scripts/paths.py`：ZeroQ 内部路径单一真源（env `QCM_ROOT` > `__file__` 推导 > 默认）
- `scripts/registry.py`：跨 Skill 依赖解析（env `INFOSEEK_ROOT` > 探测列表 > 验证 > None）

### 5.3 守卫体系（config_sync.py --check · 41 项注册守卫）
```
文件健康 12 检（①~⑫）：
① 悬空引用 ② deprecated 零容忍 ③ 所有权 ④ 测试归档
⑤ 嵌套链接 ⑥ 组件容量 ⑦ ZeroQ 硬编码 ⑧ plugins 存在性 ⑨ 跨 Skill 硬编码
⑩ ref 存在 ⑫ rglob 递归扫描
运行态/注册/契约/同源/资产/反向族：⑬ Key 健康 · ⑭ 四件套 · ⑮ 契约 · ⑯ 行业包
· ⑱ 语料登记 · ⑲ 运行态缓存 · ⑳ 文件同源 · ㉑ 废弃模板 · ㉒ 资产退休/未登记语料
+ g017_r1~r8 反向决策校准族
+ g030 元守卫（实现态↔注册态差集 + 元数据漂移 + 治理文件冗余）
```

## 六、插件扩展

```python
# plugins/ 下新建 .py（不以 _ 开头）
from mcp_server import register_tool

@register_tool(name="my_tool", description="...", input_schema={...})
def my_tool(arg: str) -> dict:
    return {"result": arg}
```

- 启动自动挂载：`PluginLoader.load_all()`（失败不阻塞）
- 热重载：`PluginLoader.hot_reload()`
- 样例：`plugins/echo_tool.py`（`qcm_plugin_echo` 工具）

## 七、ZeroQ–Infoseek 协同（§8/§10/§13）

- **五维触发**：行业/危机类型/工具/标准/大师 缺口 ≥2 维 → 触发归因
- **五维层级映射**：行业→工艺→工具→方法论→大师（调研深度 1–3）
- **混合策略三阶段**：自动浅层 → 关键中层 → 用户深层
- **写入策略**：置信度 ≥70 入库 / 40–69 归因历史 / <40 终止
- Infoseek 为**可选依赖**：未安装时自动降级，不报错

## 八、快速开始

### 作为 MCP Server

```bash
pip install -r requirements.txt

# stdio（本地）
python scripts/mcp_server.py

# HTTP/SSE（Claude Desktop / Cursor）
python scripts/mcp_server.py --transport http --port 8080
```

### 环境变量

| 变量 | 用途 | 默认 |
|------|------|------|
| `QCM_ROOT` | ZeroQ 安装根（路径归一化）| 自身推导 |
| `INFOSEEK_ROOT` | Infoseek 安装根（跨 Skill）| 探测列表 |
| `QCM_KEYWORDS` | 词库路径覆盖 | references/config/keyword.yaml |
| `QCM_AUTH_TOKEN` | MCP 认证 Token | — |

> 完整环境变量、API Key 与依赖说明见 **`DEPENDENCIES.md`** 与 **`API_KEYS.md`**。

### 验证与测试

```bash
python core/validator.py                  # 4 形态 验证
python scripts/config_sync.py --check     # 配置+文件健康 12 检（全 41 项守卫）
python core/component_scan.py             # 组件热度 + 容量
# 测试归档（tests/）：basic / protocol / engines
```

## 九、外部依赖与密钥

- **外部依赖清单与作用** → `DEPENDENCIES.md`
- **外部 API Key 清单与效益** → `API_KEYS.md`（仅变量名与作用，不含真实密钥值）

## 十、自动化定时器任务（运维）

> 详细操作命令、验证清单与故障排查决策树见 **`docs/TIMER-RUNBOOK.md`**。

ZeroQ 内置 5 个定时自动化任务，分「回写型 / 只读评估 / 混合」三类。回写型任务会将运行结论回写 ZeroQ 资产（词库、关联热度、归档观察等），是体系"自演化"的驱动面。

### 10.1 任务清单

| 任务 | 触发节奏 | 类型 | 回写实况 |
|------|---------|------|---------|
| 关联热度回灌 | 每月 1 / 15 日 | 🔴 回写型（`ref_heat.py --aggregate --backfill --apply`） | 链路贯通；落盘 `outputs/.runtime/ref_heat.json`。实际回写量取决于事件库（见 10.3 采集面） |
| 词源自进化周检 | 每周一 09:00 | 🔴 回写型（`word_evolution.sh`：观测→检测→决策→回灌→R4 写回） | ✅ 已验证真实写回（R4 热度写回 26 词，落盘 `references/config/keyword.yaml`） |
| R4 归档观察 | 每月 1 日 09:30 | 🟢 只读评估 | 观察期未满则只读、不回写（正确行为） |
| 夜巡兜底 | 每月 1 / 10 / 20 日 22:00 | 🟡 混合（`--nightrun` 决策守卫兜底） | 兜底运行，弱回写 |
| 孤儿语料巡检 | 每周三 09:00 | 🟢 report-only | 仅产出巡检报告，绝不自动改写语料 |

### 10.2 关键运维约束（运行解释器）⚠️

**回写型任务必须运行在已安装 PyYAML ≥ 6.0 的隔离 venv 解释器**：`~/.workbuddy/binaries/python/envs/default/Scripts/python.exe`。

- **原因**：若使用无 PyYAML 的裸托管 Python（`3.13.12/python.exe`），`keyword_lifecycle`、`semantic_audit`、`corpus_sync`、`ref_heat` 等环会因 `import yaml` 失败、被 `|| true` 静默吞掉，**回写链整体空转（0 回写）**。
- 三个回写型 automation（关联热度回灌 / 词源自进化周检 / 夜巡兜底）的运行解释器已在各自 prompt 中固定指向 venv 绝对路径，杜绝裸 python 覆辙。
- 建议将 venv 解释器固化为 ZeroQ 所有 automation 的默认运行环境。

### 10.3 已知项与收敛

- **抖动收敛**：词源周检夜巡窗口抖动已由 `RANDOM % 3600`（最长 1h）收敛为 `RANDOM % 60`（`scripts/word_evolution.sh:28-33`），消除后台长跑被会话切换清理后台 handle 导致的"假运行 / 中断"。
- **采集面（关联热度回灌）**：当前回灌 `applied / suggested = 0`，根因为事件采集面未全亮——Agent 直读 `references/*.md` 绕过 Python 入口，致 `ref_heat.capture` 活在死路径。回灌 0 事件属架构已知项，需独立决策（强化 SKILL.md 约束或走宿主钩子），不在常规修复范围。

## 十一、版本策略

- **对外发布版本**：`1.0.1`（见 `SKILL.md` frontmatter、`skill_meta.json`、`manifest.yaml`）
- 协议层内部标识（`action-orders.md` 的 `V8.0+`）为方法论演进轴，与产品发布版本相互独立

---

> **核心设计原则**：4 层级架构 + 5 原则 + 15 章协议 + 4 形态 + 场景路由消费 + 组件池三机制 + 文件层治理 = ZeroQ 终极架构。
