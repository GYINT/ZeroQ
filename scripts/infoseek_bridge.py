#!/usr/bin/env python3
"""qcm_infoseek_bridge.py — QCM × Infoseek 归因桥接层（§8.5 降级协议）

核心原则：Infoseek 是 optional 依赖。未安装/不可用时逐级降级：
  L0_infoseek → L1_local → L2_web → L3_protocol

降级链（§8.5.1）：
  QCM 归因触发（5 维 ≥2 失败）
    ↓
  [L0] Infoseek 可用？→ research_v3（完整多源归因）
    ↓ NO
  [L1] 本地 corpus 检索（≥2 相关源 → [local-only]）
    ↓ NO
  [L2] Web/LLM 补充（→ [unverified]）
    ↓ NO
  [L3] 纯协议推理（→ [unverified][no-external-source] + gap_tracker.md 记录）

安全：不硬编码任何 API key · 探测超时 3s · 结果缓存 30min
"""
import os
import json
import sys
import time
import uuid
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
# ============ · OAuth 客户端（跨设备 JWT）============
class OAuthClient:
    """QCM 端 OAuth 2.0 client_credentials 客户端

    - 自动获取 access_token（POST /oauth/token）
    - 缓存 token（TTL 内复用）
    - 过期自动刷新
    - 跨设备：每设备独立 client_id/secret → 独立 JWT

    用法：
        client = OAuthClient("https://infoseek.example.com", "device-a", "secret-a")
        token = client.get_token() # 自动签发/缓存/刷新
    """

    def __init__(self, base_url: str, client_id: str, client_secret: str,
                 token_ttl_buffer: int = 60):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_ttl_buffer = token_ttl_buffer  # 提前 60s 刷新
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._last_refresh: float = 0.0

    def get_token(self, force: bool = False) -> str:
        """获取有效 token（缓存命中 / 过期刷新）"""
        import time as _time
        now = _time.time()
        if (not force and self._token
                and self._expires_at > now + self.token_ttl_buffer):
            return self._token
        return self._refresh()

    def _refresh(self) -> str:
        """调用 /oauth/token 获取新 token"""
        import time as _time
        import urllib.request
        import urllib.parse

        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "tools/call resources/read",
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/oauth/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"OAuth token 获取失败: {e}")

        if "error" in body:
            raise RuntimeError(f"OAuth 拒绝: {body.get('error')} {body.get('error_description', '')}")

        self._token = body.get("access_token", "")
        self._expires_at = _time.time() + body.get("expires_in", 3600)
        self._last_refresh = _time.time()
        return self._token

    @property
    def is_authenticated(self) -> bool:
        """是否已获取过 token"""
        return self._token is not None

    def auth_header(self) -> Dict[str, str]:
        """生成 Authorization 头"""
        return {"Authorization": f"Bearer {self.get_token()}"}


def _oauth_client_from_env() -> Optional[OAuthClient]:
    """从环境变量创建 OAuthClient（跨设备部署）

    env:
        INFOSEEK_REMOTE_URL     远程 Infoseek 地址
        INFOSEEK_CLIENT_ID      设备 client_id
        INFOSEEK_CLIENT_SECRET 设备 client_secret
    """
    url = os.environ.get("INFOSEEK_REMOTE_URL", "")
    cid = os.environ.get("INFOSEEK_CLIENT_ID", "")
    csec = os.environ.get("INFOSEEK_CLIENT_SECRET", "")
    if url and cid and csec:
        return OAuthClient(url, cid, csec)
    return None


# ============ 配置 ============
from paths import ROOT as QCM_ROOT
REFERENCES = os.path.join(QCM_ROOT, "references")
from registry import find_skill
_INFOSEEK_ROOT = find_skill("infoseek")
INFOSEEK_ROOT = str(_INFOSEEK_ROOT) if _INFOSEEK_ROOT else os.environ.get("INFOSEEK_ROOT", "")
INFOSEEK_SERVER = os.path.join(INFOSEEK_ROOT, "scripts", "infoseek_mcp_server.py") if INFOSEEK_ROOT else ""

# 探测缓存（30 分钟）
_probe_cache: Dict[str, Any] = {"status": None, "ts": 0.0}
_PROBE_TTL = 30 * 60
_PROBE_TIMEOUT = 3

# 降级标注
DEGRADATION_LABELS = {
    "L0_infoseek": "",
    "L1_local": "[local-only]",
    "L2_web": "[unverified]",
    "L3_protocol": "[unverified][no-external-source]",
}

