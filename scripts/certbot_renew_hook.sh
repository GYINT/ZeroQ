#!/usr/bin/env bash
# certbot 续期部署钩子（E1-04 · QCM MCP Server）
#
# 用法：
#   certbot renew --deploy-hook scripts/certbot_renew_hook.sh
#
# 作用：将续期后的证书复制到 QCM 期望路径。QCM 以 --tls-watch 运行时，
#       文件监听线程会自动热加载新证书，无需重启进程。
#
# 环境变量：
#   QCM_TLS_CERT  QCM 证书目标路径（fullchain.pem）
#   QCM_TLS_KEY   QCM 私钥目标路径（privkey.pem）
#   CERTBOT_DRY_RUN / DRY_RUN  若为 1 则仅打印、不复制（dry-run 保护）

set -euo pipefail

if [ "${CERTBOT_DRY_RUN:-}" = "1" ] || [ "${DRY_RUN:-}" = "1" ]; then
  echo "[certbot-renew] dry-run 模式：跳过复制（不修改 QCM 证书）"
  exit 0
fi

: "${QCM_TLS_CERT:?请设置 QCM_TLS_CERT（QCM 证书目标路径）}"
: "${QCM_TLS_KEY:?请设置 QCM_TLS_KEY（QCM 私钥目标路径）}"

if [ -n "${RENEWED_LINEAGE:-}" ]; then
  cp -f "$RENEWED_LINEAGE/fullchain.pem" "$QCM_TLS_CERT"
  cp -f "$RENEWED_LINEAGE/privkey.pem"   "$QCM_TLS_KEY"
  echo "[certbot-renew] 已复制续期证书 → $QCM_TLS_CERT （QCM --tls-watch 将自动热加载，无需重启）"
else
  echo "[certbot-renew] 未检测到 RENEWED_LINEAGE，跳过（非 certbot 续期上下文）"
fi
