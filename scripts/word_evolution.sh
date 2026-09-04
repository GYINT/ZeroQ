#!/usr/bin/env bash
# QCM 词源自进化闭环（V8.4 Step 4 · 观测→检测→决策→回灌→报告 + A5 运行监控）
# 用法：bash scripts/word_evolution.sh [--dry-run]
#   --dry-run：只观测+检测+决策建议，不写回词库（安全模式）
# A5：每次执行结果归档 references/automation_log/（含退出状态）· 供异常告警/趋势分析
# 接入：可挂 CI 周频 / 自动化定时执行（闭环自动运转）
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
if command -v cygpath >/dev/null 2>&1; then
  ROOT="$(cygpath -w "$ROOT")"
fi
export QCM_ROOT="$ROOT"
export QCM_NO_REPORT=1
export PYTHONIOENCODING=utf-8
PY="python3"
[ -n "$QCM_PYTHON" ] && PY="$QCM_PYTHON"
DRY=""
[ "$1" = "--dry-run" ] && DRY="--dry-run"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT/references/automation_log"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/word_evolution-$STAMP.log"

exec > >(tee -a "$LOG") 2>&1
echo "=== QCM 词源自进化（$STAMP${DRY:+ · dry-run}）==="

# 夜巡固定触发点 → 短抖动（默认 ≤60s，避免后台长跑 sleep 被会话切换清理导致"假运行/中断"）
# 原 0~3599s 抖动：词源周检每周一、夜巡兜底每月≤3次，重叠概率极低，长抖动仅放大中断风险、无并发收益。
# 固定调度点仅作窗口起点；实际巡检在触发点后 0~60s 内随机启动。
SLEEP_SEC=$((RANDOM % 60))
echo "=== [0/8] 夜巡窗口抖动（固定触发点 ±60s 随机偏移）==="
echo "  抖动 ${SLEEP_SEC}s（实际巡检窗口：触发点后 0~60s 内）"
sleep "$SLEEP_SEC"

echo "=== [1/6] 观测环 · 未命中词统计 ==="
$PY core/hit_tracker.py --stats

echo "=== [2/6] 检测环 · 词源同类语义检测 ==="
$PY scripts/semantic_audit.py --check || true

echo "=== [3/6] 决策环 · 生命周期（回填/检查/迁移） ==="
$PY scripts/keyword_lifecycle.py --backfill
$PY scripts/keyword_lifecycle.py --check
if [ -z "$DRY" ]; then
  $PY scripts/keyword_lifecycle.py --promote || true
else
  echo "  (dry-run：跳过 --promote 写回)"
fi

echo "=== [4/6] 回灌环 · 词源协同（别名/M4） ==="
$PY scripts/corpus_sync.py alias --sync || true
$PY scripts/corpus_sync.py m4 --status | head -4

echo "=== [5/8] 行业包环（V8.5 · 归一化注入 + 命中观测）==="
$PY scripts/industry_sync.py --apply && $PY scripts/industry_sync.py --stats || true

echo "=== [6/8] 夜巡决策环（S7 · guardian --nightrun = 决策守卫 + 校准器跨周期推进）==="
$PY core/guardian.py --nightrun || true