DEGRADATION_WARNINGS = {
    "L1_local": "Infoseek 未安装，归因基于 QCM 本地 corpus（未经过多源交叉验证）",
    "L2_web": "Infoseek 未安装，结果含 Web/LLM 补充（未经过多源交叉验证）",
    "L3_protocol": "Infoseek 未安装且无外部数据源，建议安装 Infoseek 后执行 M4 批量回源",
}


# ============ L0 探测 ============
def probe_infoseek(force: bool = False) -> str:
    """探测 Infoseek 是否可用（带 30 分钟缓存）

    Returns:
        "available" / "not_installed" / "timeout"
    """
    global _probe_cache
    now = time.time()
    if (not force and _probe_cache["status"]
            and _probe_cache["server"] == INFOSEEK_SERVER
            and (now - _probe_cache["ts"]) < _PROBE_TTL):
        return _probe_cache["status"]

    # 文件存在性检查
    if not os.path.exists(INFOSEEK_SERVER):
        status = "not_installed"
    else:
        try:
            result = subprocess.run(
                [sys.executable, INFOSEEK_SERVER, "--list-tools"],
                timeout=_PROBE_TIMEOUT,
                capture_output=True,
                text=True,
            )
            status = "available" if result.returncode == 0 else "not_installed"
        except subprocess.TimeoutExpired:
            status = "timeout"
        except Exception:
            status = "timeout"

    _probe_cache = {"server": INFOSEEK_SERVER, "status": status, "ts": now}
    return status


def clear_probe_cache() -> None:
    """清空探测缓存（测试用）"""
    global _probe_cache
    _probe_cache = {"server": None, "status": None, "ts": 0.0}


# ============ L0 · Infoseek research_v3 调用 ============
def _infoseek_tool_call(tool_name: str, arguments: Dict[str, Any],
                            timeout_s: int = 60) -> Dict[str, Any]:
    """通用 stdio subprocess 调用 Infoseek MCP 工具（§8.3）"""
    request = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    proc = subprocess.Popen(
        [sys.executable, INFOSEEK_SERVER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        proc.stdin.close()
        response = proc.stdout.readline().strip()
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"Infoseek {tool_name} timeout ({timeout_s}s)")
    finally:
        if proc.poll() is None:
            proc.kill()

    if not response:
        raise RuntimeError("Infoseek no response (empty stdout)")

    parsed = json.loads(response)
    if "error" in parsed:
        raise RuntimeError(f"Infoseek error: {parsed['error']}")

    # 展开 MCP content[0].text
    result = parsed.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list):
        try:
            return json.loads(content[0]["text"])
        except (KeyError, IndexError, json.JSONDecodeError):
            pass
    return result


def _infoseek_research(query: str, sources: Optional[List[Dict]] = None,
                       domain: Optional[str] = None) -> Dict[str, Any]:
    """调用 Infoseek research_v3 工具（§8.3 · 通过通用调用器）"""
    return _infoseek_tool_call("research_v3", {
        "subject": query,
        "sources": sources or [],
        "domain": domain or "",
        "output_format": "json",
        "lite": True,
    })


# ============ · Phase 1/3 专用调用 ============
def _infoseek_search_anchors(subject: str, depth: int = 1,
                             max_results: int = 5) -> List[Dict]:
    """Phase 1 · 调用 Infoseek search_anchors（锚点发现 · 深度 1）

    Infoseek search_anchors 是评分/路由框架：真实搜索需外部 web search。
    返回渠道列表（sources）作为候选源补充，评分由 Infoseek 完成。
    """
    try:
        result = _infoseek_tool_call("search_anchors", {
            "subject": subject, "depth": depth,
        }, timeout_s=30)
        anchors = []
        if isinstance(result, list):
            anchors = result
        elif isinstance(result, dict):
            anchors = result.get("anchors") or result.get("results") or []
            if not anchors and result.get("sources"):
                # 渠道框架返回：sources 是渠道列表 → 转候选源
                anchors = [{
                    "source": f"channel://{c}",
                    "title": f"渠道 {c}（锚点框架）",
                    "snippet": result.get("message", ""),
                    "hit_count": 1,
                    "channel": c,
                } for c in result["sources"]]
        return anchors[:max_results] if isinstance(anchors, list) else []
    except Exception:
        return []


