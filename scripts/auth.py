#!/usr/bin/env python3
"""qcm_auth.py — QCM MCP Auth + RBAC + Secret 加密

功能：
  - OAuth 2.0 client_credentials flow（简化版）
  - JWT-like Token（HMAC-SHA256）
  - RBAC per-tool 权限
  - Secret 加密/解密（Fernet · 可选）

Token 格式：
  qcm_<base64-header>.<base64-payload>.<base64-sig>
  例：qcm.eyJ0eXAiOiJKV1QifQ.eyJzdWIiOiIxMjM0NSJ9.<sig>

Token 字段：
  - sub: subject (client_id)
  - scope: list of scopes (e.g., ["tools/call", "tools/list"])
  - roles: list of roles (e.g., ["admin", "auditor"])
  - exp: expiration timestamp
  - iat: issued at
  - tenant: tenant id (multi-tenant )

用法：
  from auth import AuthManager
  auth = AuthManager(secret_key="...")

  # OAuth 流程
  token = auth.client_credentials("client1", "secret1", scope=["tools/call"])

  # 验证
  payload = auth.verify(token)
  if payload:
      # 检查 RBAC
      if auth.check_scope(payload, "tools/call"):
          ...
"""
import os
import time
import hmac
import hashlib
import json
import base64
import secrets
from typing import Optional, List, Dict, Any
from urllib.parse import parse_qs


