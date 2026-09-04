# ZeroQ 外部依赖清单与作用

> 本文档声明 ZeroQ Skill 运行所需的全部外部依赖及其作用。
> 配套密钥说明见 **`API_KEYS.md`**（仅变量名与作用，不含真实密钥值）。

---

## 一、必选依赖（运行时必需）

| 依赖 | 类型 | 作用 | 说明 |
|------|------|------|------|
| Python ≥ 3.10 | 运行时 | Skill 脚本执行环境 | 推荐 3.12；本机托管环境为 3.13 |
| PyYAML | Python 包 | 解析 `keyword.yaml` / `components.yaml` / `config` 等配置 | `requirements.txt` 唯一必装项 |
| Infoseek Skill | 协同 Skill（可选）| 缺口调研 / 归因 / 收敛的跨 Skill 协同 | 通过 `INFOSEEK_ROOT` 探测；未安装时自动降级，不影响主流程 |

---

## 二、可选依赖（按能力启用）

| 依赖 | 类型 | 启用能力 | 作用 |
|------|------|---------|------|
| `websockets` (≥17) | Python 包 | WebSocket 全双工推送（`--transport ws`）| 长任务 progress 实时推送 |
| `graphql-core` (3.x) | Python 包 | GraphQL Query/Mutation/Subscription | `/graphql` 端点与 WS 订阅 |
| `opentelemetry` SDK + OTLP 导出 | Python 包 | 分布式追踪 | 工具调用 span 导出至 Jaeger/Tempo/Collector |
| `cryptography` | Python 包 | Secret 加密（Fernet）| `SecretCipher` 优先加密方案（缺失则 XOR 兜底）|
| `uvicorn` / `gunicorn` | 进程管理器 | 多进程 HTTP（生产加固）| 替代内置 `multiprocessing` 方案 |
| Docker | 容器运行时 | 镜像化部署 | `deploy/docker/Dockerfile` + `deploy.sh` |
| Kubernetes + Helm | 编排 | 集群部署 | `deploy/k8s/helm/qcm-mcp` |
| Prometheus + Grafana | 可观测 | 指标采集与仪表盘 | `deploy/monitoring/` |

---

## 三、外部服务（LLM Provider，可选）

LLM 调用用于增强 `qcm_research` 等专业输出；**无 key 时自动降级到规则 mock**，不影响 Skill 功能。

| 服务 | 环境变量 | 作用 / 效益 |
|------|---------|------------|
| DeepSeek | `DEEPSEEK_API_KEY` | 通用质量领域推理（默认主链路）|
| OpenAI | `OPENAI_API_KEY` | GPT 系列模型兜底 |
| Anthropic | `ANTHROPIC_API_KEY` | Claude 系列模型兜底 |
| 阿里云百炼 / 通义 | `DASHSCOPE_API_KEY` | Qwen 系列模型兜底 |
| SCNet 国家超算 | `SCNET_API_KEY` | 国产大模型聚合（Kimi/GLM/Qwen/DeepSeek）|
| Ollama（本地）| 无需 key | 本地私有化推理（localhost:11434）|
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | 企业级合规托管 |
| LM Studio（本地）| 无需 key | 本地私有化推理（localhost:1234）|

---

## 四、依赖关系图

```
ZeroQ Skill
├─ Python 3.10+            （必选）
├─ PyYAML                  （必选）
├─ Infoseek Skill          （可选·协同）
├─ LLM Providers           （可选·增强，无 key 降级 mock）
├─ websockets / graphql-core / opentelemetry / cryptography  （可选·按能力）
└─ Docker / K8s / Prometheus / Grafana                     （可选·部署观测）
```

---

## 五、最小化运行（零外部依赖）

仅依赖 **Python + PyYAML + Infoseek（可选）** 即可完成全部 4 形态输出与协议路由；其余依赖均为能力增强项，缺失时不阻断主流程（graceful degradation）。