def _infoseek_research_stream(subject: str, depth: int = 3) -> Dict[str, Any]:
    """Phase 3 · 调用 Infoseek research_stream（流式研究 · 7 步 yield）"""
    try:
        result = _infoseek_tool_call("research_stream", {
            "subject": subject,
            "output_format": "json",
            "lite": False,
        }, timeout_s=120)
        # v3.0.0 GA：返回 list（7 步 yield 元素）
        if isinstance(result, list):
            steps = [item.get("step", "") for item in result if isinstance(item, dict)]
            report_item = {}
            for item in result:
                if isinstance(item, dict) and item.get("step") == "report_complete":
                    report_item = item
            return {
                "steps": steps,
                "step_count": len(steps),
                "report": report_item,
                "sources": [],
                "raw": result,
            }
        # dict 兼容（旧格式）
        steps = []
        for key in ["score_complete", "wikidata_complete", "entity_graph_complete",
                    "conflict_complete", "profile_complete", "trajectory_complete",
                    "report_complete"]:
            if key in result:
                steps.append(key)
        return {
            "steps": steps,
            "step_count": len(steps),
            "report": result.get("report") or result.get("report_complete") or {},
            "sources": result.get("sources", []),
            "raw": result,
        }
    except Exception as e:
        raise RuntimeError(f"research_stream failed: {e}")


# ============ V8.4 A3/A4 · 实时层桥接（NER + 矛盾 · 直接 import · 双路径） ============
def _probe_infoseek_path() -> Optional[str]:
    """返回 Infoseek 安装路径（用于直接 import core.ner / core.conflict_v2）"""
    if INFOSEEK_ROOT and os.path.isdir(INFOSEEK_ROOT):
        return INFOSEEK_ROOT
    try:
        p = find_skill("infoseek")
        if p and os.path.isdir(str(p)):
            return str(p)
    except Exception:
        pass
    return None


def qcm_ner_extract(text: str, entity_types: Optional[list] = None) -> List[Dict]:
    """A3 NER 桥接：实体识别入归因（实时层 · 双源合并去重）

    路径 A：Infoseek core/ner.extract_entities（95+ 实体词典 · 直接 import 快于 subprocess）
    路径 B：QCM entities.yaml 匹配（40 实体 · Infoseek 缺失时独立可用）
    输出：合并去重实体列表 [{name, type, source}]
    """
    results: List[Dict] = []
    seen = set()

    # 路径 A · Infoseek NER
    inf = _probe_infoseek_path()
    if inf:
        try:
            sys.path.insert(0, inf)
            from core.ner import extract_entities as _ner
            for e in _ner(text, entity_types) or []:
                name = str(e.get("entity_name") or e.get("name") or "").strip()
                if not name or name.lower() in seen:
                    continue
                seen.add(name.lower())
                results.append({
                    "name": name, "type": str(e.get("entity_type") or "entity"),
                    "source": "infoseek_ner", "matched_alias": e.get("matched_alias", ""),
                })
        except Exception:
            pass  # Infoseek NER 失败 → 仅 QCM 本地（B 路径）

    # 路径 B · QCM entities.yaml（独立兜底 + 双源合并）
    try:
        from router import match_entities
        for e in match_entities(text):
            name = e.get("name", "")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            results.append({"name": name, "type": e.get("type", "entity"),
                            "source": "qcm_entities"})
    except Exception:
        pass

    return results


def qcm_conflict_check(sources: List[Dict], subject: str = "") -> List[Dict]:
    """A4 矛盾联动桥接：调研矛盾 → 词源冲突候选（实时层）

    路径 A：Infoseek core.conflict_v2.detect_conflicts_v2（共享事实槽+否定词典+极性放大）
            输入契约：sources=[{text/snippet, ...}] · 返回 Dict{conflicts, entity_conflicts}
    路径 B：Infoseek 缺失 → 返回空（词源冲突由 semantic_audit 规则检测独立覆盖）
    输出：冲突对列表 [{pair, type, confidence, suggestion}]（对齐 semantic_audit 格式）
    """
    inf = _probe_infoseek_path()
    if not inf or not sources:
        return []
    try:
        sys.path.insert(0, inf)
        # V8.4 A4 修复：conflict_v2 已弃用（Infoseek DeprecationWarning）→ 改用 conflict_v3 主入口
        from core.conflict_v3 import detect_conflicts_v3
        result = detect_conflicts_v3(sources, subject=subject)
        if not isinstance(result, dict):
            return []
        # conflicts（跨会话/最终）+ live_alerts（实时同实体异源矛盾）
        conflicts = list(result.get("conflicts") or []) + list(result.get("live_alerts") or [])
        out = []
        for c in conflicts:
            if "source_a" in c:  # live_alert 结构
                out.append({
                    "pair": (str(c.get("source_a") or "")[:30], str(c.get("source_b") or "")[:30]),
                    "type": "调研矛盾",
                    "confidence": 0.75,
                    "entity": str(c.get("entity_name") or ""),
                    "suggestion": f"同一实体 {c.get('entity_name')} 在不同源表述矛盾 · 置信度≥70 才可入库（§8.4）",
                })
                continue
            a = str(c.get("claim_a") or c.get("a") or c.get("entity") or c.get("source") or "")
            b = str(c.get("claim_b") or c.get("b") or c.get("value_a") or c.get("value_b") or "")
            if not a and not b:
                continue
            pair = (a[:30], b[:30]) if a and b else (a or b, "")
            out.append({
                "pair": pair,
                "type": "调研矛盾",
                "confidence": min(float(c.get("conflict_score") or c.get("confidence") or 0.7), 0.99),
                "suggestion": "调研结果语义矛盾 · 置信度≥70 才可入库（§8.4）",
            })
        return out
    except Exception:
        return []  # Infoseek 矛盾检测失败 → B 路径（semantic_audit 规则）


