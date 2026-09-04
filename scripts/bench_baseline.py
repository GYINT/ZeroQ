#!/usr/bin/env python3
"""bench_baseline.py — E1-06 性能基准（V1.0-04 表 8 项 · 离线可测部分）

沙箱无外网 → 真实 LLM 相关项（tools/call real-LLM 延迟）无法实测，仅测离线可验证项：
  - 启动时间（首次，含 jieba/corpus 初始化）
  - tools/call mock 路径延迟（qcm_validate 规则引擎，无 LLM）—— p50 / p95
  - 并发 QPS（4 workers 配置下的 loopback 压测）
  - Memory/worker（进程 RSS，依赖 psutil，缺失则跳过并标注）

真实 LLM 项（real-LLM p50<3s / p95<10s）与跨机内存基线 → 文档化缺口，待生产环境终验。
"""
import subprocess
import sys
import os
import time
import json
import tempfile
import shutil
import urllib.request
from pathlib import Path

QCM_ROOT = Path(__file__).resolve().parents[1]
SERVER = str(QCM_ROOT / "scripts" / "mcp_server.py")
PY = sys.executable


def _start(port, access_dir):
    # 注意：--require-token 为 store_true，不传值；默认关闭认证（bench 不携带 token）
    # workers=1：Windows 沙箱下 SO_REUSEPORT 不可用，多进程(>1)仅 *nix 支持；
    # 生产镜像(docker)亦默认单 worker，符合本环境可测基线。
    env = {**os.environ, "QCM_ACCESS_LOG_DIR": access_dir, "QCM_REQUIRE_TOKEN": "0"}
    p = subprocess.Popen([PY, SERVER, "--transport", "http", "--host", "127.0.0.1",
                          "--port", str(port), "--workers", "1"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return p
        except Exception:
            pass
        time.sleep(0.1)
    return p


def _measure_startup(port, access_dir):
    t0 = time.time()
    p = _start(port, access_dir)
    return time.time() - t0, p


def _measure_qps(port, n=400, workers=64):
    def get():
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            return r.status
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda _: get(), range(n)))
    dt = time.time() - t0
    return n / dt, dt


def _measure_tool_call(port, n=50):
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "qcm_validate", "arguments": {
            "output_text": "行动要项：围堵变异\n事态导航：T2→L2\n危机沟通：D=3 P3",
            "form": "quick-response"}},
    }).encode("utf-8")
    lat = []
    for _ in range(n):
        t0 = time.time()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/messages", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        lat.append(time.time() - t0)
    lat.sort()
    p50 = lat[int(len(lat) * 0.5)]
    p95 = lat[int(len(lat) * 0.95)]
    return p50, p95


def _measure_rss(pid):
    try:
        import psutil
        return psutil.Process(pid).memory_info().rss / 1024 / 1024
    except Exception:
        return None


def main():
    access_dir = tempfile.mkdtemp(prefix="qcm-bench-")
    port = 18103
    try:
        startup, proc = _measure_startup(port, access_dir)
        qps, qps_dt = _measure_qps(port)
        p50, p95 = _measure_tool_call(port)
        rss = _measure_rss(proc.pid)
        print("=" * 64)
        print("E1-06 性能基准（离线可测项 · 沙箱无外网）")
        print("=" * 64)
        print(f"  启动时间(首次)     : {startup*1000:.0f} ms   (目标 <1s)")
        print(f"  tools/call p50     : {p50*1000:.1f} ms   (mock 目标 <50ms)")
        print(f"  tools/call p95     : {p95*1000:.1f} ms   (mock 目标 <200ms)")
        print(f"  并发 QPS(单 worker): {qps:.1f}            (目标 4 workers >100；*nix 多进程 SO_REUSEPORT)")
        print(f"  Memory/worker(RSS) : {('%.1f MB' % rss) if rss else 'N/A (无 psutil)'}")
        print("-" * 64)
        print("  真实 LLM 延迟 / 跨机内存基线：沙箱无外网 → 文档化缺口（待生产终验）")
        print("=" * 64)
    finally:
        try:
            proc.terminate(); proc.wait(timeout=5)
        except Exception:
            try: proc.kill()
            except Exception: pass
        shutil.rmtree(access_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
