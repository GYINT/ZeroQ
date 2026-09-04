#!/usr/bin/env python3
"""ws_push.py — QCM MCP WS 旁路事件推送服务器

stdio/http 主传输 + WebSocket 旁路推送（双通道共存 ·）：
- 主传输（stdio/http）负责 JSON-RPC 工具调用（既有逻辑不变）
- WS 旁路（本模块）轻量级事件推送：只接受 graphql-ws subscription 连接，
  通过 qcm_graphql 事件总线推送 toolCalled 事件，让默认模式（stdio/http）
  下的客户端也能实时订阅工具调用事件
- 不处理 JSON-RPC —— 主传输是唯一命令通道，旁路是纯事件通道

设计要点：
1. 单职责：只推送 toolCalled 事件（subscribe/next/complete/ping/pong）
2. 事件总线复用：qcm_graphql.publish_tool_event / subscribe_tool_events
   （asyncio.Queue · put_nowait 跨线程安全，http 主线程可安全发布）
3. 三形态入口：
   - run_ws_push_server_async() → stdio 模式同 event loop 并行（create_task）
   - run_ws_push_server()        → 阻塞版（asyncio.run 包装）
   - start_ws_push_thread()      → http 模式 daemon thread（就绪事件可等待）

用法：
  from qcm_ws_push import build_push_schema, start_ws_push_thread
  thread, ready = start_ws_push_thread(build_push_schema(), port=8765)
  ready.wait(timeout=5)
"""
import json
import asyncio
import sys
import threading
from typing import Any, Dict, Optional, Tuple

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False


def build_push_schema(subscription_resolver=None):
    """构建最小 WS 旁路 schema（query: health + subscription: toolCalled）

    - 不依赖 TOOL_REGISTRY / qcm_mcp_server —— 轻量独立
    - subscription resolver 默认走 qcm_graphql.subscribe_tool_events
      （注册队列到全局事件总线）
    """
    from graphql import (
        GraphQLSchema, GraphQLObjectType, GraphQLField, GraphQLString,
    )
    from qcm_graphql import build_subscription_schema

    query = GraphQLObjectType(
        "Query",
        lambda: {
            "health": GraphQLField(
                GraphQLString,
                resolve=lambda _root, _info: "ok",
            ),
        },
    )
    return GraphQLSchema(
        query=query,
        subscription=build_subscription_schema(subscription_resolver),
    )


def _parse_payload(payload: Dict) -> Dict:
    """解析 GraphQL payload —— 仅接受 subscription（旁路不处理 query/mutation）"""
    from graphql import parse, OperationType

    query = payload.get("query", "")
    variables = payload.get("variables") or {}
    try:
        doc = parse(query)
    except Exception as e:
        return {"errors": [{"message": f"Parse error: {e}"}]}

    is_subscription = False
    for op in doc.definitions:
        if getattr(op, "operation", None) == OperationType.SUBSCRIPTION:
            is_subscription = True
            break
    if not is_subscription:
        return {"errors": [{"message": "WS 旁路仅支持 subscription（toolCalled）"}]}
    return {"type": "subscription", "doc": doc, "variables": variables}


async def _handle_push_ws(websocket, schema, require_token: bool,
                          fixed_token: Optional[str], server_name: str):
    """graphql-ws 订阅处理（轻量版 · 无 JSON-RPC 分支）"""
    import secrets

    # 认证（可选 · 与主传输共用 token）
    if require_token:
        try:
            headers = websocket.request.headers
            auth = headers.get("Authorization", "") if headers else ""
        except Exception:
            auth = ""
        if not (auth.startswith("Bearer ") and fixed_token
                and secrets.compare_digest(auth[7:], fixed_token)):
            await websocket.send(json.dumps({"type": "connection_error",
                                             "payload": {"message": "Unauthorized"}}))
            return

    subscriptions: Dict[str, asyncio.Task] = {}

    async for raw in websocket:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        msg_type = msg.get("type", "")
        msg_id = msg.get("id")

        if msg_type == "connection_init":
            await websocket.send(json.dumps({"type": "connection_ack"}))

        elif msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong"}))

        elif msg_type == "subscribe":
            if not msg_id:
                continue
            parsed = _parse_payload(msg.get("payload", {}))
            if "errors" in parsed:
                await websocket.send(json.dumps({
                    "type": "error", "id": msg_id, "payload": parsed["errors"]}))
                continue

            async def _run_subscription(doc, variables, sid):
                from graphql import validate, subscribe
                from graphql.execution.execute import ExecutionResult
                try:
                    v_errors = validate(schema, doc)
                    if v_errors:
                        await websocket.send(json.dumps({
                            "type": "error", "id": sid,
                            "payload": [{"message": str(e)} for e in v_errors]}))
                        return
                    result = await subscribe(schema, doc, variable_values=variables)
                    if isinstance(result, ExecutionResult):
                        await websocket.send(json.dumps({
                            "type": "error", "id": sid,
                            "payload": [{"message": str(e)} for e in (result.errors or [])]}))
                        return
                    async for event in result:
                        await websocket.send(json.dumps({
                            "type": "next", "id": sid, "payload": {"data": event.data}}))
                    await websocket.send(json.dumps({"type": "complete", "id": sid}))
                except Exception as e:
                    try:
                        await websocket.send(json.dumps({
                            "type": "error", "id": sid, "payload": [{"message": str(e)}]}))
                    except Exception:
                        pass

            task = asyncio.ensure_future(
                _run_subscription(parsed["doc"], parsed["variables"], msg_id))
            subscriptions[msg_id] = task

        elif msg_type == "complete":
            task = subscriptions.pop(msg_id, None)
            if task:
                task.cancel()

        elif msg_type == "connection_terminate":
            for t in subscriptions.values():
                t.cancel()
            return


