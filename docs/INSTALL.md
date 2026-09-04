# QCM MCP Server 安装指南

## 系统要求

- Python 3.10+（推荐 3.12）
- 操作系统：Linux / macOS / Windows
- 内存：最低 256MB，推荐 1GB
- 磁盘：100MB（corpus 缓存）

## 1. 源码安装

### 1.1 克隆仓库

```bash
git clone <repository-url>
cd qcm-mcp
```

### 1.2 安装依赖

```bash
# 核心依赖（必需）
pip install -r requirements.txt

# 可选能力（WS/GraphQL/OTel/加密等，按需启用）
pip install -r requirements-optional.txt
```

依赖说明：
- 核心：`PyYAML`（必需）
- 可选：websockets（WS 传输）/ graphql-core（GraphQL）/ opentelemetry（追踪）/ cryptography（Secret 加密 Fernet）/ prometheus-client（指标）
- 完整依赖与作用见 `DEPENDENCIES.md`

### 1.3 启动服务

**stdio 模式**（最简单）：
```bash
python scripts/mcp_server.py
```

**HTTP/SSE 模式**：
```bash
python scripts/mcp_server.py --transport http --port 8080
```

**启用 Token 认证**：
```bash
export QCM_REQUIRE_TOKEN=1
export QCM_AUTH_TOKEN=$(openssl rand -hex 32)
python scripts/mcp_server.py --transport http --port 8080
```

**启用热重载**：
```bash
python scripts/mcp_server.py --watch-corpus --watch-interval 10
```

## 2. Docker 部署

### 2.1 单容器

```bash
# 构建
docker build -t qcm/mcp-server:1.0.1 .

# 运行
docker run -d \
  --name qcm-mcp \
  -p 8080:8080 \
  -e DEEPSEEK_API_KEY=<DEEPSEEK_API_KEY> \
  -e QCM_REQUIRE_TOKEN=1 \
  -e QCM_AUTH_TOKEN=secret \
  -v qcm-cache:/var/cache/qcm \
  -v qcm-audit:/var/log/qcm-mcp \
  qcm/mcp-server:1.0.1
```

### 2.2 Docker Compose（含 Prometheus + Grafana）

```bash
# 复制环境变量模板
export DEEPSEEK_API_KEY=<DEEPSEEK_API_KEY>
export QCM_AUTH_TOKEN=$(openssl rand -hex 32)
export GRAFANA_ADMIN_PASSWORD=admin

# 启动（仅 QCM）
docker compose up qcm-mcp

# 启动（完整栈：QCM + Prometheus + Grafana）
docker compose --profile observability up -d

# 访问
# - QCM MCP:    http://localhost:8080
# - Prometheus: http://localhost:9090
# - Grafana:    http://localhost:3000 (admin / $GRAFANA_ADMIN_PASSWORD)
```

## 3. Kubernetes / Helm 部署

### 3.1 准备

```bash
# 创建命名空间
kubectl create namespace qcm

# 创建密钥
kubectl create secret generic qcm-secrets -n qcm \
  --from-literal=deepseek-api-key=<DEEPSEEK_API_KEY> \
  --from-literal=openai-api-key=<OPENAI_API_KEY> \
  --from-literal=anthropic-api-key=<ANTHROPIC_API_KEY> \
  --from-literal=dashscope-api-key=<DASHSCOPE_API_KEY> \
  --from-literal=auth-token=$(openssl rand -hex 32) \
  --from-literal=jwt-secret=$(openssl rand -hex 32)

# 准备 PVC（审计日志）
cat <<EOF | kubectl apply -n qcm -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: qcm-audit-pvc
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
EOF
```

### 3.2 安装

```bash
helm install qcm-mcp ./helm/qcm-mcp -n qcm
```

### 3.3 验证

