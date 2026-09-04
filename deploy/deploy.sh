#!/usr/bin/env bash
# =============================================================================
# QCM MCP Server · 一键部署脚本（V8.4 C2 产品化）
# -----------------------------------------------------------------------------
# 用法：
#   bash deploy/deploy.sh                 # 默认：检查 → 构建 → 运行 → 健康检查
#   bash deploy/deploy.sh --check        # 仅检查前置依赖（docker / 配置 / 端口）
#   bash deploy/deploy.sh build          # 仅构建镜像
#   bash deploy/deploy.sh up             # 构建 + 运行容器（后台）
#   bash deploy/deploy.sh health         # 仅执行健康检查（轮询 /health/live）
#   bash deploy/deploy.sh status         # 查看容器/服务状态
#   bash deploy/deploy.sh down           # 停止并移除容器
#   bash deploy/deploy.sh compose        # 使用 docker compose（--no-build · 需先 build）
#   bash deploy/deploy.sh helm           # 安装到 Kubernetes（helm · 可选）
#   bash deploy/deploy.sh --help         # 帮助
#
# 设计要点：
#   - 主部署路径用 `docker build`（构建上下文=skill 根）+ `docker run`，
#     规避 docker-compose.yml 既有 build 上下文错配（其 build:. 指向 deploy/docker/）。
#   - qcm_config.yaml 缺失时从 scripts/config.example.yaml 生成最小可用配置，保证构建/挂载不失败。
#   - 健康检查轮询 /health/live（与 Dockerfile HEALTHCHECK 一致）。
# =============================================================================
set -euo pipefail

# ---- 路径解析（兼容符号链接 / 任意 CWD）----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKER_DIR="${SKILL_ROOT}/deploy/docker"
COMPOSE_FILE="${DOCKER_DIR}/docker-compose.yml"
CONFIG_EXAMPLE="${SKILL_ROOT}/scripts/config.example.yaml"
CONFIG_FILE="${SKILL_ROOT}/qcm_config.yaml"
IMAGE_NAME="qcm/mcp-server:1.0.1"
CONTAINER_NAME="qcm-mcp"
HOST_PORT="${QCM_HOST_PORT:-8080}"
HEALTH_URL="http://localhost:${HOST_PORT}/health/live"

log()  { printf '\033[36m[deploy]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[ ok ]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
err()  { printf '\033[31m[FAIL]\033[0m %s\n' "$*"; }

usage() {
  sed -n '3,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ---- 前置依赖检查 ----
check_prereqs() {
  local fail=0
  log "检查前置依赖..."
  if ! command -v docker >/dev/null 2>&1; then
    err "docker 未安装（https://docs.docker.com/get-docker/）"; fail=1
  else
    ok "docker: $(docker --version 2>/dev/null | head -1)"
  fi
  if [[ ! -f "${CONFIG_EXAMPLE}" ]]; then
    err "配置示例缺失：${CONFIG_EXAMPLE}"; fail=1
  fi
  # 端口占用检查（仅当 docker 可用时）
  if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Ports}}' 2>/dev/null | grep -q ":${HOST_PORT}->"; then
      warn "端口 ${HOST_PORT} 已被占用（若为本服务旧实例可忽略，或用 down 先停止）"
    fi
  fi
  # 配置桩生成提示
  if [[ ! -f "${CONFIG_FILE}" ]]; then
    warn "qcm_config.yaml 缺失 → 将用最小配置桩（来自 config.example.yaml）以保证构建/挂载"
  fi
  [[ $fail -eq 0 ]]
}

# ---- 确保最小配置存在 ----
ensure_config() {
  if [[ ! -f "${CONFIG_FILE}" ]]; then
    log "生成最小配置：${CONFIG_FILE}"
    cp "${CONFIG_EXAMPLE}" "${CONFIG_FILE}"
    ok "已生成 qcm_config.yaml（生产环境请按需修改 token / LLM key）"
  fi
}