async def run_ws_push_server_async(schema, port: int = 8765, host: str = "0.0.0.0",
                                   require_token: bool = False,
                                   fixed_token: Optional[str] = None,
                                   server_name: str = "qcm-ws-push"):
    """协程版：启动 WS 旁路推送服务器（stdio 模式同 event loop 并行）

    stdio 用法：
      push_task = asyncio.create_task(run_ws_push_server_async(schema, port))
      await handle_stdio()
    """
    if not WEBSOCKETS_AVAILABLE:
        raise RuntimeError("需要 pip install websockets")

    async def handler(websocket):
        await _handle_push_ws(websocket, schema, require_token, fixed_token, server_name)

    async with websockets.serve(handler, host, port, max_size=10 * 1024 * 1024):
        # 日志统一走 stderr（stdio 模式下 stdout 是 JSON-RPC 协议通道，禁止污染）
        print(f"[{server_name} v1.0.1] WS 旁路推送 ws://{host}:{port}"
              f"（toolCalled 事件订阅）", file=sys.stderr, flush=True)
        await asyncio.Future()  # 永久运行


def run_ws_push_server(schema, port: int = 8765, host: str = "0.0.0.0",
                       require_token: bool = False,
                       fixed_token: Optional[str] = None,
                       server_name: str = "qcm-ws-push"):
    """阻塞版：启动 WS 旁路推送服务器（独立 event loop）"""
    try:
        asyncio.run(run_ws_push_server_async(
            schema, port=port, host=host, require_token=require_token,
            fixed_token=fixed_token, server_name=server_name))
    except KeyboardInterrupt:
        pass


def start_ws_push_thread(schema, port: int = 8765, host: str = "0.0.0.0",
                         require_token: bool = False,
                         fixed_token: Optional[str] = None,
                         server_name: str = "qcm-ws-push",
                         ready_timeout: float = 5.0) -> Tuple[threading.Thread, threading.Event]:
    """线程版：http 模式并行启动 WS 旁路（daemon thread）

    返回 (thread, ready_event)：
      - ready_event 在服务器监听就绪后 set（调用方可 wait 确认）
      - 线程为 daemon —— 主进程退出自动回收

    事件总线跨线程安全：qcm_graphql 的 publish_tool_event 使用
    asyncio.Queue.put_nowait（无 waiter 时仅入队，不依赖 event loop），
    http 主线程可安全发布事件到旁路订阅者。
    """
    if not WEBSOCKETS_AVAILABLE:
        raise RuntimeError("需要 pip install websockets")

    ready = threading.Event()

    def _run():
        async def _serve():
            async def handler(websocket):
                await _handle_push_ws(websocket, schema, require_token,
                                      fixed_token, server_name)

            async with websockets.serve(handler, host, port, max_size=10 * 1024 * 1024):
                ready.set()
                print(f"[{server_name} v1.0.1] WS 旁路推送 ws://{host}:{port}"
                      f"（toolCalled 事件订阅）", file=sys.stderr, flush=True)
                await asyncio.Future()

        try:
            asyncio.run(_serve())
        except OSError as e:
            # 端口冲突：降级为不可用（不阻塞主传输）—— ready 不 set
            print(f"[{server_name} v1.0.1] WS 旁路启动失败（端口 {port}）: {e}",
                  file=sys.stderr)
        except KeyboardInterrupt:
            pass

    t = threading.Thread(target=_run, daemon=True, name="qcm-ws-push")
    t.start()
    ready.wait(timeout=ready_timeout)
    return t, ready


if __name__ == "__main__":
    # Demo：起一个 WS 旁路推送服务器（端口 8770）
    import sys
    schema = build_push_schema()
    run_ws_push_server(schema, port=int(sys.argv[1]) if len(sys.argv) > 1 else 8770)
