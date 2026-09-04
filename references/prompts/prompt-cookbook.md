> [!WARNING]
> ## ⚠️ DEPRECATED — 本文件已废弃（2026-08-22）
>
> redirect_to: references/prompts/prompt-guide.md
> deprecated_since: 2026-08-22
> reason: 版本演进遗留，本文件为 prompt-guide.md 的旧版（v2.2 唯一真源）
>
> **原因（详）**：版本演进遗留。本文件（5W2H 简化版 Prompt 实战案例）是 `prompt-guide.md` 的**旧版**；`prompt-guide.md` 为同一手册的 **v2.2 演进**，补齐 T 层映射（单工具/组合/系统级→路由）+ 触发词探测 + 交叉引用。
>
> **请使用**：`references/prompts/prompt-guide.md`（v2.2 唯一真源）。
>
> **不删除原因**：历史测试（`qcm_super_reverse_test.py`）仍以本文件为样本，故保留不删；git 历史也已留痕。**后续新内容一律不得引用本文件。**
>
> **物理清理**：观察期满（≥30 日）+ 月度评审确认 + 人工核准后，移入 `references/archive/`（每 1 个季度物理清理窗口）。

# QCM 应用提示词手册（5W2H 简化版 Prompt 实战案例）

> 万能公式：`[角色 Who] + [场景 Where] + [问题/目标 What] + [交付] + [深度:单工具/组合/系统级]`
> 写全 Who + Where + What 三要素，Skill 即精准路由、不场景错配；深度（How much）决定回「单工具步骤」还是「组织级治理体系」。

---

## 一、Who（角色）/ Where（场景）/ What（问题）三要素速查表

| 案例 | Who 角色 | Where 场景 | What 问题/目标 |
|---|---|---|---|
| A1 戴明系统观 | 管理者 | 现场/会议 | 质量会议开了但不良没降 |
| A2 大野耐一 TPS | 工艺/班组长 | CNC 车间 | 在制品堆积、换型慢 |
| A3 克劳士比零缺陷 | 质量经理 | 全员 | 一线"差不多就行"文化 |
| A4 石川馨品管圈 | 班组长 | 现场/班组 | 推 QC 小组/品质圈 |
| B1 SPC 控制图 | QE | 冲压/生产制造 | 尺寸过程受控、Cpk 达标 |
| B2 8D | SQE | 采购/来料 | 供应商来料尺寸超差根治 |
| B3 FMEA 七步法 | PE | 产品开发/生产制造 | 失效模式预防优先 |
| B4 APQP/PPAP | 项目/质量 | 产品开发/采购 | 量产放行 Gate |
| B5 Poka-Yoke | PE | 冲压/过程工艺 | 毛刺防错、不制造不良 |
| C1 班组长一日管理 | 班组长 | 现场 | 日常管理节奏落地 |
| C2 报联商沟通 | 现场管理者 | 现场 | 上下级沟通断点 |
| C3 问题分析 A3 | IPQC/班组长 | 现场 | 异常闭环、一页纸报告 |
| C4 角色能力育成 | 培训者 | 现场 | 一线质量员能力缺口 |
| D1 六层级治理 | 质量经理 | 全价值链 | 搭公司级治理体系 |
| D2 SQGK 供应商现场 | SQE | 供应链 | 帮供应商建现场管理 |
| D3 注塑实战推演 | PE/QE | 注塑车间 | 缩水/变形痛点根治 |
| D4 quality-in 二维矩阵 | 选型者 | 五场景 | 按场景选工具、防错配 |
| D5 书单路线 | 学习者 | — | 系统学质量管理的阅读路线 |
| D6 四维拆解 | 定位者 | — | 交叉定位风险相关人/书/工具 |
| D7 行业案例对标 | 对标者 | 行业 | 借鉴闭环质量范式 |

---

## 二、19 个简化 Prompt 实战案例（完整卡）

每张卡含：可复制 `Prompt` + `5W2H 拆解` + `路由文件` + `期望交付物`。

### A. 人物视角类（用 XX 大师看问题）

**A1 · 戴明系统观**
```
用戴明的系统观，看"为什么质量会议开了但不良没降"，给改进抓手
```
- **5W2H**：Who=管理者 / Where=现场 / What=会议无效 / Why=找改进抓手 / How=大师视角 / How much=组合级
- **路由**：`references/people/02-deming.md`
- **交付**：系统观诊断（局部优化≠系统改进）+ 14 点对应项 + PDCA 切入建议

