# QCM 外部 API Key 清单与效益

> **安全声明**：本文档**仅声明环境变量名与作用**，不包含任何真实密钥值。
> 所有密钥均通过环境变量在运行时注入，源码中不存在明文密钥；历史文档中曾出现的明文密钥已在发布归档中脱敏。
> 生产环境请使用密钥管理（K8s Secret / Vault / `.env` 不入库）注入。

---

## 一、LLM Provider Key（可选 · 增强 `qcm_research` 等输出）

| 环境变量 | 对应服务 | 效益 | 缺失时行为 |
|---------|---------|------|-----------|
| `DEEPSEEK_API_KEY` | DeepSeek | 通用质量领域深度推理，默认主链路；真实模式 confidence≈0.92 | 降级到规则 mock（≈0.75）|
| `OPENAI_API_KEY` | OpenAI (GPT) | 兜底大模型，覆盖更广语料 | 跳过该 provider |
| `ANTHROPIC_API_KEY` | Anthropic (Claude) | 长上下文与严谨推理兜底 | 跳过该 provider |
| `DASHSCOPE_API_KEY` | 阿里云百炼 (Qwen) | 国产大模型兜底 | 跳过该 provider |
| `SCNET_API_KEY` | SCNet 国家超算（Kimi/GLM/Qwen/DeepSeek 聚合）| 国产算力合规接入 | 跳过该 provider |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI | 企业级合规托管兜底 | 跳过该 provider |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI | 端点地址（配合上者）| — |
| `ZHIPU_API_KEY` | 智谱 AI (GLM) | 中文语境检索增强兜底 | 跳过该 provider |
| `BOCHA_API_KEY` | 博查 AI 搜索 | 联网搜索通道（L2 联网能力）| 联网能力降级为不可用 |
| （Ollama / LM Studio）| 本地推理 | 私有化、零外发；无需 key | 本地端点不可达时跳过 |

**效益总结**：LLM key 用于把「规则模板输出」升级为「领域专家级输出」（含具体失效模式、4M1E 分析、工具引用）。无 key 时 Skill 仍 100% 可用，仅输出抽象度更高。

---

## 二、MCP Server 认证 Key（可选 · 服务端安全）

| 环境变量 | 作用 | 效益 |
|---------|------|------|
| `QCM_AUTH_TOKEN` | Bearer Token 静态认证 | 启用 `--require-token` 时保护 HTTP/SSE 端点 |
| `QCM_JWT_SECRET` | OAuth JWT 签发/校验密钥 | 启用 `/oauth/token` 时的 HMAC 签名密钥（**务必生产强随机**）|
| `QCM_REQUIRE_TOKEN` | 开关（0/1）| 是否强制 Token 认证 |
| `QCM_TENANTS_FILE` | 多租户配置 JSON | 按租户隔离 scope / corpus |

---

## 三、Infoseek 协同 Key（可选 · 跨 Skill OAuth）

| 环境变量 | 作用 | 效益 |
|---------|------|------|
| `INFOSEEK_ROOT` | Infoseek 安装根 | 跨 Skill 依赖解析（探测列表兜底）|
| `INFOSEEK_JWT_SECRET` | Infoseek 侧 OAuth JWT 密钥 | 与 QCM 协同时的签名密钥 |
| `INFOSEEK_CLIENT_ID` / `INFOSEEK_CLIENT_SECRET` | QCM→Infoseek OAuth 客户端凭证 | 跨设备 JWT 自动签发 |
| `INFOSEEK_REMOTE_URL` | Infoseek 远程地址 | 远程 HTTP 协同（本地 stdio 优先）|
| `INFOSEEK_AUDIT_DIR` | 审计日志目录 | 跨设备审计聚合落盘 |

---

## 四、可观测 / 部署 Key（可选）

| 环境变量 | 作用 |
|---------|------|
| `QCM_OTLP_ENDPOINT` / `QCM_OTLP_GRPC_ENDPOINT` | OTel 追踪导出端点 |
| `QCM_TRACE_EXPORTER` | console / otlp / otlp-grpc |
| `GRAFANA_ADMIN_PASSWORD` | Grafana 控制台密码（部署用）|
| `DASHSCOPE_API_KEY` 等 | 同第一节（部署 Secret 注入）|

---

## 五、密钥管理最佳实践

1. **绝不入库**：密钥只走环境变量 / Secret 挂载，禁止写入 `*.yaml` / `*.py` / `*.md`。
2. **最小暴露**：仅在使用对应能力的容器中注入所需 key。
3. **强随机**：`QCM_JWT_SECRET` / `INFOSEEK_JWT_SECRET` 用 `openssl rand -hex 32` 生成。
4. **轮换**：定期轮换 LLM Provider key 与 JWT 密钥。
5. **审计**：跨设备场景启用 `INFOSEEK_AUDIT_DIR` 落盘审计，便于合规追溯。

> QCM 默认 `mode=auto`：按 env key 自动判定 real / mock，缺 key 即降级，零配置可用。
