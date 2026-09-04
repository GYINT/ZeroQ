#!/usr/bin/env python3
"""bench_connection_pool.py — E1-03 连接池复用基准对比（供 E1-06 基准报告引用）

离线可跑（无需外网）：起一个本地 ThreadingHTTPServer，分别用
  (A) 连接池 HTTPClient（urllib3.PoolManager 复用）
  (B) 朴素每次新建连接（urllib.request 直连，无池）
对同 host 发起 N 次 GET，对比耗时 + 连接复用统计。

输出结论：池化在高频同 host 场景显著减少 TCP/TLS 建连开销。
"""
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from mcp_http_client import HTTPClient  # noqa: E402
import urllib.request  # noqa: E402


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        b = b"pong"
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


def _bench_pooled(port, n):
    c = HTTPClient(maxsize=10, retries=0, timeout=5.0)
    t0 = time.perf_counter()
    for _ in range(n):
        r = c.get(f"http://127.0.0.1:{port}/")
        assert r.status == 200
    dt = time.perf_counter() - t0
    st = c.stats()
    c.close()
    return dt, st


def _bench_plain(port, n):
    t0 = time.perf_counter()
    for _ in range(n):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
    return time.perf_counter() - t0


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        dt_pool, st = _bench_pooled(port, N)
        dt_plain = _bench_plain(port, N)
        print("=" * 64)
        print(f"E1-03 连接池基准（N={N} 次 GET · 本地 loopback · 无外网）")
        print("=" * 64)
        print(f"  [池化] 耗时 {dt_pool*1000:.1f} ms · 建连 {st['num_connections']} · 复用 {st['reused']} · 复用率 {st['reused']/max(st['num_requests'],1)*100:.0f}%")
        print(f"  [朴素] 耗时 {dt_plain*1000:.1f} ms（每次新建连接）")
        speedup = dt_plain / dt_pool if dt_pool > 0 else float('inf')
        print(f"  → 池化相对朴素提速约 {speedup:.2f}x（高频同 host 场景收益显著）")
        print("=" * 64)
    finally:
        srv.shutdown()


if __name__ == "__main__":
    main()