echo "=== [6.2/8] R4 热度写回（R18+R19+R20 · 决策建议 → keyword.yaml 状态落地 + 归档观察期状态机）==="
# R20 归档观察期：QCM_AUTO_ARCHIVE=1 全自动放开前，须先经观察期验证（防误归档）。
# 状态文件 references/config/r4_archive_observation.json：
#   {status, observe_start, review_due, auto_archive_enabled, note}
#   - 首次执行 → 初始化 observing（review_due = 今天 + 30d）
#   - 观察期满且未放开 → 提示可开启 QCM_AUTO_ARCHIVE=1
#   - 已放开 → status=ready（全自动生效）
OBS_FILE="$ROOT/references/config/r4_archive_observation.json"
obs_update() {
  $PY - "$OBS_FILE" "$1" "$2" << 'PYEOF'
import json, sys, os
from datetime import datetime, timedelta
path, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.load(open(path, encoding='utf-8'))
except Exception:
    d = {}
if key == "init":
    today = datetime.now().date().isoformat()
    d = {"status": "observing", "observe_start": d.get("observe_start", today),
         "review_due": d.get("review_due", (datetime.now().date() + timedelta(days=30)).isoformat()),
         "auto_archive_enabled": d.get("auto_archive_enabled", False),
         "note": "R4 归档观察期（30d）· 期满未发现误归档可放开 QCM_AUTO_ARCHIVE=1"}
elif key in ("status", "auto_archive_enabled"):
    d[key] = val if key == "status" else (str(val).lower() == "true")
elif key == "note":
    d[key] = val
json.dump(d, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
sys.exit(0)
PYEOF
}
obs_status() {
  $PY - "$OBS_FILE" << 'PYEOF'
import json, sys
from datetime import datetime
path = sys.argv[1]
try:
    d = json.load(open(path, encoding='utf-8'))
except Exception:
    print("none"); sys.exit(0)
review_due = d.get("review_due", "")
if review_due and datetime.now().date().isoformat() >= review_due:
    print("due"); sys.exit(0)
print(d.get("status", "observing"))
PYEOF
}
if [ -z "$DRY" ]; then
  # ① 观察期状态机（每次夜巡持久化观测记录）
  obs_update init "" ""
  OBS_ST="$(obs_status)"
  # ② R19/R20 归档写回：QCM_AUTO_ARCHIVE=1 显式放开才全自动；否则 dry-run 归档 + 观察提示
  if [ "${QCM_AUTO_ARCHIVE:-0}" = "1" ]; then
    obs_update status "ready"
    obs_update auto_archive_enabled "true"
    $PY scripts/keyword_lifecycle.py --apply-r4 --yes --auto-archive || true
  else
    obs_update auto_archive_enabled "false"
    echo "  (R4 归档默认 dry-run：需 QCM_AUTO_ARCHIVE=1 显式开启全自动归档)"
    $PY scripts/keyword_lifecycle.py --apply-r4 --yes || true
    # 观察期到期提示（R20 · 1 个月观察机制）
    if [ "$OBS_ST" = "due" ]; then
      echo "  ⏰ 归档观察期已满（≥30d）：评估无误归档后可放开 QCM_AUTO_ARCHIVE=1 全自动"
    else
      echo "  ℹ️  归档观察期进行中（review_due 见 r4_archive_observation.json · 期满提示放开）"
    fi
  fi
else
  $PY scripts/keyword_lifecycle.py --apply-r4 || true
fi

echo "=== [6.5/8] 采样对账（V8.6 P6+R19/R20 · 采集出口归一化 ↔ 链B计数基准 + word 热度观测域）==="
# R20：--fix 补采样为显式可选（QCM_RECONCILE_FIX=1 才启用 · 默认 check 安全）
# 语义：word 域「未观测」自动补记 1 次（事件级缺口 · 历史遗留词收敛为实际观测）
if [ "${QCM_RECONCILE_FIX:-0}" = "1" ]; then
  $PY scripts/qcm_reconcile.py --delta 1 --word --fix || true
else
  echo "  (word 域补采样默认 check：需 QCM_RECONCILE_FIX=1 显式开启 --fix)"
  $PY scripts/qcm_reconcile.py --delta 1 --word || true
fi

echo "=== [6.7/8] 语料自适应自检（索引/分类/检入 · V8.6）==="
# 自适应分类 + 自动检入：扫描 references 大文件 → 分类(corpus/excluded) → 自动生成索引 + 登记 manifest
# 失败安全：未知路径默认 excluded；仅 --scan --auto 才写回 corpus_manifest.yaml
$PY scripts/gen_corpus_index.py --scan --auto || true

echo "=== [6.8/8] 归一化注册视图（V8.6 · 单一入口：字典/行业/语料 注册缺口统一呈现）==="
# 守卫归一化单一入口：--phase register 聚合 g011(字典)/g016(行业包)/g018(语料) 全部注册缺口
# 与 [6.7/8] 修复动作配合：先 --scan --auto 自动检入，再此处统一核验注册一致性
$PY core/guardian.py --phase register || true

echo "=== [6.9/8] 运行态缓存轮转（M1/M2 · 多 root 分类分层 + 容量/老化轮转 + 漂移）==="
# g019_runtime_cache：读 outputs/.runtime/corpus.db 台账 · 自动构建（若缺）
#   --build 全量构建（首次/漂移后自愈） · --rotate 容量上限+TTL 驱逐 · --drift 源漂移检测
$PY scripts/corpus_cache.py --build --scan 2>/dev/null || true
$PY scripts/corpus_cache.py --rotate --scan 2>/dev/null || true
$PY scripts/corpus_cache.py --drift 2>/dev/null || true

echo "=== [6.10/8] 容量容器台账轮转（M4/M5 · 持久化台账 + 快照保留 + 损坏自愈）==="
# g_capacity 去空壳：写台账快照（保留近 12 份） → 夜巡登记视图轮到它
# 损坏自愈：check_ledger() 返回 _corrupt 标记 → update_ledger(rebaseline=True) 重建基线
$PY -c "
import sys; sys.path.insert(0, 'scripts'); sys.path.insert(0, 'core')
from capacity import update_ledger, rotate_ledger, check_ledger
_, drift = check_ledger()
needs_rebuild = any(isinstance(d, dict) and d.get('_corrupt') for d in drift)
r = update_ledger(rebaseline=needs_rebuild)
rotate_ledger()
tag = '（台账损坏 → 已重建基线）' if needs_rebuild else ''
print(f'  台账更新: intents={len(r[\"current\"][\"intent\"])} domains={len(r[\"current\"][\"domain\"])} drift={len(r[\"drift\"])}{tag}')
" || true

echo "=== [6.11/8] 语义同类接守卫（M4/H2 · semantic_audit 归一化守门）==="
# H2：semantic_audit 此前仅 [2/6] 独立跑 --check，未接守卫中心。
# 此处汇入 --phase register（g017_r2 词面校准已在决策环）+ 保留语义同类独立检测。
$PY scripts/semantic_audit.py --check || true
$PY core/guardian.py --phase register 2>/dev/null | grep -i "反向R2\|词面" || true

echo "=== [6.12/8] 关联引用热度聚合（M5 · ⑤ 核心 · dry 建议，不回灌）==="
# 夜巡仅做 aggregate(weekly) + suggest(dry)；真实 backfill 每月 ≤2 次由定时器调度（M0.6）。
# 埋点 capture 是实时（corpus_loader 注入），此处不重放。
$PY scripts/ref_heat.py --aggregate --suggest ${DRY:+--dry} 2>/dev/null || true
echo "  (textrank 补召回已并入上一段 ref_heat 聚合窗口)"

echo "=== [6.12b/8] 双通道并集（M-T5 · cut=CI 高频 + textrank=夜巡低频 · 并集写 homology_union.json）==="
# 时间间隔联用：cut 通道在 CI/config_sync（g020 默认 algo=cut）高频触发，
# textrank 通道只在夜巡低频触发，两者各自独立扫描后按并集合并（交集双中=高置信）。
# report-only：仅写 outputs/.runtime/homology_union.json + 打印报告，不改语料。
$PY scripts/file_homology.py --algo both --union --union-report 2>/dev/null || true

echo "=== [6.13/8] 资产退休环（R4R · 孤儿/悬空/废弃三源扫描 + 30d 观察期推进 · report-only）==="
# 遗留资产动态管理：三源扫描（ref_graph 孤儿 + 悬空 + DEPRECATED）→ 登记观察期状态机。
# 30 天内不动作；期满后在月度评审（qcm-r4-archive-review 定时器）由人工 --retire/--revive/--whitelist。
# 物理清理每 1 个季度（QCM_RETIRE_CYCLE_DAYS=90）执行 mv → references/archive/（用户已确认周期）。
$PY scripts/asset_retirement.py --scan 2>/dev/null || true

echo "=== [A5] automation_log 轮转（全维度评估 C1 · 保留近 30 天）==="
# 爆炸盲区修复：word_evolution-*.log 无轮转地累积 → 删除 >30d 旧日志（保留当日）
find "$LOG_DIR" -name 'word_evolution-*.log' -mtime +30 -delete 2>/dev/null || true
echo "  automation_log 现存 $(find "$LOG_DIR" -name 'word_evolution-*.log' 2>/dev/null | wc -l) 份日志（>30d 已轮转）"

echo "=== [7/8] AI 路径健康检查（V8.4 B4 · L2 联网/LLM/Key 三态）==="
$PY -c "
import sys, os; sys.path.insert(0, 'scripts'); sys.path.insert(0, 'core')
from key_manager import _load_env_file; _load_env_file()
# ① LLM Key 状态
ds = bool(os.environ.get('DEEPSEEK_API_KEY'))
zp = bool(os.environ.get('ZHIPU_API_KEY') or os.environ.get('BOCHA_API_KEY'))
# ② L2 联网搜索可达性（Infoseek search_web 免费引擎 · 3s 探测）
web_ok = False
try:
    from infoseek_bridge import _web_search_infoseek
    web_ok = _web_search_infoseek('SPC 统计过程控制', max_results=2) is not None
except Exception:
    pass
print(f'  LLM(DeepSeek): {\"✅\" if ds else \"❌\"} · 搜索Key(智谱/博查): {\"✅\" if zp else \"❌\"} · L2联网: {\"✅\" if web_ok else \"❌\"}')
print(f'  状态: {\"全通道可用\" if (ds or zp) and web_ok else \"部分可用（LLM=\" + (\"有\" if ds else \"无\") + \" · 联网=\" + (\"有\" if web_ok else \"无\") + \"）\"}')
" || true

echo "=== [8/8] 指标采集 ==="
$PY -c "import sys; sys.path.insert(0, 'scripts'); from metrics import record_keyword_health, metrics; record_keyword_health(); print([l for l in metrics.export().splitlines() if 'qcm_' in l and not l.startswith('#')][-6:])"

echo ""
echo "✅ 词源自进化闭环执行完成（观测→检测→决策→回灌→行业包→夜巡决策环→语料→缓存→容器→AI健康→指标）${DRY:+（dry-run · 未写回词库）}（归档: $LOG）"
