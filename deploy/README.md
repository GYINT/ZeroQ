# QCM MCP Server · Docker 全栈部署（E1-02）

一键拉起 **QCM MCP Server + Prometheus + Grafana** 全栈可观测演示环境。

## 目录结构

```
deploy/
├── Dockerfile                      # QCM MCP Server 生产镜像（依赖取自 skill 根 requirements*.txt + E1-03/TLS 运行时依赖）
├── docker-compose.yml              # 全栈编排（qcm-mcp / prometheus / grafana）
├── prometheus.yml                  # Prometheus 抓取配置（scrape /metrics）
└── grafana/
    └── provisioning/
        ├── datasources/datasource.yml   # Prometheus 数据源（自动接入）
        └── dashboards/
            ├── dashboard.yml             # 仪表盘 provider 声明
            └── qcm-overview.json         # QCM 概览仪表盘（up / 请求速率 / 错误速率）
```

## 快速开始

```bash
# 在 QCM skill 根目录执行（compose 的 build context 为 skill 根）
docker compose -f deploy/docker-compose.yml up -d --build
```

启动后访问：

| 服务 | 地址 | 说明 |
|------|------|------|
| MCP HTTP API | http://localhost:8080/health | 健康检查（overview） |
| OpenAPI 文档 | http://localhost:8080/openapi.json | E1-05 动态生成 |
| 指标端点 | http://localhost:8080/metrics | Prometheus 抓取源 |
| Prometheus | http://localhost:9090 | 指标查询 |
| Grafana | http://localhost:3000 | 可视化（默认 admin/admin） |

## 环境变量（可选）

| 变量 | 默认 | 说明 |
|------|------|------|
| `QCM_REQUIRE_TOKEN` | `0` | 设为 `1` 启用 Bearer Token 认证 |
| `QCM_TOKEN` | 空 | Token 值（配合 `QCM_REQUIRE_TOKEN=1`） |
| `GRAFANA_USER` / `GRAFANA_PASSWORD` | `admin` / `admin` | Grafana 登录凭据 |

## TLS（可选 · E1-04）

镜像内 `scripts/mcp_server.py` 支持 `--tls-cert/--tls-key/--tls-watch`。
在 compose 中给 `qcm-mcp` 服务挂载证书并附加命令即可启用 HTTPS：

```yaml
  qcm-mcp:
    command: ["python", "scripts/mcp_server.py", "--transport", "http",
              "--host", "0.0.0.0", "--port", "8080",
              "--tls-cert", "/certs/fullchain.pem", "--tls-key", "/certs/privkey.pem",
              "--tls-watch"]
    volumes:
      - ./certs:/certs:ro
```

配合 `scripts/certbot_renew_hook.sh` 可实现证书续期零重启（详见 E1-04）。

## 停止

```bash
docker compose -f deploy/docker-compose.yml down
```

> 注：本环境（沙箱无 docker）仅做 YAML/JSON 语法与结构校验，未实际构建镜像。
