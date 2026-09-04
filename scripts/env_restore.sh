#!/usr/bin/env bash
# env_restore.sh — ZeroQ 依赖与协同 Skill 环境恢复辅助脚本
# 用途：环境重置或迁移后一键恢复核心依赖；探测 Infoseek 协同 Skill 的安装位置
# 用法：bash scripts/env_restore.sh [--all|--deps|--infoseek]
set -e

# Infoseek 根：env 优先 > 本地用户级 skills 目录（归一化 · 消灭硬编码）
INFOSEEK_ROOT="${INFOSEEK_ROOT:-}"
if [ -z "$INFOSEEK_ROOT" ] && [ -d "$HOME/.workbuddy/skills/infoseek" ]; then
    INFOSEEK_ROOT="$HOME/.workbuddy/skills/infoseek"
fi
INFOSEK_SCRIPTS="${INFOSEEK_ROOT:+$INFOSEEK_ROOT/scripts}"

echo "=== ZeroQ 环境恢复 ==="

restore_deps() {
    echo "[1/3] 安装核心依赖..."
    pip install -q websockets graphql-core PyYAML         opentelemetry-api opentelemetry-sdk         opentelemetry-exporter-otlp-proto-http opentelemetry-exporter-otlp-proto-grpc 2>&1 | tail -1
    python3 -c "import websockets, graphql, opentelemetry; print('  deps ok:', websockets.__version__, graphql.__version__)"
}

restore_infoseek() {
    echo "[2/3] 探测 Infoseek 协同 Skill..."
    if [ -z "$INFOSEEK_ROOT" ]; then
        echo "  ⚠️ 未检测到 Infoseek（设置 INFOSEEK_ROOT 或安装到 ~/.workbuddy/skills/infoseek 后重试）"
        return 0
    fi
    if [ -f "$INFOSEK_SCRIPTS/infoseek_mcp_server.py" ]; then
        echo "  ✅ Infoseek 已就绪：$INFOSEEK_ROOT"
    else
        echo "  ⚠️ $INFOSEEK_ROOT 存在但缺少 scripts/infoseek_mcp_server.py（版本不完整）"
    fi
    # socket import 补丁（write_audit_log 依赖；幂等）
    if [ -f "$INFOSEK_SCRIPTS/infoseek_mcp_server.py" ] && \
       ! grep -q "^import socket" "$INFOSEK_SCRIPTS/infoseek_mcp_server.py" 2>/dev/null; then
        sed -i 's/^import secrets$/import secrets\nimport socket/' "$INFOSEK_SCRIPTS/infoseek_mcp_server.py"
        echo "  已补 socket import"
    fi
}

restore_verify() {
    echo "[3/3] 验证..."
    python3 -m pytest -q 2>&1 | tail -2 || echo "  ⚠️ pytest 未安装或测试未就绪（pip install pytest）"
}

case "${1:---all}" in
    --deps)      restore_deps ;;
    --infoseek)  restore_infoseek ;;
    --verify)    restore_verify ;;
    --all|"")    restore_deps; restore_infoseek; restore_verify ;;
    *) echo "用法: $0 [--all|--deps|--infoseek|--verify]"; exit 1 ;;
esac