class AuthManager:
    """OAuth 2.0 简化版 + RBAC"""

    def __init__(self, secret_key: Optional[str] = None, token_ttl_s: int = 3600):
        self.secret_key = secret_key or os.environ.get("QCM_JWT_SECRET", secrets.token_hex(32))
        self.token_ttl_s = token_ttl_s

        # Multi-tenant 支持
        # 默认租户：default
        default_secret_hash = self._hash("default-secret")
        self.tenants: Dict[str, Dict] = {
            "default": {
                "client_id": "default-client",
                "client_secret_hash": default_secret_hash,
                "scopes": ["*"],  # 全部权限
                "roles": ["admin"],
                "rate_limit": 1000,
            }
        }

        # 加载额外租户（QCM_TENANTS_FILE 环境变量）
        tenants_file = os.environ.get("QCM_TENANTS_FILE")
        if tenants_file and os.path.exists(tenants_file):
            self._load_tenants(tenants_file)

        # RBAC scope 映射
        self.scope_to_tools = {
            "tools/list": ["*"],  # 任何 client 都能 list
            "tools/call": ["*"],  # 默认所有 tools
            "resources/read": ["*"],
            "prompts/list": ["*"],
            "prompts/get": ["*"],
            "admin": ["*"],
        }

    def _hash(self, s: str) -> str:
        """HMAC-SHA256 哈希"""
        return hmac.new(self.secret_key.encode(), s.encode(), hashlib.sha256).hexdigest()

    def _load_tenants(self, filepath: str):
        """从 JSON 文件加载租户"""
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            for tenant_id, tenant_cfg in data.get("tenants", {}).items():
                if "client_secret" in tenant_cfg:
                    tenant_cfg["client_secret_hash"] = self._hash(tenant_cfg["client_secret"])
                self.tenants[tenant_id] = tenant_cfg
        except Exception as e:
            print(f"[auth] Failed to load tenants: {e}", flush=True)

    def _b64url_encode(self, data: bytes) -> str:
        """base64url 编码"""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def _b64url_decode(self, s: str) -> bytes:
        """base64url 解码"""
        s += "=" * (4 - len(s) % 4)
        return base64.urlsafe_b64decode(s)

    def _sign(self, header_b64: str, payload_b64: str) -> str:
        """计算签名"""
        msg = f"{header_b64}.{payload_b64}".encode()
        sig = hmac.new(self.secret_key.encode(), msg, hashlib.sha256).digest()
        return self._b64url_encode(sig)

    def client_credentials(
        self,
        client_id: str,
        client_secret: str,
        scope: Optional[List[str]] = None,
        tenant: str = "default",
    ) -> Dict[str, Any]:
        """OAuth 2.0 client_credentials flow

        Returns:
            {"access_token": "...", "token_type": "Bearer", "expires_in": 3600, "scope": [...]}
        """
        # 查找 tenant
        tenant_cfg = self.tenants.get(tenant, self.tenants["default"])

        # 验证 client
        if tenant_cfg.get("client_id") != client_id:
            return {"error": "invalid_client", "error_description": "unknown client_id"}

        secret_hash = self._hash(client_secret)
        if not hmac.compare_digest(secret_hash, tenant_cfg.get("client_secret_hash", "")):
            return {"error": "invalid_client", "error_description": "wrong client_secret"}

        # 分配 scope（支持 wildcard "*"）
        tenant_scopes = tenant_cfg.get("scopes", ["tools/call", "tools/list"])
        is_wildcard = "*" in tenant_scopes

        if scope is None:
            granted_scope = tenant_scopes if not is_wildcard else ["tools/call", "tools/list", "resources/read", "prompts/list", "prompts/get", "resources/list", "sampling/createMessage"]
        elif is_wildcard:
            # Wildcard tenant：所有请求 scope 都通过
            granted_scope = scope
        else:
            granted_scope = [s for s in scope if s in tenant_scopes]

        # 签发 token
        now = int(time.time())
        payload = {
            "sub": client_id,
            "tenant": tenant,
            "scope": granted_scope,
            "roles": tenant_cfg.get("roles", []),
            "iat": now,
            "exp": now + self.token_ttl_s,
        }
        token = self._make_token(payload)

        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": self.token_ttl_s,
            "scope": " ".join(granted_scope),
        }

    def _make_token(self, payload: Dict[str, Any]) -> str:
        """签发 JWT-like token"""
        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = self._b64url_encode(json.dumps(header).encode())
        payload_b64 = self._b64url_encode(json.dumps(payload).encode())
        sig = self._sign(header_b64, payload_b64)
        return f"qcm.{header_b64}.{payload_b64}.{sig}"

    def verify(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 token，返回 payload（无效返回 None）"""
        if not token or not token.startswith("qcm."):
            return None
        try:
            parts = token.split(".")
            if len(parts) != 4:
                return None
            _, header_b64, payload_b64, sig = parts

            # 验证签名
            expected_sig = self._sign(header_b64, payload_b64)
            if not hmac.compare_digest(sig, expected_sig):
                return None

            # 解析 payload
            payload = json.loads(self._b64url_decode(payload_b64))

            # 检查过期
            if payload.get("exp", 0) < time.time():
                return None

            return payload
        except Exception:
            return None

    def check_scope(self, payload: Dict, required_scope: str) -> bool:
        """检查 scope（RBAC）"""
        if not payload:
            return False
        scopes = payload.get("scope", [])
        roles = payload.get("roles", [])
        # admin 角色有所有权限
        if "admin" in roles or "*" in scopes:
            return True
        return required_scope in scopes

    def check_tool(self, payload: Dict, tool_name: str) -> bool:
        """检查 tool 权限（更细粒度 RBAC）"""
        if not payload:
            return False
        roles = payload.get("roles", [])
        if "admin" in roles:
            return True
        # 默认所有 client 都能调用所有 tools（简化）
        # 可扩展 per-tool 限制
        return "tools/call" in payload.get("scope", []) or "*" in payload.get("scope", [])


# ============ Secret 加密============
class SecretCipher:
    """API Key 加密/解密（Fernet · 可选 / XOR fallback）"""

    def __init__(self, master_key: Optional[str] = None):
        """master_key 来自 QCM_SECRET_KEY 或随机生成"""
        self.master_key = master_key or os.environ.get("QCM_SECRET_KEY")
        self.fernet_available = False
        if self.master_key:
            try:
                from cryptography.fernet import Fernet
                import hashlib
                # 派生 32 字节 key
                key = base64.urlsafe_b64encode(
                    hashlib.sha256(self.master_key.encode()).digest()
                )
                self._fernet = Fernet(key)
                self.fernet_available = True
            except ImportError:
                self.fernet_available = False

    def encrypt(self, plaintext: str) -> str:
        """加密（Fernet 优先 / XOR fallback）"""
        if self.fernet_available:
            return self._fernet.encrypt(plaintext.encode()).decode()
        return self._xor_encrypt(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        """解密"""
        if self.fernet_available and ciphertext.startswith("gAAAAA"):
            return self._fernet.decrypt(ciphertext.encode()).decode()
        return self._xor_decrypt(ciphertext)

    def _xor_encrypt(self, plaintext: str) -> str:
        """XOR 加密（fallback · 不安全但可用）"""
        if not self.master_key:
            return plaintext
        key_bytes = self.master_key.encode()
        pt_bytes = plaintext.encode()
        ct_bytes = bytes([pt_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(pt_bytes))])
        return "xor:" + base64.urlsafe_b64encode(ct_bytes).decode()

    def _xor_decrypt(self, ciphertext: str) -> str:
        """XOR 解密"""
        if ciphertext.startswith("xor:"):
            ct_bytes = base64.urlsafe_b64decode(ciphertext[4:])
            key_bytes = self.master_key.encode() if self.master_key else b""
            return bytes([ct_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(ct_bytes))]).decode()
        return ciphertext


if __name__ == "__main__":
    # Demo
    auth = AuthManager()

    # OAuth client_credentials
    print("=== OAuth client_credentials ===")
    result = auth.client_credentials(
        "default-client", "default-secret",
        scope=["tools/call", "tools/list"]
    )
    print(f"  access_token: {result.get('access_token', '?')[:60]}...")
    print(f"  expires_in: {result.get('expires_in')}")
    print(f"  scope: {result.get('scope')}")

    # 验证 token
    print("\n=== Token 验证 ===")
    payload = auth.verify(result["access_token"])
    if payload:
        print(f"  sub: {payload['sub']}")
        print(f"  scope: {payload['scope']}")
        print(f"  exp: {payload['exp']}")
    else:
        print("  ❌ invalid token")

    # RBAC
    print("\n=== RBAC 检查 ===")
    print(f"  tools/call scope: {auth.check_scope(payload, 'tools/call')}")
    print(f"  admin scope: {auth.check_scope(payload, 'admin')}")

    # Secret 加密
    print("\n=== Secret 加密 ===")
    cipher = SecretCipher("test-master-key")
    plaintext = "sk-TEST-FIXTURE-not-a-real-key"
    encrypted = cipher.encrypt(plaintext)
    print(f"  原文: {plaintext}")
    print(f"  密文: {encrypted[:60]}...")
    decrypted = cipher.decrypt(encrypted)
    print(f"  解密: {decrypted}")
    print(f"  一致: {plaintext == decrypted}")