# ---- 构建镜像 ----
build_image() {
  ensure_config
  log "构建镜像 ${IMAGE_NAME}（上下文=${SKILL_ROOT}）"
  if docker build -f "${DOCKER_DIR}/Dockerfile" -t "${IMAGE_NAME}" "${SKILL_ROOT}"; then
    ok "镜像构建完成：${IMAGE_NAME}"
  else
    err "镜像构建失败"; return 1
  fi
}

# ---- 运行容器（主部署路径）----
run_container() {
  ensure_config
  # 若已存在同名容器，先移除
  if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log "移除已存在的容器 ${CONTAINER_NAME}"
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
  log "启动容器 ${CONTAINER_NAME}（端口 ${HOST_PORT}→8080）"
  docker run -d --name "${CONTAINER_NAME}" \
    -p "${HOST_PORT}:8080" \
    -e QCM_ROOT=/app \
    -e QCM_AUDIT_DIR=/var/log/qcm-mcp \
    -e PYTHONPATH=/app/scripts \
    -e DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}" \
    -e ZHIPU_API_KEY="${ZHIPU_API_KEY:-}" \
    -v "${SKILL_ROOT}/logs:/var/log/qcm-mcp" \
    -v "${CONFIG_FILE}:/app/qcm_config.yaml:ro" \
    --restart unless-stopped \
    "${IMAGE_NAME}" \
    python scripts/qcm_mcp_server.py --transport http --host 0.0.0.0 --port 8080
  ok "容器已启动"
}

# ---- 健康检查（轮询 /health/live）----
health_check() {
  local retries="${HEALTH_RETRIES:-30}"
  local wait="${HEALTH_WAIT:-2}"
  log "健康检查 ${HEALTH_URL}（最多 ${retries} 次，间隔 ${wait}s）"
  for i in $(seq 1 "$retries"); do
    if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
      ok "服务健康：${HEALTH_URL}"
      # 打印概览
      curl -fsS "http://localhost:${HOST_PORT}/health" 2>/dev/null || true
      return 0
    fi
    printf '.'
    sleep "$wait"
  done
  echo
  err "健康检查超时（查看日志：docker logs ${CONTAINER_NAME}）"
  return 1
}

# ---- docker compose（--no-build，需先 build）----
compose_up() {
  if ! docker compose version >/dev/null 2>&1; then
    err "docker compose 不可用（需 Docker Desktop / compose v2）"; return 1
  fi
  log "docker compose up（--no-build）"
  docker compose -f "${COMPOSE_FILE}" up -d --no-build
  health_check
}

# ---- 状态 ----
status() {
  log "容器状态："
  docker ps -a --filter "name=${CONTAINER_NAME}" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
}

# ---- 停止 ----
down() {
  log "停止并移除容器 ${CONTAINER_NAME}"
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 && ok "已停止" || warn "无运行实例"
}

# ---- Helm 安装（可选）----
helm_install() {
  if ! command -v helm >/dev/null 2>&1; then
    err "helm 未安装（https://helm.sh/）"; return 1
  fi
  local ns="${QCM_HELM_NS:-qcm}"
  local rel="${QCM_HELM_REL:-qcm-mcp}"
  log "Helm 安装 ${rel} → namespace ${ns}"
  helm upgrade --install "${rel}" "${SKILL_ROOT}/deploy/k8s/helm/qcm-mcp" \
    --namespace "${ns}" --create-namespace \
    --set image.repository=qcm/mcp-server --set image.tag=1.0.1 \
    "$@"
  ok "Helm release ${rel} 已就绪（kubectl -n ${ns} get pods）"
}

# ---- 主分发 ----
main() {
  local action="${1:-default}"
  case "$action" in
    --help|-h|help) usage; exit 0 ;;
    --check|check) check_prereqs ;;
    build) check_prereqs && build_image ;;
    up) check_prereqs && build_image && run_container && health_check ;;
    health) health_check ;;
    status) status ;;
    down|stop) down ;;
    compose) check_prereqs && build_image && compose_up ;;
    helm) helm_install "${@:2}" ;;
    default)
      check_prereqs || { err "前置检查未通过，终止部署"; exit 1; }
      build_image
      run_container
      health_check
      ;;
    *) err "未知命令：$action"; usage; exit 2 ;;
  esac
}

main "$@"
