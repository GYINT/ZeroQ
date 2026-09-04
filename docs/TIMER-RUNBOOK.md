# QCM 定时器任务运维 Runbook

> 本文档是 README「十、自动化定时器任务（运维）」的**详细操作版**，面向运维 / 接手者。
> 提供逐任务命令、回写目标、验证方法与故障排查决策树。
> 最后更新：2026-09-01（含 L1 抖动修复 + D6 定时任务层解释器根因修复）。

---

## 0. 红线（先读，违反即回写空转）

1. **回写型任务只能跑 venv 解释器**（含 PyYAML 6.0.3）：
   - Windows：`~/.workbuddy/binaries/python/envs/default/Scripts/python.exe`
   - 类 Unix：`~/.workbuddy/binaries/python/envs/default/bin/python`
2. **绝对禁止**用裸托管 python `3.13.12/python.exe`（无 PyYAML → 回写链静默空转）。
3. **验证回写真实落地的唯一判据**：`references/config/keyword.yaml` 时间戳更新 + 日志出现 `✅ 已写回 N 个词`。日志"看起来跑完"不代表真的写回（裸 python 下 `|| true` 会吞掉 import 错误）。

---

## 1. 任务总览

| 任务 | Automation ID | 触发节奏 | 类型 | 入口命令 | 回写目标 |
|------|--------------|---------|------|---------|---------|
| 关联热度回灌 | `automation-1787382137111` | 每月 1 / 15 日 | 🔴 回写型 | `ref_heat.py --aggregate --backfill --apply` | `outputs/.runtime/ref_heat.json` |
| 词源自进化周检 | `automation-1787197054394` | 每周一 09:00 | 🔴 回写型 | `bash scripts/word_evolution.sh` | `references/config/keyword.yaml`（R4 热度 hot 化等） |
| R4 归档观察 | `automation-1787365144880` | 每月 1 日 09:30 | 🟢 只读评估 | R4 观察评估脚本 | 无（仅推进观察期） |
| 夜巡兜底 | `automation-1787312499382` | 每月 1 / 10 / 20 日 22:00 | 🟡 混合 | `bash scripts/word_evolution.sh --nightrun` | 弱回写（守卫决策环） |
| 孤儿语料巡检 | `automation-1787558509281` | 每周三 09:00 | 🟢 report-only | 孤儿语料巡检脚本 | 无（仅报告，绝不改写） |

> 查看 / 修改 automation：`automation_update view <id>` 或 `automation_update list`。

---

## 2. 运行解释器配置（最关键点 · D6 根因）

**为什么必须 venv**：`keyword_lifecycle` / `semantic_audit` / `corpus_sync` / `ref_heat` 均依赖 `import yaml`。若解释器无 PyYAML，这些环会 `ModuleNotFoundError` 失败，被脚本 `|| true` 静默吞掉 → 整个回写链空转（日志"跑完"但 0 回写）。这是 2026-09-01 发现并修复的核心根因。

**三个回写型 automation 当前配置**（已落地修复）：
- 词源周检 `1787197054394` / 夜巡兜底 `1787312499382`：prompt 内 `export QCM_PYTHON=<venv绝对路径>` 后跑脚本。
- 关联热度回灌 `1787382137111`：prompt 直接调用 `<venv>/python.exe scripts/ref_heat.py ...`。

**巡检当前 automation 是否用对解释器**：
```bash
automation_update view automation-1787197054394   # 搜索 prompt 中是否含 envs/default/Scripts/python.exe
automation_update view automation-1787312499382
automation_update view automation-1787382137111
```
若 prompt 仍指向 `python3` 或裸 `3.13.12/python.exe`，须按 §0 红线改回 venv。

**建议**：将 venv 解释器固化为 QCM 所有 automation 的默认运行环境，避免后续定时任务重蹈覆辙。

---

## 3. 逐任务运维手册

### 3.1 关联热度回灌（每月 1 / 15）
```bash
cd <QCM根目录>
QCM_REF_HEAT_APPLY=1 <venv>/python.exe scripts/ref_heat.py --aggregate --backfill --apply
```
- 需 `QCM_REF_HEAT_APPLY=1` 或 `--apply` 覆盖 dry，否则仅评估不落盘。
- 预期：打印 `applied / suggested` 数量；落盘 `outputs/.runtime/ref_heat.json`。
- 已知：当前 `applied=suggested=0`（事件采集面未全亮，见 §6）。
- 频率：**仅月度定时器触发，严禁每夜执行**。