```bash
# Pod 状态
kubectl get pods -n qcm -l app.kubernetes.io/name=qcm-mcp

# Service
kubectl get svc -n qcm qcm-mcp

# Ingress（如启用）
kubectl get ingress -n qcm

# 端口转发测试
kubectl port-forward -n qcm svc/qcm-mcp 8080:8080
curl http://localhost:8080/health/live
```

### 3.4 升级

```bash
# 修改 values 后升级
helm upgrade qcm-mcp ./helm/qcm-mcp -n qcm
```

### 3.5 卸载

```bash
helm uninstall qcm-mcp -n qcm
# 保留 PVC（审计日志）
```

## 4. 配置

### 4.1 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `QCM_ROOT` | `<QCM_ROOT>` | Skill 根目录（env 覆盖，缺省自动推导）|
| `QCM_TRANSPORT` | stdio | 传输方式 |
| `QCM_PORT` | 8080 | HTTP 端口 |
| `QCM_REQUIRE_TOKEN` | 0 | 启用 Token 认证 |
| `QCM_AUTH_TOKEN` | - | Bearer Token |
| `QCM_JWT_SECRET` | 随机 | OAuth JWT 密钥 |
| `DEEPSEEK_API_KEY` | - | DeepSeek API Key |
| `OPENAI_API_KEY` | - | OpenAI API Key |
| `ANTHROPIC_API_KEY` | - | Claude API Key |
| `DASHSCOPE_API_KEY` | - | Qwen API Key |
| `QCM_CACHE_DIR` | `/tmp/qcm-cache` | Cache 目录 |
| `QCM_CACHE_DISABLE` | 0 | 禁用 Cache |
| `QCM_LLM_CACHE` | 1 | 启用 LLM Cache |
| `QCM_AUDIT_DIR` | `/tmp/qcm-mcp-audit` | 审计日志目录 |
| `QCM_TENANTS_FILE` | - | Multi-tenant JSON 文件 |
| `QCM_RATE_LIMIT_PER_IP` | 100 | IP 限流 |
| `QCM_RATE_LIMIT_PER_TOKEN` | 1000 | Token 限流 |

### 4.2 YAML 配置（推荐）

```bash
cp scripts/config.example.yaml qcm_config.yaml
# 编辑
vim qcm_config.yaml

# 启动（自动加载）
export QCM_CONFIG=/path/to/qcm_config.yaml
python scripts/mcp_server.py
```

## 5. 验证

### 5.1 健康检查

```bash
curl http://localhost:8080/health/live
# {"status":"alive","version":"1.0.1","protocol":"V8.0+","uptime_s":42}

curl http://localhost:8080/health/ready
# {"status":"ready","corpus_files":41,"llm":{"mode":"auto","providers_with_keys":["deepseek"]},...}
```

### 5.2 OAuth 流程

```bash
# 获取 token
TOKEN=$(curl -s -X POST http://localhost:8080/oauth/token \
  -d "grant_type=client_credentials&client_id=default-client&client_secret=$QCM_AUTH_TOKEN&scope=tools/call" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# 调用工具
curl -X POST http://localhost:8080/rpc \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"qcm_research","arguments":{"query":"焊接虚焊"}}}'
```

## 6. 升级

```bash
# 拉取最新代码
git pull

# 重新安装依赖
pip install -r requirements.txt --upgrade

# 重启服务
systemctl restart qcm-mcp  # 如果用 systemd

# 或 Docker
docker compose pull
docker compose up -d

# 或 K8s
helm upgrade qcm-mcp ./helm/qcm-mcp -n qcm
```

## 7. 卸载

```bash
# 源码
# 停止进程 + 删除目录

# Docker
docker stop qcm-mcp && docker rm qcm-mcp

# K8s
helm uninstall qcm-mcp -n qcm
```

## 下一步

- 阅读 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- 查看 [openapi.yaml](openapi.yaml) 完整 API
- 浏览 [CHANGELOG.md](CHANGELOG.md) 了解版本变更