# ============ L2a · AI 搜索（Infoseek 主路 + 直连兜底 · V8.4） ============
def _web_search_infoseek(query: str, max_results: int = 5) -> Optional[List[Dict]]:
    """L2a 主路 · 复用 Infoseek search_web（5 引擎成熟链 · 并行+降级）

    Infoseek 可用时优先（零重复建设）；返回真实联网锚点 [{url,title,snippet}]。

    可用性信号与 L0 探测统一（probe_infoseek），避免两套发现路径分叉：
    INFOSEEK_SERVER 不可达时 L0/L2a 同时失效，保证降级链（L0→L1→L2→L3）一致。
    """
    if probe_infoseek() != "available":
        return None
    inf = _probe_infoseek_path()
    if not inf:
        return None
    try:
        sys.path.insert(0, os.path.join(inf, "scripts"))
        from infoseek_pipeline import search_web
        hits = search_web(query, max_results=max_results) or []
        if not hits:
            return None
        return [{
            "source": h.get("url", "infoseek-search://"),
            "title": h.get("title", query)[:60],
            "snippet": h.get("snippet", "")[:200],
            "hit_count": 1,
            "unverified": True,
            "web": True,
        } for h in hits]
    except Exception:
        return None


def _web_search_fallback(query: str, max_results: int = 5) -> Optional[List[Dict]]:
    """L2a 兜底 · 直连 AI 搜索引擎（scripts/ai_search.py · 智谱/博查）

    返回真实联网锚点 [{url, title, snippet}] · 无 Key/失败 → None（降级 LLM 语义消解）
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ai_search import ai_search
        hits = ai_search(query, max_results=max_results)
        if not hits:
            return None
        return [{
            "source": h.get("url", "ai-search://"),
            "title": h.get("title", query)[:60],
            "snippet": h.get("snippet", "")[:200],
            "hit_count": 1,
            "unverified": True,
            "web": True,
        } for h in hits]
    except Exception:
        return None


# ============ L1 · 本地 corpus 检索 ============
def _search_local_corpus(query: str, max_results: int = 5) -> List[Dict]:
    """QCM references 关键词检索（中文滑窗 + 英文词 + 整句匹配）"""
    import re

    # 1. 提取中文连续串 + 英文词
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    english_words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", query)

    # 2. 中文长串滑窗生成候选关键词（2-4 字窗口）
    keywords = []
    for run in chinese_runs:
        if len(run) <= 4:
            keywords.append(run)
        else:
            # 4 字窗口滑动
            for i in range(len(run) - 3):
                keywords.append(run[i:i + 4])
            # 保留整句（长句也可能直接命中）
            keywords.append(run)
    keywords.extend(english_words)
    # 去重 + 去太短的
    keywords = list(dict.fromkeys(k for k in keywords if len(k) >= 2))[:15]

    if not keywords:
        return []

    results = []
    if not os.path.isdir(REFERENCES):
        return results

    # V8.3.2 修复：V8.3.1 目录重组后知识库移入 12 个子目录，顶层 os.listdir 永远 0 命中
    # → L1_local 降级不可达（全部误落 L3_protocol）。改用递归 rglob 扫描全部子目录。
    for fpath in sorted(Path(REFERENCES).rglob("*.md")):
        fname = fpath.name
        if ".deprecated" in fname:
            continue
        rel = fpath.relative_to(REFERENCES).as_posix()
        try:
            with open(fpath, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        hits = sum(1 for kw in keywords if kw in content)
        if hits > 0:
            results.append({
                "source": f"qcm://references/{rel}",
                "title": rel,
                "snippet": content[:200].replace("\n", " "),
                "hit_count": hits,
                "local": True,
            })
    results.sort(key=lambda r: r["hit_count"], reverse=True)
    return results[:max_results]


# ============ L2 · Web/LLM 语义消解 ============
def _web_llm_supplement(query: str, failure_dims: Optional[List[str]] = None) -> Optional[Dict]:
    """L2 降级 · 归因语义消解（V8.4 第 27 轮评估落地）

    相比旧版"通用知识补充"（1 个非结构化 snippet · conf 固定 50）：
      · prompt 注入 failure_dims → LLM 逐失败维度归因（维度对齐）
      · 输出 JSON 结构化 [{dimension, evidence, confidence, suggested_tool}]
      · 置信聚合 → conf 55-65（动态反映证据强度）

    无真实 LLM（无 Key）→ 返回 None → 落 L3（行为不变 · 零回归）
    """
    try:
        import sys
        import json
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from llm_router import LLMRouter

        dims = failure_dims or []
        dim_hint = "、".join(dims[:5]) if dims else "（未指定 · 请给出主要归因维度）"
        router = LLMRouter()
        result = router.call(
            prompt=(
                f"【归因语义消解 · L2 降级（未接入 Infoseek 多源调研）】\n"
                f"质量问题：{query}\n"
                f"失败归因维度：{dim_hint}\n"
                f"请逐维度分析可能根因与证据，严格输出 JSON 数组（不要其它文字）：\n"
                f'[{{"dimension": "维度名", "evidence": "根因/证据一句话", '
                f'"confidence": 0-1 数值, "suggested_tool": "建议工具或空"}}]'
            ),
            task="research",
            max_tokens=600,
        )
        if result.get("mode") != "real":
            return None  # 无真实 LLM → L3
        text = result.get("text", "")
        # 解析 JSON（容忍 ```json 包裹）
        import re
        m = re.search(r"\[.*\]", text, re.S)
        items = json.loads(m.group(0)) if m else []
        if not isinstance(items, list) or not items:
            # JSON 解析失败 → 降级旧行为（1 个 snippet 锚点）
            return {
                "source": "llm://semantic",
                "title": "LLM 语义补充（非结构化降级）",
                "snippet": text[:300],
                "hit_count": 1,
                "unverified": True,
            }
        # 维度锚点 + 置信聚合
        anchors = []
        conf_sum, conf_n = 0.0, 0
        for it in items[:5]:
            dim = str(it.get("dimension", "未知维度"))[:20]
            conf = min(max(float(it.get("confidence", 0.5)), 0), 1)
            conf_sum += conf
            conf_n += 1
            anchors.append({
                "source": f"llm://semantic/{dim}",
                "title": f"维度归因 · {dim}",
                "snippet": str(it.get("evidence", ""))[:150],
                "hit_count": 1,
                "unverified": True,
                "dimension": dim,
                "confidence": round(conf, 2),
                "suggested_tool": str(it.get("suggested_tool", "") or "")[:40],
            })
        avg_conf = (conf_sum / conf_n) if conf_n else 0.5
        return {
            "source": "llm://semantic",
            "title": f"LLM 归因语义消解（{len(anchors)} 维度）",
            "snippet": text[:200],
            "hit_count": len(anchors),
            "unverified": True,
            "anchors": anchors,
            "avg_confidence": round(avg_conf, 2),
        }
    except Exception:
        return None


# ============ L3 · 缺口记录 ============
def _append_gap_tracker(query: str, failure_dims: List[str], path: str) -> None:
    """写入 gap_tracker.md（status=pending_infoseek · 待 M4 批量回源）

    M1.3 修复：写入前按问题去重（与消费端 corpus_sync.gap_tracker_entries 同键：
    表格第 2 列问题字段）——同一缺口多次 L3 降级只保留首条，不再无限追加，
    根治 2026-08-18 08:30/08:34/08:38 式 98 行重复日志堆叠。
    """
    try:
        entry = (
            f"\n| {time.strftime('%Y-%m-%d %H:%M')} | {query[:40]} | "
            f"{','.join(failure_dims[:3])} | pending_infoseek | L3_protocol |\n"
        )
        header = "| 时间 | 缺口问题 | 失败维度 | 状态 | 降级路径 |\n|------|----------|----------|------|----------|\n"
        if os.path.exists(path):
            content = open(path, encoding="utf-8").read()
            # M1.3 去重：同问题（第 2 列）已有记录 → 跳过（更新时间为首条时间，保持稳定）
            for line in content.splitlines():
                if "pending_infoseek" in line and line.strip().startswith("|"):
                    cells = [c.strip() for c in line.strip().strip("|").split("|")]
                    if len(cells) >= 3 and cells[1] == query[:40]:
                        return  # 已登记同一缺口，不重复追加
            with open(path, "a", encoding="utf-8") as f:
                # 若无表头则补表头
                if "| 时间 |" not in content:
                    f.write("\n" + header)
                f.write(entry)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# QCM 缺口追踪（gap_tracker）\n\n" + header + entry)
    except Exception:
        pass  # 缺口记录失败不影响归因主流程


# ============ 响应构造（统一契约） ============
def _build_response(query: str, anchors: List[Dict], status: str,
                    degradation_path: str, failure_dims: List[str],
                    suggested_tools: Optional[List[str]] = None) -> Dict[str, Any]:
    """构造统一 output_schema（§8.2 + §8.5.3）· V8.4 L2 置信动态化"""
    confidence = 30
    if degradation_path == "L0_infoseek":
        confidence = 85
    elif degradation_path == "L1_local":
        confidence = 65
    elif degradation_path == "L2_web":
        # V8.4 第 27 轮：L2 语义消解后按维度锚点置信聚合（55-65 动态）
        confidence = 50
        confs = [a.get("confidence", 0) for a in anchors
                 if isinstance(a, dict) and isinstance(a.get("confidence"), (int, float))]
        if confs:
            avg = sum(confs) / len(confs)
            confidence = min(65, 50 + round(avg * 15))  # avg 0.33→55 · avg 1.0→65
        elif any(isinstance(a, dict) and a.get("hit_count", 0) > 1 for a in anchors):
            confidence = 55  # 多锚点语义消解但无逐维置信 → 温和提升

    return {
        "attribution_id": uuid.uuid4().hex[:12],
        "anchors": anchors,
        "confidence_score": confidence,
        "matched_qcm_form": "quick_response" if confidence < 70 else "case_application",
        "infoseek_status": status,
        "degradation_path": degradation_path,
        "warning": DEGRADATION_WARNINGS.get(degradation_path, ""),
        "label": DEGRADATION_LABELS.get(degradation_path, ""),
        "suggested_tools": suggested_tools or [],
        "qcm_ingestion_plan": {
            "level": "main" if confidence >= 70 else ("history" if confidence >= 40 else "terminate"),
            "manual_review": confidence < 70,
        },
    }


# ============ · 3 阶段混合策略（§13.3）============
def qcm_attribution_phase(unparsed_query: str,
                          qcm_failure_dimensions: List[str],
                          phase: Optional[int] = None,
                          user_explicit: bool = False,
                          industry_hint: Optional[str] = None) -> Dict[str, Any]:
    """§13.3 混合策略 3 阶段触发

    Phase 1 · 自动浅层调研（缺口出现 → 立即触发 · 深度 1 · ~3000 Token）
    Phase 2 · 关键缺口中层调研（关键缺口 → 自动触发 · 深度 2 · ~2500 Token）
    Phase 3 · 用户显式深度调研（"展开 D"/"深度调研" · 深度 3 · streaming · ~2500 Token）
    """
    failed = [d for d in qcm_failure_dimensions if d and d != "ok"]

    # 自动判断 phase（若未指定）
    if phase is None:
        critical_count = sum(1 for d in qcm_failure_dimensions
                             if isinstance(d, dict) and d.get("severity") == "critical")
        if critical_count >= 2 or user_explicit:
            phase = 3
        elif critical_count >= 1 or len(failed) >= 3:
            phase = 2
        else:
            phase = 1

    # Phase 1 · 浅层锚点发现
    if phase == 1:
        anchors = _infoseek_search_anchors(unparsed_query, depth=1)
        return {
            "phase": 1,
            "matched_qcm_form": "quick_response",
            "anchors": anchors,
            "anchor_count": len(anchors),
            "token_estimate": 3000,
            "degradation_path": "L0_infoseek" if anchors else "L1_local",
            "infoseek_status": probe_infoseek(),
            "warning": "" if anchors else DEGRADATION_WARNINGS["L1_local"],
        }

    # Phase 2 · 中层 research_v3
    elif phase == 2:
        try:
            result = _infoseek_research(unparsed_query)
            anchors = result.get("sources", []) or result.get("anchors", [])
            confidence = result.get("confidence", 70)
            return {
                "phase": 2,
                "matched_qcm_form": "case_application" if confidence >= 70 else "quick_response",
                "anchors": anchors,
                "confidence_score": confidence,
                "token_estimate": 2500,
                "degradation_path": "L0_infoseek",
                "infoseek_status": "available",
                "qcm_ingestion_plan": {
                    "level": "main" if confidence >= 70 else "history",
                    "manual_review": confidence < 70,
                },
            }
        except Exception as e:
            # Infoseek 不可用 → §8.5 降级
            local = _search_local_corpus(unparsed_query)
            path = "L1_local" if len(local) >= 2 else "L3_protocol"
            return {
                "phase": 2,
                "matched_qcm_form": "quick_response",
                "anchors": local,
                "confidence_score": 65 if path == "L1_local" else 30,
                "token_estimate": 2500,
                "degradation_path": path,
                "infoseek_status": "not_installed",
                "warning": DEGRADATION_WARNINGS.get(path, ""),
            }

    # Phase 3 · 深度流式研究
    elif phase == 3:
        try:
            result = _infoseek_research_stream(unparsed_query)
            return {
                "phase": 3,
                "matched_qcm_form": "assessment_report",
                "streaming": True,
                "steps": result["steps"],
                "step_count": result["step_count"],
                "report": str(result["report"])[:500],
                "token_estimate": 2500,
                "degradation_path": "L0_infoseek",
                "infoseek_status": "available",
            }
        except Exception as e:
            local = _search_local_corpus(unparsed_query)
            return {
                "phase": 3,
                "matched_qcm_form": "assessment_report",
                "streaming": False,
                "steps": [],
                "step_count": 0,
                "error": str(e)[:100],
                "anchors": local,
                "token_estimate": 2500,
                "degradation_path": "L3_protocol" if len(local) < 2 else "L1_local",
                "infoseek_status": "not_installed",
                "warning": DEGRADATION_WARNINGS["L3_protocol"],
            }

    return {"phase": 0, "error": "invalid phase"}


# ============ 主入口：qcm_attribution ============
def qcm_attribution(unparsed_query: str,
                    qcm_failure_dimensions: List[str],
                    industry_hint: Optional[str] = None,
                    mds_fields: Optional[Dict] = None) -> Dict[str, Any]:
    """§8 QCM-Infoseek 归因协议 + §8.5 三级降级

    Args:
        unparsed_query: 用户原始问题
        qcm_failure_dimensions: 5 维触发信号（行业/危机类型/工具/标准/大师），'ok' 或失败描述
        industry_hint: 行业提示（可选）
        mds_fields: MDS 输入字段（可选）

    Returns:
        §8.2 output_schema（含 §8.5.3 扩展字段）
    """
    # 触发条件：5 维 ≥2 失败
    failed = [d for d in qcm_failure_dimensions if d and d != "ok"]
    if len(failed) < 2:
        return {
            "attribution_id": uuid.uuid4().hex[:12],
            "anchors": [],
            "confidence_score": 50,
            "matched_qcm_form": "quick_response",
            "infoseek_status": "not_triggered",
            "degradation_path": "L0_infoseek",
            "warning": "未触发归因（5 维失败 <2）",
            "label": "",
            "suggested_tools": [],
            "qcm_ingestion_plan": {"level": "terminate", "manual_review": False},
        }

    # L0: Infoseek 可用探测
    status = probe_infoseek()
    if status == "available":
        try:
            result = _infoseek_research(unparsed_query)
            anchors = result.get("sources", []) or result.get("anchors", [])
            if not anchors and result.get("report"):
                anchors = [{
                    "source": "infoseek://research_v3",
                    "title": "Infoseek 调研报告",
                    "snippet": result.get("report", "")[:300],
                    "hit_count": 1,
                }]
            return _build_response(unparsed_query, anchors, status="available",
                                   degradation_path="L0_infoseek",
                                   failure_dims=failed)
        except Exception as e:
            # Infoseek 调用失败 → 降级
            status = "partial"

    # L1: 本地 corpus 检索
    local = _search_local_corpus(unparsed_query)
    if len(local) >= 2:
        return _build_response(unparsed_query, local, status=status,
                               degradation_path="L1_local",
                               failure_dims=failed)

    # L2: Web/LLM 语义消解（V8.4：注入 failure_dims · 维度锚点展开）
    # L2a: AI 搜索双通道（Infoseek search_web 主路 → ai_search 直连兜底 · 引用可核验）
    web = _web_search_infoseek(unparsed_query, max_results=5) or _web_search_fallback(unparsed_query, max_results=5)
    if web:
        anchors = local + web
        return _build_response(unparsed_query, anchors, status=status,
                               degradation_path="L2_web",
                               failure_dims=failed)
    # L2b: LLM 语义消解（DeepSeek Key · 维度锚点）
    web = _web_llm_supplement(unparsed_query, failed)
    if web:
        sub = web.get("anchors") or [web]  # 结构化 → 维度锚点列表；降级 → 单锚点
        anchors = local + sub
        return _build_response(unparsed_query, anchors, status=status,
                               degradation_path="L2_web",
                               failure_dims=failed)

    # L3: 纯协议推理 + 缺口记录
    gap_path = os.path.join(REFERENCES, "gap_tracker.md")
    _append_gap_tracker(unparsed_query, failed, gap_path)
    return _build_response(unparsed_query, local, status=status,
                           degradation_path="L3_protocol",
                           failure_dims=failed)



# ============ · 远程调用（HTTP transport + Bearer JWT）============
def _remote_tool_call(tool_name: str, arguments: Dict[str, Any],
                      timeout_s: int = 60) -> Dict[str, Any]:
    """通过 HTTP 调用远程 Infoseek（跨设备 · OAuth JWT）

    env:
        INFOSEEK_REMOTE_URL      远程地址（如 https://infoseek.example.com）
        INFOSEEK_CLIENT_ID       设备 client_id
        INFOSEEK_CLIENT_SECRET   设备 client_secret
        INFOSEEK_REQUIRE_AUTH    1=强制 OAuth（默认 1）
    """
    import urllib.request
    import urllib.error

    client = _oauth_client_from_env()
    if client is None:
        raise RuntimeError("远程调用需要 INFOSEEK_REMOTE_URL + CLIENT_ID + CLIENT_SECRET")

    request = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {"Content-Type": "application/json"}
    headers.update(client.auth_header())  # Bearer JWT

    req = urllib.request.Request(
        f"{client.base_url}/rpc",
        data=json.dumps(request, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 401:
            raise RuntimeError(f"远程认证失败 (401): {body[:200]}")
        if e.code == 403:
            raise RuntimeError(f"远程 RBAC 拒绝 (403): {body[:200]}")
        raise RuntimeError(f"远程调用失败 ({e.code}): {body[:200]}")
    except Exception as e:
        raise RuntimeError(f"远程连接失败: {e}")

    if "error" in parsed:
        raise RuntimeError(f"远程工具错误: {parsed['error']}")

    result = parsed.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list):
        try:
            return json.loads(content[0]["text"])
        except (KeyError, IndexError, json.JSONDecodeError):
            pass
    return result


def infoseek_call(tool_name: str, arguments: Dict[str, Any],
                  timeout_s: int = 60) -> Dict[str, Any]:
    """统一入口：本地 stdio → 远程 HTTP（自动选择 transport）

    - 本地已装 Infoseek → stdio subprocess
    - 配置了远程地址 → HTTP + OAuth JWT
    - 都不可用 → 抛异常（调用方降级）
    """
    if os.path.exists(INFOSEEK_SERVER):
        return _infoseek_tool_call(tool_name, arguments, timeout_s)
    if os.environ.get("INFOSEEK_REMOTE_URL"):
        return _remote_tool_call(tool_name, arguments, timeout_s)
    raise RuntimeError("Infoseek 不可用（本地未安装且未配置远程）")


def qcm_attribution_remote(unparsed_query: str,
                           qcm_failure_dimensions: List[str],
                           industry_hint: Optional[str] = None) -> Dict[str, Any]:
    """跨设备归因：通过远程 Infoseek 执行 research_v3"""
    try:
        result = infoseek_call("research_v3", {
            "subject": unparsed_query,
            "output_format": "json",
            "lite": True,
        })
        anchors = result.get("sources", []) or result.get("anchors", [])
        return _build_response(unparsed_query, anchors, status="available",
                               degradation_path="L0_infoseek",
                               failure_dims=[d for d in qcm_failure_dimensions if d != "ok"])
    except RuntimeError as e:
        # 远程失败 → 降级
        local = _search_local_corpus(unparsed_query)
        path = "L1_local" if len(local) >= 2 else "L3_protocol"
        return _build_response(unparsed_query, local, status="timeout",
                               degradation_path=path,
                               failure_dims=[d for d in qcm_failure_dimensions if d != "ok"])


if __name__ == "__main__":
    # CLI 调试入口
    import sys
    query = sys.argv[1] if len(sys.argv) > 1 else "焊接虚焊客诉复发"
    dims = sys.argv[2].split(",") if len(sys.argv) > 2 else ["ok", "ok", "ok", "ok", "工具缺失"]
    print(json.dumps(qcm_attribution(query, dims), ensure_ascii=False, indent=2))
