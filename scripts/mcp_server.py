#!/usr/bin/env python3
"""mcp_server.py — QCM v8.0+ MCP 服务器（MVP）

协议层 SOLE 权威: action-orders.md（+）13 协议
设计参考: Infoseek v1.7.0+ MCP server（6+ 工具 · stdio/SSE · Bearer Token）

 范围（决策 1+2+3）：
  ✓ 6 工具一次性（全量 stub · 规则引擎 · 无 LLM 调用）
  ✓ stdio 传输（开发友好）
  ✓ Bearer Token 认证（基础）
  ✓ 多 Provider 配置框架（才真正调用）

工具:
  1. qcm_research        - 端到端 T-L 路由 → 4 形态输出
  2. qcm_score_source    - 5 维评分（主题30% + 可信40% + 时效20% + 完整10%）
  3. qcm_decide          - T-L 路由决策（T1-T4 → L1-L4）
  4. qcm_solve_problem   - 5 段式输出 + 双归零判据
  5. qcm_audit           - 字段校验 + 引用追溯 + 五维风险
  6. qcm_validate        - 4 形态 × 10 项 = 40 检查矩阵

启动:
  python scripts/qcm_mcp_server.py                              # stdio（默认）
  python scripts/qcm_mcp_server.py --transport sse --port 8080 # SSE（启用）
  python scripts/mcp_server.py --require-token --token <secret>

工具命名: mcp__plugin_qcm_search__<tool>
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
import hashlib
import secrets
import threading
import logging
from datetime import datetime
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import multiprocessing
import socket

# GraphQL 适配（graphql-core 可选）
try:
    from qcm_graphql import (build_schema, execute_graphql,
                             build_subscription_schema, publish_tool_event)
    GRAPHQL_AVAILABLE = True
except ImportError:
    GRAPHQL_AVAILABLE = False

# OpenTelemetry 追踪
try:
    from tracing import start_tool_span, tracing_enabled
    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# E1-03 出站 HTTP 连接池客户端（urllib3.PoolManager 复用）
try:
    from mcp_http_client import HTTPClient
    HTTP_CLIENT_AVAILABLE = True
except ImportError:
    HTTP_CLIENT_AVAILABLE = False

# E1-04 服务端 TLS/HTTPS（证书加载 + 热重载）
try:
    from mcp_tls import TLSConfig
    TLS_AVAILABLE = True
except ImportError:
    TLS_AVAILABLE = False
from typing import Any, Dict, List, Optional, Tuple

# Metrics + Rate Limit
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from metrics import metrics, record_request, record_llm_call, record_tool_call, record_error
    from ratelimit import rate_limiter as default_rate_limiter
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    record_request = record_llm_call = record_tool_call = record_error = lambda *a, **k: None
    default_rate_limiter = None

# Resources + Prompts + Sampling + Streaming + Protocol + WebSocket
try:
    from resources import ResourceHandler
    from prompts import list_prompts as qcm_list_prompts, get_prompt as qcm_get_prompt
    RESOURCES_AVAILABLE = True
except ImportError:
    RESOURCES_AVAILABLE = False
    ResourceHandler = None
    qcm_list_prompts = qcm_get_prompt = lambda *a, **k: []

# OAuth 2.0 + RBAC + Secret 加密
try:
    from auth import AuthManager, SecretCipher
    AUTH_MANAGER = AuthManager()
    SECRET_CIPHER = SecretCipher()
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    AUTH_MANAGER = None
    SECRET_CIPHER = SecretCipher()  # XOR fallback


def handle_websocket(ws):
    """ WebSocket 处理器（JSON-RPC over WS）"""
    import json as _json
    for message in ws:
        try:
            request = _json.loads(message)
            response = _process_jsonrpc_static(request)
            ws.send(_json.dumps(response, ensure_ascii=False))
        except Exception as e:
            ws.send(_json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}))


def _process_jsonrpc_static(request: dict) -> dict:
    """JSON-RPC 静态处理（用于 WebSocket transport）"""
    # 直接复用 HTTP 路径的核心逻辑
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})
    start = time.time()

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "qcm-mcp-server", "version": SERVER_VERSION, "protocol": PROTOCOL_VERSION},
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
        }}
    elif method == "tools/list":
        tools_list = [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]} for t in TOOL_REGISTRY.values()]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name not in TOOL_REGISTRY:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}}
        try:
            # 发布工具调用事件（GraphQL subscription）
            if GRAPHQL_AVAILABLE:
                try:
                    publish_tool_event({
                        "tool": tool_name,
                        "arguments": arguments,
                        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    })
                except Exception:
                    pass
            result = _gateway_invoke(tool_name, arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            }}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

# ============ 版本常量（必须在 initialize 响应前定义） ============
PROTOCOL_VERSION = "V8.0+"
SERVER_VERSION = "1.0.1"

# LLM Router 初始化已移至 tools_pack.py（P2-9 拆分）
from tools_pack import LLM_ROUTER, LLM_AVAILABLE

# ============ 配置 ============
from paths import ROOT as QCM_ROOT
from paths import PLUGINS as PLUGINS_DIR
REFERENCES = os.path.join(QCM_ROOT, "references")
OUTPUTS = os.path.join(QCM_ROOT, "outputs")

# 多 Provider 配置框架（启用）
LLM_PROVIDERS = {
    "deepseek":  {"priority": 1, "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "openai":    {"priority": 2, "base_url": "https://api.openai.com/v1",  "model": "gpt-4o"},
    "claude":    {"priority": 3, "base_url": "https://api.anthropic.com",     "model": "claude-sonnet-4-20250514"},
    "qwen":      {"priority": 4, "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max"},
}

# ============ Corpus 加载（已移至 tools_pack.py · P2-9 拆分）============
from tools_pack import load_corpus

# ============ 工具实现（规则引擎 · 无 LLM）============
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

# V8.6 P2 · R10/R11 蓝图落地：TOOL_REGISTRY 网关兜底采样（链 B 归一点兜底）
# 语义：wrapped handler 已带 _x_qcm_sampled 标记（本地直调场景已采样）→ 网关跳过；
#       未带标记（wrap=False 注册 / 历史调用路径）→ 网关兜底采样（双计治理关键）。
def _gateway_record(tool_name: str, result: Any) -> None:
    try:
        if isinstance(result, dict) and result.get("_x_qcm_sampled"):
            return  # 织入层已采样 → 防双计
        from usage_global import record_usage
        record_usage("tool", tool_name)
    except Exception:
        pass


def _gateway_invoke(tool_name: str, arguments: Dict) -> Any:
    """统一网关调用 + 兜底采样（四条协议路径共用）"""
    handler = TOOL_REGISTRY[tool_name]["handler"]
    result = handler(**arguments)
    _gateway_record(tool_name, result)
    return result

def register_tool(name: str, description: str, input_schema: Dict[str, Any]):
    """注册 MCP 工具"""
    def decorator(func):
        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": func,
        }
        return func
    return decorator

# ---------- Tool 1: qcm_research ----------
# ============ 工具实现（已拆至 tools_pack.py · P2-9 单一职责）============
from tools_pack import TOOL_DEFS as _TOOL_DEFS, register_all as _register_all
_register_all(TOOL_REGISTRY)

class QCMCrypto:
    """简单 Token 验证（基础版 · 升级 OAuth）"""
    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def verify(provided: str, expected: str) -> bool:
        return secrets.compare_digest(provided, expected)


async def handle_stdio():
    """stdio JSON-RPC 处理器（MCP 协议）"""
    expected_token = os.environ.get("QCM_AUTH_TOKEN")
    require_token = os.environ.get("QCM_REQUIRE_TOKEN", "0") == "1"

    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            method = request.get("method")
            req_id = request.get("id")
            params = request.get("params", {})  # V8.3.2 T2：函数级初始化，修复 resources/read 等分支作用域 Bug

            # 认证（仅对 tools/call）
            if require_token and method == "tools/call":
                auth = request.get("params", {}).get("__token__", "")
                if not expected_token or not QCMCrypto.verify(auth, expected_token):
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32001, "message": "Unauthorized"},
                    }
                    print(json.dumps(response, ensure_ascii=False), flush=True)
                    continue

            # 路由
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": "qcm-mcp-server",
                            "version": SERVER_VERSION,
                            "protocol": PROTOCOL_VERSION,
                        },
                        "capabilities": {"tools": {"listChanged": False}},
                    },
                }
            elif method == "tools/list":
                tools_list = [
                    {
                        "name": t["name"],
                        "description": t["description"],
                        "inputSchema": t["inputSchema"],
                    }
                    for t in TOOL_REGISTRY.values()
                ]
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": tools_list},
                }
            elif method == "resources/list":
                if not RESOURCES_AVAILABLE:
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32601, "message": "Resources not available"}}
                else:
                    handler = ResourceHandler(load_corpus())
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "result": {"resources": handler.list_resources()}}
            elif method == "resources/read":
                if not RESOURCES_AVAILABLE:
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32601, "message": "Resources not available"}}
                else:
                    handler = ResourceHandler(load_corpus())
                    uri = params.get("uri", "")
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "result": handler.read_resource(uri)}
            elif method == "prompts/list":
                response = {"jsonrpc": "2.0", "id": req_id,
                            "result": {"prompts": qcm_list_prompts()}}
            elif method == "prompts/get":
                pname = params.get("name", "")
                pargs = params.get("arguments", {})
                try:
                    result = qcm_get_prompt(pname, pargs)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": result}
                except Exception as e:
                    from prompts import PromptNotFoundError
                    if isinstance(e, PromptNotFoundError):
                        response = {"jsonrpc": "2.0", "id": req_id,
                                    "error": {"code": -32602, "message": str(e)}}
                    else:
                        response = {"jsonrpc": "2.0", "id": req_id,
                                    "error": {"code": -32603, "message": f"prompt error: {e}"}}
            elif method == "sampling/createMessage":
                # 服务端反向调用 LLM（用现有 LLM Router）
                msgs = params.get("messages", [])
                max_tokens = params.get("maxTokens", 1024)
                prompt_text = "\n".join([m.get("content", {}).get("text", "") if isinstance(m.get("content"), dict) else str(m.get("content", "")) for m in msgs])
                if LLM_AVAILABLE and LLM_ROUTER:
                    llm_result = LLM_ROUTER.call(prompt_text, task="general", max_tokens=max_tokens)
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "result": {
                                    "role": "assistant",
                                    "content": {"type": "text", "text": llm_result["text"]},
                                    "model": llm_result["provider"],
                                    "stopReason": "endTurn",
                                }}
                else:
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32002, "message": "LLM not available"}}
            elif method == "tools/call":
                params = request.get("params", {})
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if tool_name not in TOOL_REGISTRY:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
                    }
                else:
                    try:
                        handler = TOOL_REGISTRY[tool_name]["handler"]
                        # 发布工具调用事件（WS 旁路推送 · stdio 主传输）
                        if GRAPHQL_AVAILABLE:
                            try:
                                publish_tool_event({
                                    "tool": tool_name,
                                    "arguments": arguments,
                                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                })
                            except Exception:
                                pass
                        result = _gateway_invoke(tool_name, arguments)
                        response = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                                ],
                            },
                        }
                    except Exception as e:
                        response = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32603, "message": f"Tool execution error: {e}"},
                        }
            elif method == "ping":
                response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            print(json.dumps(response, ensure_ascii=False), flush=True)
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            print(json.dumps(error_response, ensure_ascii=False), flush=True)
        except Exception as e:
            try:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id") if 'request' in locals() else None,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                }
                print(json.dumps(error_response, ensure_ascii=False), flush=True)
            except Exception:
                pass


def _start_corpus_watcher(references_dir: str, interval_s: float):
    """: 启动 corpus hot reload"""
    try:
        from corpus_cache import CorpusCache, CorpusWatcher
        cache = CorpusCache(references_dir)
        if not cache.is_built():
            cache.build()
        watcher = CorpusWatcher(cache, references_dir, interval_s)
        watcher.start()
        print(f"[corpus] CorpusWatcher 启动（间隔 {interval_s}s）", file=sys.stderr)
    except Exception as e:
        print(f"[corpus] CorpusWatcher 启动失败: {e}", file=sys.stderr)


# ============ : WS 旁路推送（双通道共存）============
def _build_ws_push_schema():
    """构建 WS 旁路推送 schema（轻量 · 仅 toolCalled subscription）"""
    from ws_push import build_push_schema
    return build_push_schema()


async def _run_stdio_with_ws_push(args):
    """: stdio 主传输 + WS 旁路推送（同 event loop 并行）

    - 主协程：handle_stdio()（JSON-RPC 协议 · stdout）
    - 旁路协程：run_ws_push_server_async()（graphql-ws 订阅 · 事件推送）
    - 日志全部走 stderr，不污染 stdout 协议流
    """
    from ws_push import run_ws_push_server_async
    push_task = asyncio.create_task(
        run_ws_push_server_async(
            _build_ws_push_schema(),
            port=args.ws_push_port,
            host=args.host,
            require_token=args.require_token,
            fixed_token=args.token,
        )
    )
    try:
        await handle_stdio()
    finally:
        push_task.cancel()


def _start_ws_push_thread(args):
    """: http 模式并行启动 WS 旁路（daemon thread）

    事件总线已做跨线程安全（qcm_graphql.publish_tool_event 用
    call_soon_threadsafe），http handler 线程可安全发布事件到旁路订阅者。
    旁路启动失败（如端口冲突）仅告警，不阻塞主传输。
    """
    try:
        from ws_push import start_ws_push_thread
        _t, ready = start_ws_push_thread(
            _build_ws_push_schema(),
            port=args.ws_push_port,
            host=args.host,
            require_token=args.require_token,
            fixed_token=args.token,
            ready_timeout=3.0,
        )
        if not ready.is_set():
            print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ WS 旁路推送未就绪"
                  f"（端口 {args.ws_push_port} 可能被占用，仅主传输可用）",
                  file=sys.stderr)
    except Exception as e:
        print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ WS 旁路推送启动失败: {e}"
              f"（仅主传输可用）", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=f"QCM MCP Server v{SERVER_VERSION}")
    parser.add_argument("--transport", choices=["stdio", "http", "ws"], default="stdio",
                        help="传输协议（stdio=本地 · http=SSE/HTTP · ws=WebSocket）")
    parser.add_argument("--watch-corpus", action="store_true",
                        help="V8.3.0: 启用 corpus hot reload（每 5 秒检测文件变化）")
    parser.add_argument("--watch-interval", type=float, default=5.0,
                        help="V0.8: 文件检测间隔（秒）")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 绑定地址")
    parser.add_argument("--workers", type=int, default=1, help="V0.8.1: HTTP worker 进程数（>1 多进程）")
    parser.add_argument("--port", type=int, default=8080, help="HTTP 端口")
    parser.add_argument("--require-token", action="store_true", help="启用 Bearer Token 认证")
    parser.add_argument("--token", help="认证 Token")
    parser.add_argument("--ws-push-port", type=int, default=8765,
                        help="WS 旁路事件推送端口（stdio/http 模式并行启动，默认 8765）")
    parser.add_argument("--disable-ws-push", action="store_true",
                        help="禁用 WS 旁路推送（仅主传输）")
    parser.add_argument("--upstream-url", default=None,
                        help="E1-03: 上游就绪探针 URL（/health/ready 将探测此地址，如 http://127.0.0.1:8080/health）")
    parser.add_argument("--tls-cert", default=None, help="E1-04: TLS 证书路径（PEM），启用 HTTPS")
    parser.add_argument("--tls-key", default=None, help="E1-04: TLS 私钥路径（PEM），启用 HTTPS")
    parser.add_argument("--tls-watch", action="store_true",
                        help="E1-04: 监听证书文件变更并热重载（配合 certbot 续期，无需重启）")
    args = parser.parse_args()

    # E1-03 连接池 + 上游就绪探针激活
    global UPSTREAM_URL, UPSTREAM_CLIENT, TLS_CTX
    if args.upstream_url and HTTP_CLIENT_AVAILABLE:
        UPSTREAM_URL = args.upstream_url
        UPSTREAM_CLIENT = HTTPClient()
    elif args.upstream_url and not HTTP_CLIENT_AVAILABLE:
        print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ --upstream-url 已设但连接池客户端不可用（mcp_http_client 缺失），跳过上游探针", file=sys.stderr)

    # E1-04 服务端 TLS 激活
    if args.tls_cert and args.tls_key and TLS_AVAILABLE:
        try:
            TLS_CTX = TLSConfig(args.tls_cert, args.tls_key, watch=args.tls_watch)
            print(f"[qcm-mcp v{SERVER_VERSION}] ✅ TLS 已启用（cert={args.tls_cert} · watch={args.tls_watch}）", file=sys.stderr)
        except Exception as e:
            TLS_CTX = None
            print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ TLS 启用失败（回退 HTTP）：{e}", file=sys.stderr)
    elif args.tls_cert or args.tls_key:
        if not TLS_AVAILABLE:
            print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ TLS 模块不可用（mcp_tls 缺失），跳过 HTTPS", file=sys.stderr)
        else:
            print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ 需同时提供 --tls-cert 与 --tls-key，跳过 HTTPS", file=sys.stderr)

    # T-P2: 插件挂载（plugins/ 目录 → PluginLoader.load_all → TOOL_REGISTRY）
    try:
        from plugin import PluginLoader
        _plugin_dir = os.environ.get("QCM_PLUGINS_DIR", str(PLUGINS_DIR))
        if os.path.isdir(_plugin_dir):
            _loader = PluginLoader(_plugin_dir)
            _loaded = _loader.load_all()
            if _loaded:
                print(f"[qcm-mcp v{SERVER_VERSION}] ✅ 插件挂载: {len(_loaded)} 工具 ({', '.join(_loaded)})", file=sys.stderr)
        else:
            print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ plugins 目录不存在（{_plugin_dir}），跳过插件加载", file=sys.stderr)
    except Exception as e:
        print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ 插件加载失败（不阻塞启动）: {e}", file=sys.stderr)

    if args.require_token and args.token:
        os.environ["QCM_AUTH_TOKEN"] = args.token
        os.environ["QCM_REQUIRE_TOKEN"] = "1"

    if args.transport == "stdio":
        if args.watch_corpus:
            _start_corpus_watcher(REFERENCES, args.watch_interval)
        if args.disable_ws_push:
            asyncio.run(handle_stdio())
        else:
            # stdio 主传输 + WS 旁路推送（同 event loop 并行 · 双通道共存）
            asyncio.run(_run_stdio_with_ws_push(args))
    elif args.transport == "http":
        if args.watch_corpus:
            _start_corpus_watcher(REFERENCES, args.watch_interval)
        if not args.disable_ws_push:
            _start_ws_push_thread(args)
        run_multi_process(host=args.host, port=args.port, workers=args.workers)
    elif args.transport == "ws":
        # WebSocket 双协议（graphql-ws subscription + JSON-RPC）
        try:
            from ws import run_graphql_ws_server
            from qcm_graphql import build_subscription_schema
            from graphql import GraphQLSchema
            schema = get_graphql_schema()
            if schema is not None and schema.subscription_type is None:
                base = build_schema(_gql_tools_provider, _gql_call_provider,
                                    _gql_health_provider, _gql_stats_provider)
                schema = GraphQLSchema(query=base.query_type, mutation=base.mutation_type,
                                       subscription=build_subscription_schema())
            run_graphql_ws_server(
                schema, port=args.port, host=args.host,
                require_token=args.require_token, fixed_token=args.token,
                jsonrpc_handler=_process_jsonrpc_static,
                server_name=f"qcm-mcp v{SERVER_VERSION}",
            )
        except ImportError as e:
            print(f"WebSocket transport 依赖缺失: {e}", file=sys.stderr)
            print("  pip install websockets graphql-core", file=sys.stderr)
            sys.exit(1)




# ============ HTTP/SSE 传输 ============
class AuditLogger:
    """审计日志（JSON Lines · 按日轮转）"""

    def __init__(self, log_dir: str = None):
        # 支持 QCM_AUDIT_DIR 环境变量
        self.log_dir = log_dir or os.environ.get("QCM_AUDIT_DIR", "/tmp/qcm-mcp-audit")
        os.makedirs(self.log_dir, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, method: str, params_summary: str, status: str,
            duration_s: float, provider: str = "-"):
        """写入一条审计记录"""
        with self._lock:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            log_file = os.path.join(self.log_dir, f"audit-{today}.log")
            entry = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "method": method,
                "params_summary": params_summary[:200],
                "status": status,
                "duration_s": round(duration_s, 3),
                "provider": provider,
            }
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass  # 审计失败不阻塞主流程


AUDIT = AuditLogger()  # 全局实例


class AccessLogLogger:
    """HTTP 访问日志（JSON Lines · 按日轮转）— E1-01

    与工具级 AUDIT 区分：本类记录 HTTP 传输层（method/path/status/bytes/duration/
    client_ip/ua），服务于排障与可观测性；AUDIT 记录工具调用级语义（method/params/
    provider）。两者独立，互不替代。
    """

    def __init__(self, log_dir: str = None):
        # 支持 QCM_ACCESS_LOG_DIR 环境变量（独立于 AUDIT 的 QCM_AUDIT_DIR）
        self.log_dir = log_dir or os.environ.get("QCM_ACCESS_LOG_DIR", "/tmp/qcm-mcp-access")
        os.makedirs(self.log_dir, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, method: str, path: str, status: int, bytes_sent: int,
            duration_s: float, client_ip: str, user_agent: str):
        """写入一条结构化 HTTP 访问记录"""
        with self._lock:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            log_file = os.path.join(self.log_dir, f"access-{today}.log")
            entry = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "method": method or "-",
                "path": path or "-",
                "status": int(status),
                "bytes_sent": int(bytes_sent),
                "duration_s": round(duration_s, 6),
                "client_ip": client_ip or "unknown",
                "user_agent": user_agent or "-",
            }
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass  # 访问日志失败不阻塞主流程


ACCESS = AccessLogLogger()  # 全局实例（HTTP 访问日志）


# ============ E1-05 OpenAPI 3.1 动态生成路由注册表 ============
# 单一真源：本表驱动 /openapi.json 的动态生成（非静态托管文件）。
# 新增端点时在此登记，文档即自动同步，避免文档与实现漂移。
MCP_ROUTE_SPEC = {
    "/health":       {"get": {"summary": "服务总览健康检查（overview）", "tags": ["health"]}},
    "/health/live": {"get": {"summary": "存活探针 (K8s liveness)", "tags": ["health"]}},
    "/health/ready": {"get": {"summary": "就绪探针 (K8s readiness)", "tags": ["health"]}},
    "/sse":          {"get": {"summary": "Server-Sent Events 实时推送流", "tags": ["realtime"]}},
    "/metrics":      {"get": {"summary": "Prometheus 指标端点", "tags": ["observability"]}},
    "/stats":        {"get": {"summary": "运行态统计端点", "tags": ["observability"]}},
    "/openapi.json": {"get": {"summary": "本 OpenAPI 文档（由代码动态生成）", "tags": ["meta"]}},
    "/oauth/token":  {"post": {"summary": "OAuth2 令牌签发（无需 Bearer Token）", "tags": ["auth"]}},
    "/graphql":      {"post": {"summary": "GraphQL 查询端点（Bearer Token）", "tags": ["protocol"]}},
    "/messages":     {"post": {"summary": "JSON-RPC 消息端点（Bearer Token + 限流）", "tags": ["protocol"]}},
    "/rpc":          {"post": {"summary": "JSON-RPC 端点别名（Bearer Token + 限流）", "tags": ["protocol"]}},
}


# E1-03 连接池 + 上游就绪探针（由 --upstream-url 激活；None 表示不探测）
UPSTREAM_URL = None
UPSTREAM_CLIENT = None

# E1-04 服务端 TLS/HTTPS（由 --tls-cert/--tls-key 激活；None 表示不启用）
TLS_CTX = None


class QCMHTTPHandler(BaseHTTPRequestHandler):
    """QCM MCP HTTP/SSE 端点处理器"""

    # 禁用默认 stderr access log（改用结构化 JSONL 访问日志 ACCESS）
    def log_message(self, format, *args):
        pass

    def handle_one_request(self):
        """每个请求开始计时并重置响应字节计数（E1-01 访问日志前置）"""
        self._req_start = time.monotonic()
        self._resp_bytes = 0
        super().handle_one_request()

    def send_header(self, keyword, value):
        """捕获响应 Content-Length 供访问日志统计字节数（E1-01）"""
        if keyword.lower() == "content-length":
            try:
                self._resp_bytes = int(value)
            except (TypeError, ValueError):
                pass
        super().send_header(keyword, value)

    def log_request(self, code='-', size='-'):
        """结构化 HTTP 访问日志（E1-01 · JSON Lines）

        BaseHTTPRequestHandler.send_response() 在发送响应前调用本方法并传入状态码；
        method/path 取自 self.command/self.path，耗时取自本请求起始时间，
        bytes 取自响应 Content-Length（send_header 捕获）。
        """
        try:
            if isinstance(code, HTTPStatus):
                code = code.value
            status = int(code) if str(code).strip("-").isdigit() else 500
        except (TypeError, ValueError):
            status = 500
        duration_s = round(time.monotonic() - getattr(self, "_req_start", time.monotonic()), 6)
        client_ip = self.client_address[0] if self.client_address else "unknown"
        user_agent = self.headers.get("User-Agent", "-") if self.headers else "-"
        ACCESS.log(
            method=self.command or "-",
            path=self.path or "-",
            status=status,
            bytes_sent=getattr(self, "_resp_bytes", 0),
            duration_s=duration_s,
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        """Bearer Token 认证（支持 JWT/OAuth token）"""
        require_token = os.environ.get("QCM_REQUIRE_TOKEN", "0") == "1"
        if not require_token:
            return True
        expected = os.environ.get("QCM_AUTH_TOKEN", "")
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            provided = auth_header[7:]
        else:
            provided = self.headers.get("X-QCM-Token", "")

        # 尝试 OAuth JWT 验证
        if AUTH_AVAILABLE and AUTH_MANAGER and provided.startswith("qcm."):
            payload = AUTH_MANAGER.verify(provided)
            if payload:
                self._qcm_token = provided
                self._qcm_payload = payload
                return True
            return False

        # /: 兼容简单 Bearer Token
        self._qcm_token = provided
        return bool(expected) and QCMCrypto.verify(provided, expected)

    def _do_health(self, kind: str):
        """/health · /health/live · /health/ready"""
        if kind == "live":
            # 进程存活
            self._send_json(200, {
                "status": "alive",
                "version": SERVER_VERSION,
                "protocol": PROTOCOL_VERSION,
                "uptime_s": int(time.time() - SERVER_START_TIME),
            })
            return
        if kind == "ready":
            # 就绪检查：corpus 加载 + provider 状态
            try:
                corpus = load_corpus()
                corpus_ok = len(corpus) >= 10
            except Exception:
                corpus_ok = False

            providers_info = {}
            if LLM_AVAILABLE and LLM_ROUTER:
                providers_info = {
                    "mode": LLM_ROUTER.mode,
                    "is_real_mode": LLM_ROUTER.is_real_mode(),
                    "providers_with_keys": LLM_ROUTER.list_providers_with_keys(),
                }

            # E1-03 上游就绪探针（--upstream-url 激活）：探测上游可达性并纳入就绪判定
            upstream_info = None
            if UPSTREAM_URL and UPSTREAM_CLIENT is not None:
                try:
                    _u = UPSTREAM_CLIENT.get(UPSTREAM_URL, timeout=2.0)
                    _u_status = getattr(_u, "status", None)
                    upstream_ok = _u_status == 200
                except Exception as _e:
                    _u_status = f"error: {_e}"
                    upstream_ok = False
                upstream_info = {"url": UPSTREAM_URL, "ok": upstream_ok, "status": _u_status}

            ok = corpus_ok and (LLM_AVAILABLE or True) and (upstream_info is None or upstream_info["ok"])
            ready_payload = {
                "status": "ready" if ok else "degraded",
                "corpus_files": len(corpus) if corpus_ok else 0,
                "corpus_ok": corpus_ok,
                "llm": providers_info,
                "upstream": upstream_info,
            }
            # 增强：添加 rate limiter + metrics 状态
            if METRICS_AVAILABLE and default_rate_limiter:
                ready_payload["rate_limiter"] = default_rate_limiter.get_stats()
                ready_payload["metrics"] = {
                    "requests_total": sum(v for k, v in metrics._counters.items() if k[0] == "qcm_requests_total"),
                    "errors_total": sum(v for k, v in metrics._counters.items() if k[0] == "qcm_errors_total"),
                }
            self._send_json(200 if ok else 503, ready_payload)
            return
        # /health 概览
        self._send_json(200, {
            "status": "ok",
            "version": SERVER_VERSION,
            "tools_count": len(TOOL_REGISTRY),
            "transports": ["stdio", "sse", "http"],
        })

    def _build_openapi(self) -> dict:
        """根据 MCP_ROUTE_SPEC 动态生成 OpenAPI 3.1 文档（E1-05 · 非静态文件）"""
        paths = {}
        for route, methods in MCP_ROUTE_SPEC.items():
            item = {}
            for method, meta in methods.items():
                item[method] = {
                    "summary": meta.get("summary", ""),
                    "tags": meta.get("tags", []),
                    "responses": {
                        "200": {"description": "OK"},
                        "401": {"description": "Unauthorized — Bearer Token 缺失或无效"},
                        "429": {"description": "Rate limit exceeded"},
                    },
                }
            paths[route] = item
        host, port = ("127.0.0.1", 8080)
        try:
            host, port = self.server.server_address[0], self.server.server_address[1]
        except Exception:
            pass
        return {
            "openapi": "3.1.0",
            "info": {
                "title": "QCM MCP Server",
                "version": SERVER_VERSION,
                "description": "Quality Control Manual (QCM) MCP Server — HTTP/SSE 传输层 API。"
                               "本文档由代码内 MCP_ROUTE_SPEC 动态生成，非静态托管文件。",
            },
            "servers": [{"url": f"http://{host}:{port}", "description": "当前运行实例"}],
            "paths": paths,
        }

    def _handle_openapi(self):
        """GET /openapi.json — 返回动态生成的 OpenAPI 3.1 文档（E1-05）"""
        self._send_json(200, self._build_openapi())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # OpenAPI 3.1 动态文档（E1-05 · 由 MCP_ROUTE_SPEC 生成）
        if path == "/openapi.json":
            self._handle_openapi()
        # 健康检查
        elif path == "/health":
            self._do_health("overview")
        elif path == "/health/live" or path == "/healthz":
            self._do_health("live")
        elif path == "/health/ready" or path == "/readyz":  # V8.3.2 T2：修复 /healtlth 拼写（K8s 就绪探针 404 根因）
            self._do_health("ready")
        elif path == "/sse":
            self._handle_sse()
        elif path == "/metrics" and METRICS_AVAILABLE:
            self._handle_metrics()
        elif path == "/stats" and METRICS_AVAILABLE:
            self._handle_stats()
        else:
            self._send_json(404, {"error": "not found", "path": path})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # OAuth token endpoint（无需 Bearer Token）
        if path == "/oauth/token":
            self._handle_oauth_token()
            return

        # 认证
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized"})
            return

        # GraphQL 端点
        if path == "/graphql":
            self._handle_graphql()
            return

        if path == "/messages" or path == "/rpc":
            # Rate limiting 检查
            if METRICS_AVAILABLE and default_rate_limiter:
                client_ip = self.client_address[0] if self.client_address else "unknown"
                # 从 Authorization header 提取 token
                auth_header = self.headers.get("Authorization", "")
                token = auth_header[7:] if auth_header.startswith("Bearer ") else self.headers.get("X-QCM-Token", "")
                ok, retry_after = default_rate_limiter.check(client_ip=client_ip, token=token)
                if not ok:
                    record_error("rate_limit")
                    self.send_response(429)
                    self.send_header("Retry-After", str(int(retry_after) + 1))
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    body = json.dumps({"error": "rate limit exceeded", "retry_after_s": retry_after}).encode("utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            self._handle_jsonrpc()
        else:
            self._send_json(404, {"error": "not found", "path": path})

    def _handle_graphql(self):
        """: GraphQL 查询执行（POST /graphql）"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Empty body"})
            return
        try:
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        if not GRAPHQL_AVAILABLE:
            self._send_json(503, {"error": "GraphQL 不可用（需 pip install graphql-core）"})
            return

        schema = get_graphql_schema()
        if schema is None:
            self._send_json(503, {"error": "GraphQL schema 构建失败"})
            return

        query = body.get("query", "")
        variables = body.get("variables") or {}
        result = execute_graphql(schema, query, variables)
        body_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def _handle_jsonrpc(self):
        """POST /messages 或 /rpc · JSON-RPC 2.0"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "empty body"})
            return
        raw = self.rfile.read(content_length).decode("utf-8")

        try:
            request = json.loads(raw)
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return

        response = self._process_jsonrpc(request)
        self._send_json(200, response)

    def _handle_sse(self):
        """GET /sse · Server-Sent Events 流式响应

        客户端 GET /sse 一次，仅获取 SSE 通道
        实际请求通过 POST /messages 发送，结果通过 SSE 推送
        """
        # 认证
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        # 推送初始化事件
        init_event = {
            "jsonrpc": "2.0",
            "method": "sse/connected",
            "params": {
                "server": "qcm-mcp-server",
                "version": SERVER_VERSION,
                "tools_count": len(TOOL_REGISTRY),
            }
        }
        self.wfile.write(f"data: {json.dumps(init_event, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

        # 保持连接（每 30s 发心跳）
        try:
            while True:
                time.sleep(30)
                heartbeat = {"jsonrpc": "2.0", "method": "sse/heartbeat", "ts": time.time()}
                self.wfile.write(f": heartbeat\ndata: {json.dumps(heartbeat)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_oauth_token(self):
        """POST /oauth/token · OAuth 2.0 client_credentials"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "empty body"})
            return
        raw = self.rfile.read(content_length).decode("utf-8")
        # 支持 JSON 或 form-urlencoded
        try:
            if "application/json" in self.headers.get("Content-Type", ""):
                params = json.loads(raw)
            else:
                params = {k: v[0] if isinstance(v, list) else v for k, v in parse_qs(raw).items()}
        except Exception as e:
            self._send_json(400, {"error": f"invalid body: {e}"})
            return

        grant_type = params.get("grant_type", "client_credentials")
        if grant_type != "client_credentials":
            self._send_json(400, {"error": "unsupported_grant_type", "supported": ["client_credentials"]})
            return

        client_id = params.get("client_id", "")
        client_secret = params.get("client_secret", "")
        scope = params.get("scope", "").split() if params.get("scope") else None
        tenant = params.get("tenant", "default")

        if AUTH_AVAILABLE and AUTH_MANAGER:
            result = AUTH_MANAGER.client_credentials(client_id, client_secret, scope, tenant)
        else:
            # Fallback：直接比对（兼容 Bearer Token）
            expected = os.environ.get("QCM_AUTH_TOKEN", "")
            if client_id == "default-client" and client_secret == expected:
                result = {
                    "access_token": expected,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "tools/call tools/list",
                }
            else:
                result = {"error": "invalid_client"}

        if "error" in result:
            self._send_json(401, result)
        else:
            self._send_json(200, result)

    def _check_rbac(self, tool_name: str) -> bool:
        """ RBAC 检查"""
        if not AUTH_AVAILABLE or AUTH_MANAGER is None:
            return True  # 无 AuthManager 时放行
        # 从 auth state 读取（由 _check_auth 写入）
        token = getattr(self, "_qcm_token", None)
        if not token:
            return True  # 兼容 
        if not token.startswith("qcm."):
            return True  # : 静态 token（兼容）无 RBAC 维度，放行
        payload = AUTH_MANAGER.verify(token)
        return AUTH_MANAGER.check_tool(payload, tool_name)

    def _handle_metrics(self):
        """GET /metrics · Prometheus 文本格式（V8.4：含词源健康指标）"""
        try:
            from metrics import record_keyword_health
            record_keyword_health()  # 采集词源健康（qcm_keyword_* · §11.5）
        except Exception:
            pass  # 词指标采集失败不影响 /metrics
        body = metrics.export().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_stats(self):
        """GET /stats · JSON 摘要"""
        stats = metrics.get_summary()
        # 加上 rate limiter 状态
        if default_rate_limiter:
            stats["rate_limiter"] = default_rate_limiter.get_stats()
        self._send_json(200, stats)

    def _process_jsonrpc(self, request: dict) -> dict:
        """处理 JSON-RPC 请求 · 返回响应 dict"""
        start = time.time()
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})
        provider = "-"

        try:
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": "qcm-mcp-server",
                            "version": SERVER_VERSION,
                            "protocol": PROTOCOL_VERSION,
                            "vendor": "qcm",
                        },
                        "capabilities": {
                            "tools": {"listChanged": False},
                            "resources": {"subscribe": False, "listChanged": False},
                            "prompts": {"listChanged": False},
                            "logging": {},
                        },
                    },
                }
            elif method == "tools/list":
                tools_list = [
                    {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
                    for t in TOOL_REGISTRY.values()
                ]
                response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}
            elif method == "resources/list":
                if not RESOURCES_AVAILABLE:
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32601, "message": "Resources not available"}}
                else:
                    handler = ResourceHandler(load_corpus())
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "result": {"resources": handler.list_resources()}}
            elif method == "resources/read":
                if not RESOURCES_AVAILABLE:
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32601, "message": "Resources not available"}}
                else:
                    handler = ResourceHandler(load_corpus())
                    uri = params.get("uri", "")
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "result": handler.read_resource(uri)}
            elif method == "prompts/list":
                response = {"jsonrpc": "2.0", "id": req_id,
                            "result": {"prompts": qcm_list_prompts()}}
            elif method == "prompts/get":
                pname = params.get("name", "")
                pargs = params.get("arguments", {})
                try:
                    result = qcm_get_prompt(pname, pargs)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": result}
                except Exception as e:
                    from prompts import PromptNotFoundError
                    if isinstance(e, PromptNotFoundError):
                        response = {"jsonrpc": "2.0", "id": req_id,
                                    "error": {"code": -32602, "message": str(e)}}
                    else:
                        response = {"jsonrpc": "2.0", "id": req_id,
                                    "error": {"code": -32603, "message": f"prompt error: {e}"}}
            elif method == "sampling/createMessage":
                # 服务端反向调用 LLM（用现有 LLM Router）
                msgs = params.get("messages", [])
                max_tokens = params.get("maxTokens", 1024)
                prompt_text = "\n".join([m.get("content", {}).get("text", "") if isinstance(m.get("content"), dict) else str(m.get("content", "")) for m in msgs])
                if LLM_AVAILABLE and LLM_ROUTER:
                    llm_result = LLM_ROUTER.call(prompt_text, task="general", max_tokens=max_tokens)
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "result": {
                                    "role": "assistant",
                                    "content": {"type": "text", "text": llm_result["text"]},
                                    "model": llm_result["provider"],
                                    "stopReason": "endTurn",
                                }}
                else:
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32002, "message": "LLM not available"}}
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                if tool_name not in TOOL_REGISTRY:
                    response = {"jsonrpc": "2.0", "id": req_id,
                                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}}
                else:
                    try:
                        # RBAC 检查
                        if not self._check_rbac(tool_name):
                            # 修复: 拒绝时返回合法 JSON-RPC 错误响应
                            # （此前 return None → _send_json(200, null) 破坏协议）
                            response = {"jsonrpc": "2.0", "id": req_id,
                                        "error": {"code": -32004,
                                                  "message": f"forbidden: no permission for tool {tool_name}"}}
                            return response
                        tool_start = time.time()
                        # streaming support - 检查客户端请求 streaming
                        want_streaming = params.get("streaming", False)
                        progress_token = None
                        if want_streaming:
                            import uuid
                            progress_token = str(uuid.uuid4())[:8]
                            # 推送初始 progress（10%）
                            progress_event = {
                                "jsonrpc": "2.0",
                                "method": "notifications/progress",
                                "params": {
                                    "progressToken": progress_token,
                                    "progress": 10,
                                    "total": 100,
                                    "message": f"Starting {tool_name}",
                                }
                            }
                            print(f"data: {json.dumps(progress_event)}\n\n", file=sys.stderr, flush=True)
                        # 发布工具调用事件（GraphQL subscription）
                        if GRAPHQL_AVAILABLE:
                            try:
                                publish_tool_event({
                                    "tool": tool_name,
                                    "arguments": arguments,
                                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                })
                            except Exception:
                                pass
                        result = _gateway_invoke(tool_name, arguments)
                        if want_streaming:
                            # 完成时推送 100%
                            complete_event = {
                                "jsonrpc": "2.0",
                                "method": "notifications/progress",
                                "params": {
                                    "progressToken": progress_token,
                                    "progress": 100,
                                    "total": 100,
                                    "message": f"Completed {tool_name}",
                                }
                            }
                            print(f"data: {json.dumps(complete_event)}\n\n", file=sys.stderr, flush=True)
                        tool_duration = time.time() - tool_start
                        # 记录 metrics
                        if METRICS_AVAILABLE:
                            record_tool_call(tool_name, tool_duration, success=True)
                            # LLM 调用 metrics
                            if isinstance(result, dict) and "llm_meta" in result:
                                provider = result["llm_meta"].get("provider", "-")
                                mode = result["llm_meta"].get("mode", "unknown")
                                record_llm_call(provider, mode, tool_duration, success=True)
                        # 提取 provider
                        if isinstance(result, dict) and "llm_meta" in result:
                            provider = result["llm_meta"].get("provider", "-")
                        result_content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
                        result_extra = {}
                        if want_streaming and progress_token:
                            result_extra["progressToken"] = progress_token
                        response = {
                            "jsonrpc": "2.0", "id": req_id,
                            "result": {
                                "content": result_content,
                                **result_extra,
                            },
                        }
                    except Exception as e:
                        if METRICS_AVAILABLE:
                            record_tool_call(tool_name, 0, success=False)
                            record_error("tool_error")
                        response = {"jsonrpc": "2.0", "id": req_id,
                                    "error": {"code": -32603, "message": f"Tool execution error: {e}"}}
            elif method == "ping":
                response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
            else:
                response = {"jsonrpc": "2.0", "id": req_id,
                            "error": {"code": -32601, "message": f"Method not found: {method}"}}

            status = "ok" if "result" in response else "error"
        except Exception as e:
            response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}
            status = "exception"

        # 审计日志
        AUDIT.log(
            method=method or "unknown",
            params_summary=json.dumps(params)[:200] if params else "",
            status=status,
            duration_s=time.time() - start,
            provider=provider,
        )

        # 记录 metrics
        if METRICS_AVAILABLE:
            tool_name = params.get("name", "-") if method == "tools/call" else "-"
            record_request(method or "unknown", tool_name, status, time.time() - start)

        return response


