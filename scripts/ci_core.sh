#!/usr/bin/env bash
# QCM CI 核心基线（V8.3.2 T3 · 无环境依赖 · 干净环境必绿）
# 覆盖：8 引擎 + v82 + 路由黄金 + 守卫（guardian 引擎）+ 双绑 + 词源语义检测 + 热词生命周期 + 实体层
# 用法：bash scripts/ci_core.sh  （QCM_ROOT 自动探测；可设 QCM_NO_REPORT=1）
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
# Git Bash 下转 Windows 路径（Python os.path.join 需要 \ 风格）
if command -v cygpath >/dev/null 2>&1; then
  ROOT="$(cygpath -w "$ROOT")"
fi
export QCM_ROOT="$ROOT"
export QCM_NO_REPORT=1
PY="python3"
[ -n "$QCM_PYTHON" ] && PY="$QCM_PYTHON"

echo "=== [1/11] 8 引擎回归 ==="
$PY tests/engines/qcm_all_test.py
$PY tests/engines/qcm_cross_test.py
$PY tests/engines/qcm_loop_test.py
$PY tests/engines/qcm_combo_test.py
$PY tests/engines/qcm_super_test.py
$PY tests/engines/qcm_super_reverse_test.py
$PY tests/engines/qcm_full_test.py
$PY tests/engines/qcm_lowfreq_test.py

echo "=== [2/11] V8.2 集成测试 ==="
$PY tests/qcm_v82_test.py

echo "=== [3/11] 路由黄金用例（P0 歧义回归护栏）==="
$PY tests/qcm_router_golden_test.py

echo "=== [4/11] 守卫检查（guardian 引擎 · 注册中心驱动 + S6 校准器 dry-run）==="
$PY core/guardian.py --check
$PY core/intent_calibrator.py --check || true

echo "=== [5/11] Manifest 双绑验证 ==="
$PY scripts/sync_manifest.py

echo "=== [6/11] 词源同类语义检测（V8.4 · 0 严重即绿）==="
$PY scripts/semantic_audit.py --check

echo "=== [7/11] 热词生命周期健康（容量/状态机）==="
$PY scripts/keyword_lifecycle.py --check

echo "=== [8/11] 实体层与知识库同步 ==="
$PY scripts/extract_entities.py --check

echo "=== [9/11] 全维度边界 + 压力测试（V8.4 · 输入/容量/阈值/实体/并发）==="
$PY tests/qcm_boundary_test.py
$PY tests/qcm_stress_test.py

echo "=== [10/11] 歧义消解三级链 + 回灌闭环（V8.4 · 无 Key 零回归）==="
$PY tests/qcm_ambiguity_test.py

echo "=== [11/11] 下挂链路（V8.4+ · four-aspect→3A5WHY 下挂最小约束）==="
$PY tests/qcm_hung_chain_test.py

echo ""
echo "✅ CI 核心基线全部通过"
