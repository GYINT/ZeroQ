# QCM 变更日志（CHANGELOG）

> 依据：Keep a Changelog 规范
> 版本策略：对外发布版本统一为 **1.0.1**（SKILL.md / manifest / skill_meta / SERVER_VERSION / 镜像标签一致）。

---

## [1.0.0] - 2026-08-20 · 首次对外发布

### 新增（Added）
- **版本归一化**：对外发布版本统一为 `1.0.0`；内部开发版本基线重置为 `0.0.0`，二者相互独立。
- **外部依赖声明**：新增 `DEPENDENCIES.md`，声明必选/可选依赖清单与各自作用。
- **外部 API Key 声明**：新增 `API_KEYS.md`，声明 LLM Provider / MCP 认证 / Infoseek 协同密钥的环境变量名与效益（不含任何真实密钥值）。
- **对话历史待办**：新增 `outputs/QCM-优化升级待办.md`，汇总已完成工作与发布后优化升级路线。
- **行业知识包**：`references/industry/` 新增消费电子、新能源两个行业包（规模化知识扩展）。

### 变更（Changed）
- **SKILL.md / README.md 重写**：去除全部内部版本标注（V4.6→V8.3.1 散注），呈现面向外部用户的干净文档；架构（4 层级 / 5 范式 / 14 章协议 / 4 形态 / 场景路由 / 文件治理 / Infoseek 协同）内容完整保留。
- **manifest.yaml / skill_meta.json**：`version` 统一为对外发布版本 `1.0.1`；`description` 去除版本号前缀。
- **代码版本常量**：`mcp_server.py` 的 `SERVER_VERSION` 统一为 `1.0.0`；CLI help 与 `ws_push.py` 运行时日志去除内部版本标注。
- **CHANGELOG 收口**：1647 行内部开发史归档并脱敏，本文档仅保留面向发布的变更说明。
- **开源许可**：`license: Internal` → **Apache-2.0**（落地 `LICENSE` 全文，同步 frontmatter / manifest / skill_meta / openapi / README 徽章）。

### 环境补齐（Infoseek OAuth）
- `infoseek/scripts/infoseek_auth.py`：新增 `AuthManager`（client_credentials JWT 签发/RBAC）与 `SecretCipher`（Fernet/XOR 加密）。
- `infoseek/scripts/infoseek_mcp_server.py`：新增 `/oauth/token` 端点，`check_auth` 接受 `infoseek.` JWT。
- 结果：`qcm_mcp_v050_test` 与 `qcm_mcp_v060_test` 由条件 SKIP 转为真实通过（10/10）。

### 清理（Cleanup）
- 删除 `__pycache__` / `*.pyc` 缓存。
- 删除开发过程产物：`outputs/` 下的 C 类执行报告、Infoseek-OAuth 开发报告、semantic-audit 与 `_test_db`。
- 历史文档中明文密钥全部脱敏（`sk-***REDACTED***`）。

### 修复（Fixed）
- `disambiguation_cases.yaml` 污染案例（`spc→知识学习` 固化）已清空，歧义段回归 8/8。
- 关键词英文别名 enrich 的 YAML 空列表 falsy 写入 bug 已修复（113 词 / 135 条英文别名）。

### 安全（Security）
- 源码与发布包中不存在任何明文 API Key；所有密钥仅经环境变量在运行时注入。
- 发布包严格排除敏感文件：`.env`（真实 DeepSeek Key）、`key_state.json`（运行时状态）、`_user_meta.json`（宿主安装痕迹），对齐 `.gitignore` 约定。
- **安全提示**：历史嵌套版发布包曾包含 `.env`（本地产物），建议尽快轮换其中的 DeepSeek API Key。

---

## 版本策略说明

| 维度 | 版本 | 说明 |
|------|------|------|
| 对外发布版本 | `1.0.1` | 用户可见的统一版本（SKILL.md / manifest / skill_meta / SERVER_VERSION / 镜像标签）|
| 协议层标识 | `V8.0+` | `action-orders.md` 方法论演进轴，独立于产品发布版本 |