# ============ · GraphQL schema ============
def _gql_tools_provider():
    """GraphQL tools provider（TOOL_REGISTRY）"""
    return [
        {"name": t["name"], "description": t.get("description", ""),
         "inputSchema": t.get("inputSchema", {})}
        for t in TOOL_REGISTRY.values()
    ]


def _gql_call_provider(name: str, arguments: Dict) -> Dict:
    """GraphQL callTool resolver（TOOL_REGISTRY handler）"""
    if name not in TOOL_REGISTRY:
        raise ValueError(f"Tool not found: {name}")
    handler = TOOL_REGISTRY[name].get("handler")
    if not handler:
        raise ValueError(f"Tool {name} has no handler")
    # 发布工具调用事件（GraphQL subscription）
    if GRAPHQL_AVAILABLE:
        try:
            publish_tool_event({
                "tool": name,
                "arguments": arguments or {},
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
        except Exception:
            pass
    # OpenTelemetry span
    span = start_tool_span(name, arguments) if TRACING_AVAILABLE else None
    try:
        result = handler(**arguments) if arguments else handler()
        _gateway_record(name, result)  # 网关兜底采样（未带标记才采样 · 防双计）
        return result
    except TypeError:
        # 某些 handler 不接受 kwargs（容错）
        result = handler(arguments)
        _gateway_record(name, result)
        return result
    finally:
        if span:
            span.end()


def _gql_health_provider():
    return {"status": "ok", "version": SERVER_VERSION,
            "uptime": round(time.time() - SERVER_START_TIME, 2)}


def _gql_stats_provider():
    return {
        "requests_total": getattr(AUDIT, "count", 0) if hasattr(AUDIT, "count") else 0,
        "tools_called": len(TOOL_REGISTRY),
        "active_sessions": 0,
    }


_GRAPHQL_SCHEMA = None


def get_graphql_schema():
    global _GRAPHQL_SCHEMA
    if _GRAPHQL_SCHEMA is None and GRAPHQL_AVAILABLE:
        from graphql import GraphQLSchema
        base = build_schema(_gql_tools_provider, _gql_call_provider,
                            _gql_health_provider, _gql_stats_provider)
        # 附加 Subscription 类型（WS 实时推送）
        try:
            sub_type = build_subscription_schema()
            _GRAPHQL_SCHEMA = GraphQLSchema(
                query=base.query_type,
                mutation=base.mutation_type,
                subscription=sub_type,
            )
        except Exception:
            _GRAPHQL_SCHEMA = base
    return _GRAPHQL_SCHEMA


# ============ · multi-process HTTP（QPS 提升）============
def _worker_process(host: str, port: int, worker_id: int):
    """worker 进程：SO_REUSEPORT 共享端口 + ThreadingHTTPServer"""
    try:
        server = ThreadingHTTPServer((host, port), QCMHTTPHandler, bind_and_activate=False)
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        server.server_bind()
        server.server_activate()
    except OSError as e:
        print(f"[qcm-mcp v{SERVER_VERSION}] worker-{worker_id} bind 失败: {e}", file=sys.stderr)
        return
    print(f"[qcm-mcp v{SERVER_VERSION}] worker-{worker_id} listening on http://{host}:{port} (pid={os.getpid()})",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def run_multi_process(host: str = "127.0.0.1", port: int = 8080, workers: int = 1):
    """: 多进程 HTTP 服务器（SO_REUSEPORT 共享端口）

    - workers=1：单进程（默认 · 兼容旧行为）
    - workers>1：multiprocessing 起 N 个 worker（Linux SO_REUSEPORT）
    - 每个 worker 内部仍是 ThreadingHTTPServer（线程+进程双层并发）
    """
    if workers <= 1:
        start_http_server(host, port)
        return

    print(f"[qcm-mcp v{SERVER_VERSION}] 启动 {workers} 个 worker 进程（SO_REUSEPORT）", file=sys.stderr)
    procs = []
    for i in range(workers):
        p = multiprocessing.Process(target=_worker_process, args=(host, port, i), daemon=True)
        p.start()
        procs.append(p)

    try:
        while True:
            time.sleep(60)
            # 监控：worker 退出则重启（简单 supervisor）
            for i, p in enumerate(procs):
                if not p.is_alive():
                    print(f"[qcm-mcp v{SERVER_VERSION}] worker-{i} 退出（code={p.exitcode}），重启", file=sys.stderr)
                    new_p = multiprocessing.Process(target=_worker_process, args=(host, port, i), daemon=True)
                    new_p.start()
                    procs[i] = new_p
    except KeyboardInterrupt:
        print(f"\n[qcm-mcp v{SERVER_VERSION}] 关闭多进程服务器", file=sys.stderr)
        for p in procs:
            p.terminate()


SERVER_START_TIME = time.time()


def start_http_server(host: str = "127.0.0.1", port: int = 8080):
    """启动 HTTP/SSE 服务器（阻塞）"""
    server = ThreadingHTTPServer((host, port), QCMHTTPHandler)
    # E1-04 服务端 TLS：将监听套接字包装为 SSL（server_side），accept 出的连接自动 TLS 握手
    if TLS_CTX is not None:
        try:
            server.socket = TLS_CTX.context.wrap_socket(server.socket, server_side=True)
            scheme = "https"
        except Exception as e:
            print(f"[qcm-mcp v{SERVER_VERSION}] ⚠ TLS 套接字包装失败（回退 HTTP）：{e}", file=sys.stderr)
            scheme = "http"
    else:
        scheme = "http"
    print(f"[qcm-mcp v{SERVER_VERSION}] HTTP/SSE listening on {scheme}://{host}:{port}", file=sys.stderr)
    print(f"  MCP API:", file=sys.stderr)
    print(f"    tools + resources + prompts + sampling", file=sys.stderr)
    print(f"  Endpoints:", file=sys.stderr)
    print(f"    GET  /health /health/live /health/ready", file=sys.stderr)
    print(f"    GET  /metrics /stats", file=sys.stderr)
    print(f"    GET  /sse            (Server-Sent Events)", file=sys.stderr)
    print(f"    POST /messages /rpc  (JSON-RPC + auth + rate limit)", file=sys.stderr)
    print(f"  Audit log: {AUDIT.log_dir}", file=sys.stderr)
    print(f"  Access log: {ACCESS.log_dir}", file=sys.stderr)
    if TLS_CTX is not None:
        _exp = TLS_CTX.expiry()
        if _exp:
            print(f"  TLS cert expires: {_exp['not_after']} ({_exp['days_remaining']}d remaining)", file=sys.stderr)
    if UPSTREAM_URL:
        print(f"  Upstream probe: {UPSTREAM_URL} (via connection pool)", file=sys.stderr)
    if METRICS_AVAILABLE and default_rate_limiter:
        print(f"  Rate limit: per_ip={default_rate_limiter.per_ip}/{default_rate_limiter.per_ip_window_s}s · per_token={default_rate_limiter.per_token}/{default_rate_limiter.per_token_window_s}s · global={default_rate_limiter.global_limit}/{default_rate_limiter.global_window_s}s", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()




if __name__ == "__main__":
    main()