**A2 · 大野耐一 TPS**
```
大野耐一的视角：CNC 车间在制品堆积、换型慢，怎么用 TPS 消除浪费
```
- **5W2H**：Who=工艺/班组长 / Where=CNC / What=在制品+换型 / Why=降本增效 / How=TPS视角 / How much=组合级
- **路由**：`references/people/08-ohno.md` + `workshop.md §2`
- **交付**：七种浪费识别 + JIT/自働化 + SMED 快换建议

**A3 · 克劳士比零缺陷**
```
克劳士比零缺陷视角：一线觉得"差不多就行"，怎么把 ZD 落成管理政策而非罚错 KPI
```
- **5W2H**：Who=质量经理 / Where=全员 / What=质量意识 / Why=文化落地 / How=ZD视角 / How much=系统级
- **路由**：`references/people/04-crosby.md`
- **交付**：ZD 四原则 + 政策设计（非考核鞭子）+ 质量成本 COPQ 说服逻辑

**A4 · 石川馨品管圈**
```
石川馨视角：怎么在班组推 QC 小组/品质圈，给一个启动模板
```
- **5W2H**：Who=班组长 / Where=现场 / What=一线改善 / Why=全员参与 / How=品管圈视角 / How much=组合级
- **路由**：`references/people/05-ishikawa.md` + `gk-management.md §7`
- **交付**：QCC 组建步骤 + 课题选择 + 活动记录模板

### B. 工具应用类（查工具怎么一步步用）

**B1 · SPC 控制图**
```
SPC 控制图在冲压尺寸管控怎么用？给 Xbar-R 描点步骤、判异准则、Cpk≥1.33 判据
```
- **5W2H**：What=SPC / Where=冲压·生产制造 / Why=过程受控 / How=标准步骤 / How much=单工具
- **路由**：`references/tools-examples.md`（#4）+ `workshop.md §1`
- **交付**：抽样→描点→休哈特判异 8 准则→Cpk 评估→处置门槛

**B2 · 8D**
```
8D 处理供应商来料尺寸超差，给 D0–D8 每步模板 + D4 鱼骨+5why 数据验证要求
```
- **5W2H**：What=8D / Where=采购·来料 / Why=根治不复发 / How=标准步骤 / How much=单工具
- **路由**：`references/tools-examples.md`（#17）+ `governance.md`
- **交付**：D1–D8 模板 + D4 验证判据 + D7 回流 PFMEA/控制计划

**B3 · FMEA 七步法**
```
FMEA 七步法怎么落地？要 PFMEA 结构/功能/失效分析表格 + S/O/D 打分规则
```
- **5W2H**：What=FMEA / Where=产品开发·生产制造 / Why=预防优先 / How=标准步骤 / How much=单工具
- **路由**：`references/tools-examples.md` + `methods.md`
- **交付**：七步表格 + RPN/AP 优先级 + 措施闭环

**B4 · APQP/PPAP**
```
APQP 五阶段 + PPAP 批准怎么走？给各阶段交付物清单和 PSW 签署 Gate
```
- **5W2H**：What=APQP/PPAP / Where=产品开发·采购 / Why=量产放行 / How=流程步骤 / How much=组合级
- **路由**：`references/governance.md`（Gate）+ `tools-examples.md`
- **交付**：五阶段交付物 + PPAP 等级 + 量产放行 Gate 条件

**B5 · Poka-Yoke**
```
Poka-Yoke 防错设计：选特性确认/计数/动作关联三类，给冲压毛刺防错方案
```
- **5W2H**：What=Poka-Yoke / Where=冲压·过程工艺 / Why=不制造不良 / How=设计步骤 / How much=单工具
- **路由**：`references/tools-examples.md`（#2）+ `workshop.md §1`
- **交付**：三类防错法选型 + 验证记录 + 防绕过设计

### C. 现场管理 / GK 软技能类

**C1 · 班组长一日管理**
```
我是班组长，给我"一日管理"SOP：班前会→巡线→异常→班后小结
```
- **5W2H**：Who=班组长 / Where=现场 / What=日常管理节奏 / Why=体系落地 / How=GK框架 / How much=组合级
- **路由**：`references/gk-management.md §1/§7`
- **交付**：四段式 SOP + 各段要点 + 看板/Andon 衔接

**C2 · 报联商沟通**
```
怎么用"报联商 Hō-Ren-Sō"改善上下级沟通？给报告/联络/商谈要点卡
```
- **5W2H**：Who=现场管理者 / Where=现场 / What=沟通断点 / Why=信息不断 / How=GK软技能 / How much=单模块
- **路由**：`references/gk-management.md §7.2`
- **交付**：三主题定义+时机+要点表 + 上下级 PDCA 沟通模型

