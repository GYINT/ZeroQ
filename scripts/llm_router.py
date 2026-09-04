#!/usr/bin/env python3
"""qcm_llm_router.py — QCM LLM Router

4 provider fallback chain:
  P0: deepseek (https://api.deepseek.com/v1)
  P1: openai    (https://api.openai.com/v1)
  P2: claude    (https://api.anthropic.com)
  P3: qwen      (https://dashscope.aliyuncs.com/compatible-mode/v1)

Usage:
  from llm_router import LLMRouter
  router = LLMRouter()
  result = router.call(prompt, task="research")

Environment Variables:
  DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / DASHSCOPE_API_KEY
  QCM_LLM_MODE = "real" | "mock" | "auto" (default "auto")

 模式：
- "real": 强制真实 API 调用（无 key 抛错）
- "mock": 强制 mock（不调 API）
- "auto": 优先 real（有 key 时），否则 mock
"""
import os
import json
import time
import hashlib
from typing import Optional, Dict, Any, List

# 4 Provider 配置
PROVIDERS = {
    "deepseek": {
        "priority": 1,
        "cost_per_1k": 0.001,  # V8.4 T3 成本感知
        "base_url": "https://api.deepseek.com/v1",
        "endpoint": "/chat/completions",
        "model": "deepseek-chat",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "DEEPSEEK_API_KEY",
        "max_tokens_param": "max_tokens",
        "timeout_s": 30,
    },
    "openai": {
        "priority": 2,
        "cost_per_1k": 0.01,  # V8.4 T3 成本感知
        "base_url": "https://api.openai.com/v1",
        "endpoint": "/chat/completions",
        "model": "gpt-4o-mini",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "OPENAI_API_KEY",
        "max_tokens_param": "max_tokens",
        "timeout_s": 30,
    },
    "claude": {
        "priority": 3,
        "cost_per_1k": 0.015,  # V8.4 T3 成本感知
        "base_url": "https://api.anthropic.com",
        "endpoint": "/v1/messages",
        "model": "claude-sonnet-4-20250514",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "env_key": "ANTHROPIC_API_KEY",
        "extra_headers": {
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        "max_tokens_param": "max_tokens",
        "timeout_s": 30,
    },
    "qwen": {
        "priority": 4,
        "cost_per_1k": 0.002,  # V8.4 T3 成本感知
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "endpoint": "/chat/completions",
        "model": "qwen-max",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "DASHSCOPE_API_KEY",
        "max_tokens_param": "max_tokens",
        "timeout_s": 30,
    },
    # 新增 Provider
    "ollama": {
        "priority": 5,
        "cost_per_1k": 0.0,  # V8.4 T3 成本感知
        "base_url": "http://localhost:11434/v1",  # 用户可配置
        "endpoint": "/chat/completions",
        "model": "llama3",  # 用户可配置（llama3/qwen2.5/mistral）
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",  # Ollama 接受任意 token
        "env_key": "OLLAMA_KEY",  # 不强制要求
        "max_tokens_param": "max_tokens",
        "timeout_s": 120,  # 本地模型可能慢
    },
    "azure_openai": {
        "priority": 6,
        "cost_per_1k": 0.01,  # V8.4 T3 成本感知
        "base_url": "${AZURE_OPENAI_ENDPOINT}/openai/deployments/${AZURE_DEPLOYMENT}",  # 环境变量替换
        "endpoint": "/chat/completions?api-version=2024-12-01-preview",
        "model": "gpt-4o",  # deployment 名
        "auth_header": "api-key",  # Azure 用 api-key 而非 Bearer
        "auth_prefix": "",
        "env_key": "AZURE_OPENAI_API_KEY",
        "max_tokens_param": "max_tokens",
        "timeout_s": 30,
        "is_azure": True,  # 特殊标记
    },
    "lm_studio": {
        "priority": 7,
        "cost_per_1k": 0.0,  # V8.4 T3 成本感知
        "base_url": "http://localhost:1234/v1",
        "endpoint": "/chat/completions",
        "model": "local-model",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",  # LM Studio 接受任意
        "env_key": "LM_STUDIO_KEY",
        "max_tokens_param": "max_tokens",
        "timeout_s": 120,
    },
    # 新增 Provider：国家超算中心（SCNet · Kimi/GLM/Qwen/DeepSeek 等国产 LLM）
    "scnet": {
        "priority": 8,
        "cost_per_1k": 0.003,  # V8.4 T3 成本感知
        "base_url": "https://api.scnet.cn/api/llm/v1",
        "endpoint": "/chat/completions",
        # SCNet 平台支持的模型示例（控制台为准）：DeepSeek-R1-Distill-Qwen-7B · Qwen3.8-Max · Qwen3.x 系列 · GLM-5.x 等
        "model": "Qwen3.8-Max",  # 默认使用 Qwen3.8 系列（性能/通用平衡）
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "env_key": "SCNET_API_KEY",  # 用户提供的 API key（base64 编码 `tenant-ts-epoch` 格式）
        "max_tokens_param": "max_tokens",
        "timeout_s": 60,
        "model_aliases": {
            # 兼容用户提到的 Kimi 2.6 命名
            "kimi_2_6": "Qwen3.8-Max",
            "kimi-latest": "Qwen3.8-Max",
            "kimi-k2": "Qwen3.8-Max",
            # SCNet 平台常见别名
            "ds-r1-distill": "DeepSeek-R1-Distill-Qwen-7B",
            "qwen3-max": "Qwen3.8-Max",
            "glm-5": "Qwen3.8-Max",
        },
        "platform": "SCNet 国家超算互联网平台",
        "openai_compatible": True,
    },
}


class LLMRouter:
    """4-provider LLM 路由 + 自动 fallback"""

    def __init__(self, mode: Optional[str] = None, custom_providers: Optional[List[str]] = None):
        """
        Args:
            mode: "real" / "mock" / "auto"（默认读 QCM_LLM_MODE env）
            custom_providers: 自定义 provider 顺序（默认按 priority 排序）
        """
        self.mode = mode or os.environ.get("QCM_LLM_MODE", "auto")
        # V8.4 T3：成本感知排序（QCM_LLM_MODE=free 时 cost=0 免费引擎优先）
        def _sort_key(kv):
            name, cfg = kv
            if self.mode == "free":
                return (cfg.get("cost_per_1k", 0.01) != 0, cfg.get("cost_per_1k", 0.01), cfg["priority"])
            return cfg["priority"]
        self.providers = sorted(
            PROVIDERS.items(),
            key=_sort_key
        )
        if custom_providers:
            self.providers = [
                (name, PROVIDERS[name]) for name in custom_providers
                if name in PROVIDERS
            ]
        self.stats = {
            "calls_total": 0,
            "calls_real": 0,
            "calls_mock": 0,
            "calls_failed": 0,
            "calls_cache_hit": 0,
            "by_provider": {name: {"calls": 0, "success": 0, "fail": 0}
                            for name in PROVIDERS},
        }
        # LLM Response Cache
        self.cache_enabled = os.environ.get("QCM_LLM_CACHE", "1") == "1"
        self.cache: Dict[str, Dict] = {}  # key → response

    def _local_engine_available(self) -> bool:
        """本地免费引擎可达性（ollama:11434 / lm_studio:1234）· V8.4 批次 A

        无 Key 时若本机部署了 ollama/lm_studio → 仍可走真实本地 AI（免费优先闭环）。
        """
        import socket
        for port in (11434, 1234):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    return True
            except OSError:
                continue
        return False

    def _persist_stats(self, provider: str, mode: str) -> None:
        """V8.6.2 P4：by_provider stats 落盘 usage_global（对账基准跨进程稳定）

        - namespace=llm · obj=<provider>:<mode>（与 qcm_reconcile 对账口径一致）
        - QCM_NO_REPORT 隔离由 record_usage 内部处理（CI/合成测试不污染观测）
        """
        try:
            from usage_global import record_usage
            record_usage("llm", f"{provider}:{mode}")
        except Exception:
            pass  # 落盘失败不影响 LLM 调用（观测环防御降级）

    def is_real_mode(self) -> bool:
        """是否走真实 API"""
        if self.mode == "mock":
            return False
        if self.mode == "real":
            return True
        # auto: 有 key 或本地免费引擎可达（V8.4 批次 A · 无 Key 也有真实本地 AI）
        has_key = any(
            os.environ.get(p["env_key"])
            for _, p in self.providers
        )
        return has_key or self._local_engine_available()

    def list_providers_with_keys(self) -> List[str]:
        """列出有 API key 的 provider"""
        return [name for name, p in self.providers if os.environ.get(p["env_key"])]

    # ============ : Cache helpers ============
    _cache_ttl_s = 7 * 24 * 3600  # 7 天

    def _make_cache_key(self, prompt: str, system: Optional[str],
                        temperature: float, max_tokens: int,
                        provider: str) -> str:
        """生成 cache key (MD5)"""
        import hashlib
        content = f"{prompt}|{system or ''}|{temperature}|{max_tokens}|{provider}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def cache_clear(self):
        """清空 cache"""
        self.cache.clear()
        self.stats["calls_cache_hit"] = 0

    def cache_size(self) -> int:
        """cache 大小"""
        return len(self.cache)

    def call(
        self,
        prompt: str,
        task: str = "general",
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        prefer_provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        调用 LLM（自动 fallback + cache）

        : LLM Response Cache
          - cache key = MD5(prompt + system + temperature + max_tokens + provider)
          - 命中：直接返回，无网络调用
          - TTL：默认 7 天（可配置 QCM_LLM_CACHE_TTL）

        Returns:
            {
                "text": "...",
                "provider": "deepseek" | "mock" | ...,
                "mode": "real" | "mock" | "cache",
                "duration_s": 0.001,
                "fallback_chain": [...],
                "cache_hit": True/False,
            }
        """
        self.stats["calls_total"] += 1
        start = time.time()

        # Cache 命中检查
        if self.cache_enabled:
            cache_key = self._make_cache_key(prompt, system, temperature, max_tokens, prefer_provider or "auto")
            if cache_key in self.cache:
                self.stats["calls_cache_hit"] += 1
                cached = self.cache[cache_key]
                # 检查 TTL
                if time.time() - cached["cached_at"] < self._cache_ttl_s:
                    self._persist_stats(cached["response"].get("provider", "cache"), "cache")
                    return {
                        **cached["response"],
                        "cache_hit": True,
                        "duration_s": time.time() - start,
                        "fallback_chain": [cached["response"]["provider"]],
                    }
                else:
                    # TTL 过期，删除
                    del self.cache[cache_key]

        # 优先 provider 顺序
        providers_to_try = self.providers[:]
        if prefer_provider:
            for i, (name, _) in enumerate(providers_to_try):
                if name == prefer_provider:
                    providers_to_try = [providers_to_try[i]] + providers_to_try[:i] + providers_to_try[i+1:]
                    break

        fallback_chain = [name for name, _ in providers_to_try]

        # 真实模式 + 至少 1 个 key（V8.4 T2：KeyManager 健康过滤 + 反馈驱动）
        km = None
        try:
            from key_manager import KeyManager
            km = KeyManager.instance()
        except Exception:
            km = None
        if self.is_real_mode():
            for name, cfg in providers_to_try:
                # 熔断/配额跳过（主动健康降级 · 非等失败）
                if km is not None and not km.is_usable(name):
                    continue
                api_key = os.environ.get(cfg["env_key"])
                is_free = cfg.get("cost_per_1k", 0.01) == 0  # V8.4 批次 A：免费引擎无需 key
                if not api_key and not is_free:
                    continue
                if not api_key:
                    api_key = "local"  # 免费引擎占位（ollama/lm_studio 接受任意 token）
                self.stats["by_provider"][name]["calls"] += 1
                try:
                    text = self._call_real(name, cfg, api_key, prompt, system, max_tokens, temperature)
                    if km is not None:
                        km.report_success(name)
                    self.stats["calls_real"] += 1
                    self.stats["by_provider"][name]["success"] += 1
                    result = {
                        "text": text,
                        "provider": name,
                        "mode": "real",
                        "duration_s": round(time.time() - start, 3),
                        "fallback_chain": fallback_chain,
                        "task": task,
                    }
                    # 保存到 cache
                    if self.cache_enabled:
                        cache_key = self._make_cache_key(prompt, system, temperature, max_tokens, prefer_provider or name)
                        self.cache[cache_key] = {
                            "response": {k: v for k, v in result.items() if k != "cache_hit"},
                            "cached_at": time.time(),
                        }
                    self._persist_stats(name, "real")
                    return result
                except Exception as e:
                    if km is not None:
                        km.report_failure(name)
                        # 429/额度响应 → 配额感知（V8.4 T4）
                        if "429" in str(e) or "quota" in str(e).lower() or "rate limit" in str(e).lower():
                            km.report_quota(name, used=1, limit=1)
                    self.stats["calls_failed"] += 1
                    self.stats["by_provider"][name]["fail"] += 1
                    # 继续 fallback
                    continue

        # mock fallback（所有 real 失败或无 key）
        self.stats["calls_mock"] += 1
        text = self._call_mock(prompt, task, system)
        self._persist_stats("mock", "mock")
        return {
            "text": text,
            "provider": "mock",
            "mode": "mock",
            "duration_s": round(time.time() - start, 3),
            "fallback_chain": fallback_chain,
            "task": task,
        }

    def _call_real(self, name: str, cfg: Dict, api_key: str,
                   prompt: str, system: Optional[str],
                   max_tokens: int, temperature: float) -> str:
        """真实 API 调用（urllib，无依赖）"""
        import urllib.request
        import urllib.error

        # 处理 Azure OpenAI 和 base_url 中的环境变量替换（须在 url 计算前赋值）
        base_url = cfg["base_url"]
        if "${" in base_url:
            import re
            base_url = re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), base_url)

        url = base_url + cfg["endpoint"]
        headers = {
            cfg["auth_header"]: cfg["auth_prefix"] + api_key,
            "Content-Type": "application/json",
            "User-Agent": "QCM-MCP/0.2",
        }
        if cfg.get("extra_headers"):
            headers.update(cfg["extra_headers"])

        # 构建 payload（claude 格式不同）
        if name == "claude":
            payload = {
                "model": cfg["model"],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                payload["system"] = system
        else:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            payload = {
                "model": cfg["model"],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=cfg["timeout_s"]) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"URL Error: {e.reason}")
        except Exception as e:
            raise RuntimeError(f"Request failed: {e}")

        # 解析响应
        if name == "claude":
            content = body.get("content", [])
            if content and isinstance(content, list):
                return content[0].get("text", "")
            return ""
        else:
            choices = body.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""

    def _call_mock(self, prompt: str, task: str, system: Optional[str]) -> str:
        """Mock LLM 响应（基于 prompt 关键词 + task 类型）"""
        # 模拟 LLM 输出（确定性 + 可观察）
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]

        if task == "research":
            # 提取 query 的核心关键词
            kw_match = re.findall(r"[\u4e00-\u9fff]{2,}", prompt)
            core_kw = kw_match[0] if kw_match else "问题"
            return f"""【Mock LLM · 研究输出 · hash={prompt_hash}】

针对「{core_kw}」的深度分析：

1. **主因识别**：
   - 表层原因：变异/失效/浪费等类型
   - 深层原因：系统链 + 治理层双归零

2. **工具落格**（按 action-orders.md §3 决策路由）：
   - 紧急（T1）→ L1 操作级 24h：SPC + 8D D1-D3
   - 重要（T2）→ L2 选型级 1-2 周：FMEA + 控制计划
   - 常规（T3）→ L3 执行级 2-3 周：DOE + 双归零
   - 例行（T4）→ L4 治理级 整季：体系审核 + 成熟度

3. **大师视角**：
   - 戴明：PDCA + 持续改进
   - 克劳士比：零缺陷 + 4 成熟度阶段
   - 朱兰：三步曲（质量策划/控制/改进）

4. **数据来源**：action-orders.md §1-§7 · cases.md §焊接/汽车
5. **协议版本**：QCM + v0.2

（Mock 模式 · 待真实 LLM API 启用后将自动切换）
"""
        elif task == "score":
            return f"[Mock score · hash={prompt_hash}] 综合评分：78.5 / tier 2 / gate=核心自动采集"
        elif task == "decide":
            return f"[Mock decide · hash={prompt_hash}] 决策：L2 / 工具 A01+B01+F01 / 大师 戴明+克劳士比"
        elif task == "audit":
            return f"[Mock audit · hash={prompt_hash}] 审计得分：92.5 / passed=true / warnings=0 / errors=0"
        else:
            return f"[Mock LLM · task={task} · hash={prompt_hash}] 通用响应（prompt={prompt[:100]}）"

    def get_stats(self) -> Dict[str, Any]:
        """获取路由统计"""
        return {
            **self.stats,
            "mode": self.mode,
            "providers_with_keys": self.list_providers_with_keys(),
            "is_real_mode": self.is_real_mode(),
            "cache": {
                "enabled": self.cache_enabled,
                "size": self.cache_size(),
                "hit_rate": round(self.stats["calls_cache_hit"] / max(self.stats["calls_total"], 1), 3),
            }
        }


import re  # 用于 mock 关键词提取

if __name__ == "__main__":
    # CLI 测试
    import sys
    router = LLMRouter()
    print(f"Mode: {router.mode}")
    print(f"Providers with keys: {router.list_providers_with_keys()}")
    print(f"Is real mode: {router.is_real_mode()}")
    print()
    prompt = sys.argv[1] if len(sys.argv) > 1 else "焊接虚焊客诉复发怎么破"
    result = router.call(prompt, task="research")
    print(json.dumps(result, ensure_ascii=False, indent=2))