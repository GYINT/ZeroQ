"""mcp_http_client.py — QCM 出站 HTTP 连接池客户端（E1-03）

基于 urllib3.PoolManager 实现连接复用，避免每次请求新建 TCP/TLS 连接。
作为 QCM 全部出站 HTTP 调用（LLM Provider / 上游就绪探针 / webhook）的统一客户端。

特性：
- 连接池复用（num_pools / maxsize 可配）
- 自动重试（Retry · 指数退避 · 对 429/5xx 触发）
- 超时控制
- 连接复用统计（stats() · 证明 num_connections < num_requests）
"""
from __future__ import annotations

import urllib3
from typing import Optional


class HTTPClient:
    """带连接池复用的出站 HTTP 客户端。"""

    def __init__(self, maxsize: int = 10, num_pools: int = 10,
                 retries: int = 2, timeout: float = 10.0,
                 headers: Optional[dict] = None):
        self._maxsize = maxsize
        self._retries = retries
        self._timeout = timeout
        self._default_headers = headers or {}
        self._pool = urllib3.PoolManager(
            num_pools=num_pools,
            maxsize=maxsize,
            retries=urllib3.Retry(
                total=retries,
                backoff_factor=0.1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "HEAD"]),
            ),
            timeout=urllib3.Timeout(total=timeout),
        )

    def request(self, method: str, url: str, body=None, headers=None, **kw):
        final_headers = {**self._default_headers, **(headers or {})}
        return self._pool.request(method, url, body=body, headers=final_headers, **kw)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, body=None, **kw):
        return self.request("POST", url, body=body, **kw)

    @property
    def pool_manager(self) -> urllib3.PoolManager:
        return self._pool

    def stats(self) -> dict:
        """连接复用统计：num_connections（建连数）vs num_requests（请求数）。

        num_connections < num_requests 即证明连接被复用（同一连接服务多次请求）。
        """
        pools = getattr(self._pool, "pools", None)
        pool_list = []
        if pools is not None:
            # urllib3 PoolManager.pools 是 RecentlyUsedContainer（禁止直接迭代）；
            # 经其私有 _container 取出真实连接池对象（已在 venv urllib3 2.7.0 验证稳定）。
            container = getattr(pools, "_container", None)
            if container is not None:
                pool_list = list(container.values())
            else:
                try:
                    pool_list = list(pools.values())
                except Exception:
                    pool_list = []
        num_connections = sum(getattr(p, "num_connections", 0) for p in pool_list)
        num_requests = sum(getattr(p, "num_requests", 0) for p in pool_list)
        return {
            "pools": len(pool_list),
            "num_connections": num_connections,
            "num_requests": num_requests,
            "reused": num_requests - num_connections,
        }

    def close(self):
        try:
            self._pool.clear()
        except Exception:
            pass


# 默认出站客户端（单例 · 全 QCM 出站调用共享连接池）
DEFAULT_HTTP_CLIENT = HTTPClient()
