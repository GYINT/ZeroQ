"""mcp_tls.py — QCM 服务端 TLS/HTTPS（E1-04）

- TLSConfig：从 cert/key 文件加载并构建 ssl.SSLContext（TLS1.2+ 最低版本）
- 证书过期检测（expiry / days_remaining）
- 可选文件监听自动重载（certbot 续期后无需重启，watcher 热加载新证书）

典型用法：
    cfg = TLSConfig("cert.pem", "key.pem", watch=True)
    server.socket = cfg.context.wrap_socket(server.socket, server_side=True)
"""
from __future__ import annotations

import os
import ssl
import threading
import time
from datetime import datetime, timezone


class TLSConfig:
    """服务端 TLS 配置：加载证书链、构建 SSLContext、可选热重载。"""

    def __init__(self, cert_path: str, key_path: str, watch: bool = False, watch_interval: float = 30.0):
        if not os.path.isfile(cert_path):
            raise FileNotFoundError(f"TLS 证书不存在: {cert_path}")
        if not os.path.isfile(key_path):
            raise FileNotFoundError(f"TLS 私钥不存在: {key_path}")
        self.cert_path = cert_path
        self.key_path = key_path
        self.watch = watch
        self.watch_interval = watch_interval
        self._lock = threading.Lock()
        self._mtime = 0
        self.context = None
        self.reload()
        if self.watch:
            self._start_watcher()

    def reload(self):
        """重新加载证书并构建 SSLContext（TLS1.2+）。失败抛异常，由调用方决定降级。"""
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # 仅允许 TLS1.2 / 1.3（禁用 SSLv2/3、TLS1.0/1.1）
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=self.cert_path, keyfile=self.key_path)
        try:
            self._mtime = os.path.getmtime(self.cert_path)
        except OSError:
            self._mtime = 0
        with self._lock:
            self.context = ctx

    def expiry(self):
        """证书过期信息（依赖 cryptography；缺失则降级返回 None）。

        返回 {"not_after": ISO8601, "days_remaining": int} 或 None。
        """
        try:
            from cryptography import x509
            with open(self.cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
            not_after = cert.not_valid_after_utc
            now = datetime.now(timezone.utc)
            days = (not_after - now).days
            return {"not_after": not_after.isoformat(), "days_remaining": days}
        except Exception:
            return None

    def _start_watcher(self):
        """后台线程：监听证书文件 mtime，变更即热重载（支撑 certbot 续期）。"""
        def _loop():
            while True:
                time.sleep(self.watch_interval)
                try:
                    m = os.path.getmtime(self.cert_path)
                    if m != self._mtime:
                        self.reload()
                except Exception:
                    pass

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def https_url(self, host: str = "127.0.0.1", port: int = 8080) -> str:
        return f"https://{host}:{port}"