**C3 · 问题分析 A3**
```
现场发现异常，用问题分析四阶段（界定→要因→方案→落地）给我 A3 报告框架
```
- **5W2H**：Who=IPQC/班组长 / Where=现场 / What=异常 / Why=闭环 / How=GK软技能 / How much=单模块
- **路由**：`references/gk-management.md §7.3`
- **交付**：四阶段步骤 + A3 一页纸模板 + 工具（MECE/鱼骨/二八）

**C4 · 角色能力育成**
```
帮我设计一线质量员"角色能力三维"育成地图（技能/认知/行为基础）+ 三阶段课程
```
- **5W2H**：Who=培训者 / Where=现场 / What=能力缺口 / Why=育成人才 / How=GK软技能 / How much=组合级
- **路由**：`references/gk-management.md §7.4`
- **交付**：三维模型 + 质量能力三阶段课程表 + 育成路径

### D. 治理 / 体系 / 实战类

**D1 · 六层级治理**
```
搭"工序→岗位→现场→车间→部门→公司"六层级治理，给 RACI 总表 + Gate 闭环 + 日周月季年节拍
```
- **5W2H**：What=治理地图 / Where=全价值链 / Why=系统质量 / How=治理框架 / How much=系统级
- **路由**：`references/governance.md`
- **交付**：六层级×五价值链矩阵 + RACI + Gate + 治理节拍

**D2 · SQGK 供应商现场**
```
供应商现场管理（SQGK）：怎么帮供应商立基准、做作业观察、跑三不原则
```
- **5W2H**：What=SQGK / Where=供应链 / Why=源头质量 / How=GK延伸 / How much=系统级
- **路由**：`references/gk-management.md §③` + `governance.md`
- **交付**：SQGK 步骤 + 供应商 audit 清单 + 与治理地图互补说明

**D3 · 实战推演（注塑）**
```
精密电子制造实战推演：注塑缩水/变形，给对应 4M+CTQ+控制计划打法
```
- **5W2H**：What=实战推演 / Where=注塑 / Why=痛点根治 / How=三面贯穿 / How much=组合级
- **路由**：`references/workshop.md §3`
- **交付**：4M 根因 + CTQ + 控制计划 + 5why/4M 三面咬合

**D4 · quality-in 二维矩阵**
```
按 quality-in 二维矩阵，生产制造场景首选哪些工具？给纵三档×横五场景推荐表
```
- **5W2H**：What=工具选型 / Where=五场景 / Why=不场景错配 / How=矩阵 / How much=组合级
- **路由**：`references/quality-in-tools.md`
- **交付**：二维矩阵 + 各场景首选工具 + 选型逻辑

**D5 · 书单路线**
```
想系统学质量管理，按 QCM 书单给我"新人→进阶→专家"三档 41 本阅读路线
```
- **5W2H**：What=读书 / Where=— / Why=体系学习 / How=书单 / How much=—
- **路由**：`references/books.md`
- **交付**：三档分层 + 每本一句话定位 + 配套人物/工具

**D6 · 四维拆解**
```
用四维拆解（战略/过程/工具/改进）帮我交叉定位：风险管理该看哪几位大师、哪几本书、哪些工具
```
- **5W2H**：What=交叉索引 / Where=— / Why=精准定位 / How=四维 / How much=组合级
- **路由**：`references/dimensions.md`
- **交付**：战略/过程/工具/改进四维交叉表 + 风险维度映射

**D7 · 行业案例对标**
```
看行业质量范式案例（航空宇航双归零 / 精密电子实战），给我可借鉴的闭环范式
```
- **5W2H**：What=案例 / Where=行业 / Why=对标借鉴 / How=案例 / How much=组合级
- **路由**：`references/cases.md` + `workshop.md`
- **交付**：行业范式 + 工具映射 + 落地注意（代入本企业真实值）

---

## 三、使用三原则（避免踩坑）

1. **写全三要素** Who + Where + What → Skill 精准路由，不场景错配。
2. **标深度** 单工具（要步骤）/ 组合（多工具解题）/ 系统级（搭体系）。
3. **带数据** 凡主张带数据（如"不良率 12%→≤1%"），无数据不决策（戴明）。

> 简化 prompt 填空公式：`[我的角色] + [价值链/工艺场景] + [具体问题/目标] + [要什么交付] + [深度]`。例：`我是PE + 冲压 + 毛刺复发 + 给4M根因展开表+防错方案 + 组合级` → 自动路由到 `workshop §1` + `tools-examples Poka-Yoke`。
