# ZeroQ 平台适配说明（PLATFORM）

> 本文档说明 ZeroQ 在各生态平台的适用方式与 Skill 元数据字段的兼容边界，供集成方与维护者参考。
> 评估结论详见 `outputs/ZeroQ-多生态平台适用性评估.md`。

---

## 一、运行方式总览

ZeroQ 提供两种运行形态，二者独立：

| 形态 | 入口 | 适用场景 |
|------|------|---------|
| **Skill 形态** | `SKILL.md`（frontmatter 元数据 + 协议/知识资产）| Agent 直接加载指令与知识，进行 4 形态输出 |
| **MCP Server 形态** | `scripts/mcp_server.py`（stdio/http/ws）| 任意 MCP 客户端调用 `qcm_search` / `qcm_research` / `qcm_decide` / `qcm_evaluate` 等工具 |

---

## 二、Skill 元数据字段兼容边界

`SKILL.md` frontmatter 字段分为两类：

### 通用字段（Anthropic Claude Skills / CodeBuddy 等生态通用）
`name` `version` `display_name` `description` `author` `license` `entry_point`

### ZeroQ 增强字段（本生态专属，其他宿主宽松忽略）
| 字段 | 作用 | 其他宿主行为 |
|------|------|-------------|
| `protocol_authority` | 协议层单一权威指向 | 忽略（不报错）|
| `manifest` / `manifest_sync` | Manifest 双绑与同步脚本 | 忽略 |
| `output_validator` | 4 形态输出校验器 | 忽略 |
| `test_engine` | 回归声明 | 忽略 |

> 结论：跨生态加载 ZeroQ Skill 时主体字段可被识别；增强字段不破坏解析，仅失去深层校验能力。

---

## 三、主流平台接入示例

### 3.1 Claude（Code / Desktop）

```json
// claude_desktop_config.json（macOS: ~/.config/claude/ · Windows: %APPDATA%\Claude\）
{
  "mcpServers": {
    "qcm": {
      "command": "python",
      "args": ["<QCM_ROOT>/scripts/mcp_server.py", "--transport", "stdio"]
    }
  }
}
```

### 3.2 Cursor / VS Code Copilot（`.mcp.json` 项目级）

```json
{
  "mcpServers": {
    "qcm": {
      "type": "stdio",
      "command": "python",
      "args": ["<QCM_ROOT>/scripts/mcp_server.py", "--transport", "stdio"]
    }
  }
}
```

### 3.3 HTTP/SSE 服务化（任意 MCP 客户端 / 云部署）

```bash
# 本地启动
python scripts/mcp_server.py --transport http --port 8080
# 客户端配置 URL: http://localhost:8080/sse （或 /rpc，按客户端协议）
```

### 3.4 Docker / K8s

```bash
bash deploy/deploy.sh build && bash deploy/deploy.sh up
# 或 Helm
helm install qcm-mcp deploy/k8s/helm/qcm-mcp -n qcm
```

---

## 四、LLM Provider 中立性

ZeroQ 不绑定任何推理厂商：`scripts/llm_router.py` 按环境变量自动探测
DeepSeek / OpenAI / Anthropic / DashScope / SCNet / Azure OpenAI / Ollama / LM Studio，
`mode=auto` 缺 key 自动降级 mock，**无 key 也可运行**。密钥清单见 `API_KEYS.md`。

---

## 五、已知边界

- **License**：Apache-2.0（见 `LICENSE`），可自由使用、修改与再分发（保留版权与许可声明）。
- **Infoseek 协同**：深度调研/归因能力依赖 WorkBuddy 生态的 Infoseek Skill；其他平台缺失时自动降级（缺口标注 `[Infoseek 补充]` 不产生、改用规则兜底），不阻塞主体流程。
- **插件 / WS 旁路推送**：ZeroQ 自有扩展机制，非 MCP 标准能力；其他平台无需关注。
- **开发工具链**：`scripts/ci_core.sh` / `env_restore.sh` 为 bash 脚本（仅开发/CI 侧，运行时不受影响）。