### 3.2 词源自进化周检（每周一 09:00）
```bash
cd <QCM根目录>
export QCM_PYTHON=<venv>/python.exe
bash scripts/word_evolution.sh
```
- 环节链路：`[0]` 抖动 ≤60s → `[2/6]` 语义检测 → `[3/6]` 决策环 → `[6.2/8]` R4 热度写回 → `[6.12/8]` 完成。
- 验证：日志出现 `✅ 已写回 26 个词`；`references/config/keyword.yaml` 时间戳更新。
- 冒烟（不写回词库）：`bash scripts/word_evolution.sh --dry-run`。

### 3.3 R4 归档观察（每月 1 日 09:30 · 只读）
- 观察期未满则只读、不回写（正确行为）。
- `references/config/r4_archive_observation.json` 的 `observe_start` 幂等复用初值，不能单凭该字段判定今日写回。

### 3.4 夜巡兜底（每月 1 / 10 / 20 日 22:00 · 混合）
```bash
cd <QCM根目录>
export QCM_PYTHON=<venv>/python.exe
bash scripts/word_evolution.sh --nightrun
```
- 重点观测 `[6/8] guardian --nightrun` 决策环输出，确认兜底链真实落地（而非再出"日志停在 sleep"）。
- 若期间主链路已正常运行，可仅做简短确认。

### 3.5 孤儿语料巡检（每周三 09:00 · report-only）
- 仅产出巡检报告，**绝不自动改写语料**。
- 无需解释器特殊配置，但同样建议走 venv 以保持一致。

---

## 4. 故障排查决策树

| 症状 | 根因 | 处置 |
|------|------|------|
| 日志停在 `sleep` 抖动后即无后续输出 | 旧抖动机 `RANDOM%3600`（最长 1h）被会话切换清理后台 handle 中断（已修为 ≤60s） | 确认 `scripts/word_evolution.sh:28-33` 抖动 ≤60s；改用前台大 timeout 运行 |
| 回写 0 词 / keyword.yaml 不更新 | 跑在裸 python（无 PyYAML）→ `import yaml` 失败被 `|| true` 吞 | §2 改 automation prompt 指向 venv；前台 venv dry-run 复验 |
| 日志 `[2/6]` 出现 `import yaml` / `ModuleNotFoundError` | 解释器配对（同上 D6） | 同"回写 0 词" |
| 关联热度回灌 `applied=0` | 事件采集面未全亮（D7 架构面） | 属架构已知项，非脚本修复范围，需独立决策 |
| 多实例同刻并发 | 抖动窗口重叠（概率极低） | 当前 ≤60s 抖动已足够；无需额外处理 |

---

## 5. 验证清单（每次触发后勾选）

- [ ] 回写型任务：`<venv>/python.exe` 已被实际使用（日志无 `ModuleNotFoundError`）
- [ ] 词源周检 / 夜巡兜底：`references/config/keyword.yaml` 时间戳已更新
- [ ] 日志含 `✅ 词源自进化闭环执行完成` 与 `✅ 已写回 N 个词`
- [ ] 关联热度回灌：`outputs/.runtime/ref_heat.json` 已落盘
- [ ] 抖动实测 `≤60s`（无 1h 假运行）
- [ ] 无 `import yaml` / `No module named yaml` 报错

---

## 6. 已知项与收敛（2026-09-01）

| 项 | 状态 | 说明 |
|----|------|------|
| 抖动过长（假运行） | ✅ 已收敛 | `scripts/word_evolution.sh:28-33` `RANDOM%3600` → `RANDOM%60` |
| D6 解释器根因 | ✅ 已修 | 3 个回写型 automation prompt 固定指向 venv（含 PyYAML 6.0.3） |
| D7 采集面（回灌 0 事件） | ⏳ 架构已知 | Agent 直读 `references/*.md` 绕过 Python 入口，致 `ref_heat.capture` 活死路径；待独立决策 |

---

## 7. 待验证点（下次触发即验证）

- 🕐 **夜巡兜底今晚 22:00** 首次用 venv 真实运行 → 重点观测 `[6/8] guardian --nightrun` 决策环。
- 📅 **关联热度回灌 9/15** 用 venv 真实回灌 → 验证 D7 采集面是否有事件落盘（仍 0 则坐实 D7 架构面）。

---

*本 Runbook 配套 README「十、自动化定时器任务（运维）」。铁证级修复记录见 `outputs/QCM-定时器回写状态核查与L1-D6修复-2026-09-01.md`。*
