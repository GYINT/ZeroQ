# 资产废弃（DEPRECATED）模板规范

> 版本：v1.0 · 2026-08-22 · 治理面：references/ 全资产
> 关联守卫：g020b（废弃资产・redirect_to 校验 · report-only）
> 治理循环：R4R（扫描 → 30 天观察 → 月度评审 → 人工 retire/revive/whitelist → **每 1 个季度物理清理**）

---

## 一、何时标记 DEPRECATED

任一资产满足以下条件时，应进入废弃流程（**标记 ≠ 删除**）：

| 条件 | 示例 |
|------|------|
| 内容被其他文件完整合并/取代 | prompt-cookbook.md → prompt-guide.md（v2.2） |
| 内容多段拼贴、全部有真源 | problem-solving.md → 3a5why.md / pd-qm-workflow.md |
| 主题错位（不在该目录职责域） | 治理类内容出现在 methods/ |
| 版本演进旧版存档 | 旧流程规范 → 新版本手册 |

## 二、DEPRECATED 头部模板（必填）

所有废弃文件头部**必须以 `> [!WARNING]` 引用块开头**，且**必须包含结构化字段**（供 g020b 机读校验）：

```markdown
> [!WARNING]
> ## ⚠️ DEPRECATED — 本文件已废弃（YYYY-MM-DD）
>
> redirect_to: `references/<dir>/<target>.md`     <!-- 唯一真源，多个用 ; 分隔 -->
> deprecated_since: YYYY-MM-DD                    <!-- 标记日期 -->
> reason: <一句话原因>                             <!-- 如：被 X 完整合并 -->
>
> **原因（详）**：<展开说明，含段落到真源的映射>
>
> **不删除原因**：<保留理由：测试样本 / 历史报告引用 / git 历史留痕>
>
> **物理清理**：观察期满（≥30 日）+ 月度评审确认 + 人工核准后，于最近一个季度清理窗口
> 移入 `references/archive/`。**仅当 archived 且无任何生效引用才可删除。**
```

### 字段约束（g020b 校验规则）

| 字段 | 必填 | 校验 |
|------|------|------|
| `redirect_to:` | ✅ | 目标文件必须存在于 references/（相对 app 根解析） |
| `deprecated_since:` | ✅ | ISO 日期格式 |
| `reason:` | ✅ | 非空 |
| `> [!WARNING]` 开头 | ✅ | 缺失则告警「废弃资产缺模板头」 |

## 三、废弃 ≠ 删除：四阶段生命周期

```
标记 DEPRECATED（模板头 + 结构化字段）
   → 30 天观察（asset_retirement.py 登记 observing）
   → 月度评审（qcm-r4-archive-review 定时器）
   → 人工处置三选一：
       retire      → 移 references/archive/（保留可逆）
       revive      → 摘除 DEPRECATED + 修复引用（内容仍有效）
       whitelist   → 永久保留（如测试样本基座，登记 asset_retirement.json whitelist）
   → 每 1 个季度物理清理窗口：对 retire 项执行 mv
```

## 四、存档目录语义

`references/archive/`（M0.4 已预留 EXCLUDE_DIRS）：

- ✅ **move 而非 delete**：保留 git 历史 + 可逆恢复
- ✅ 守卫（g020 同源 / g017 反向 / corpus_cache）自动排除 archive/，不误报
- ✅ 存档文件头部同样加 `> [!WARNING] ARCHIVED`（区别于 DEPRECATED，表示已物理退役）
- ❌ 不允许删除任何仍被 references/ 生效文件引用的存档项

## 五、g020b 校验行为（report-only）

- 扫描 references/**/*.md 中 `DEPRECATED` 头部块
- 缺失 `redirect_to:` / 目标不存在 / 无模板头 → 输出 `[废弃资产⑳b]` 警告
- **不自动修改、不自动删除**；修复动作由人工或治理自动化按 R4R 节奏执行