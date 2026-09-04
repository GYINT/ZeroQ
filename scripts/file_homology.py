#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QCM 同源文件归一化守卫（M3 · g020_file_homology）

目标：对 references/**/*.md 做同源指纹聚类，标记"疑似同根未互链"——
  即两份文档语义高度相似（标题/首段/锚点重叠），但彼此未交叉引用。
  这是评估 H1 缺口的落地：文件/资料层此前无自动同源检测（仅靠人工 SOLE 纪律）。

机制：
  ① 指纹：标题集合 Jaccard（文件名 stem 拆词 + H1/H2 标题） + 首段重叠 +
          锚点标题 Jaccard。加权相似度 ∈ [0,1]。
  ② 动态阈值：默认 BASE=0.6（M0.5 决策）；从 ref_heat.confirmed_pairs 读取
              已确认同根对 → 对(A,B)类降权（不再误报"未互链"）；下限 MIN=0.45
              （防止过度降权漏检）。report-only：不写 yaml。
  ③ 交叉引用检测：若 A 正文含 B 的文件名/stem 且 B 含 A → 已互链，跳过告警。
  ④ 失败安全：任何异常返回空结果（守卫不静默吞错，由 config_sync 外层 report）。

消费方：config_sync._check_file_homology()（输出 [同源文件⑳] 前缀）；
        guardian.yaml 注册 g020_file_homology。
"""
import os
import re
import sys
import json
import time
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Tuple, Set

ROOT = Path(__file__).resolve().parent.parent
REF_DIR = ROOT / "references"
RUNTIME_DIR = ROOT / "outputs" / ".runtime"
REF_HEAT_PATH = RUNTIME_DIR / "ref_heat.json"
UNION_PATH = RUNTIME_DIR / "homology_union.json"   # 双算法并集持久化（M-T2 · 夜巡文本词面拉取交并）

# ── 中文分词分级降级链依赖探测（懒加载，失败安全）────────────
# ① jieba 主路径：**优先本地 import jieba**（最快、零进程开销；jieba 若已随环境安装）
# ② jieba via MCP：本地 jieba 不可用时，通过 MCP 调 Infoseek 端 summarize_content(prefer="jieba")
# ③ zerodep 兜底：**QCM 本地 vendored 副本** scripts/infoseek_zerodep_nlp.py
#   （纯标准库零依赖，已随 QCM 发行，不依赖 infoseek 是否安装/跨平台）
# ④ 旧 regex 极端兜底：整句成词（保持旧行为不崩）
_INFOSEEK_ROOT = os.environ.get(
    "INFOSEEK_ROOT",
    str(ROOT.parent / "infoseek") if (ROOT.parent / "infoseek").exists() else "",
)
# vendored zerodep 副本：优先 QCM 本地（scripts/），回退 infoseek 同级
_LOCAL_ZERODEP = ROOT / "scripts" / "infoseek_zerodep_nlp.py"
_ZERODEP = None          # 懒加载的 infoseek_zerodep_nlp 模块
_ZERODEP_OK = False
_JIEBA = None            # 懒加载的本地 jieba 模块（优先主路径）
_JIEBA_OK = False
_MCP_CLIENT = None       # 长驻 Infoseek MCP 连接（复用作 jieba 次级路径）
_MCP_OK = False
# 双算法并集：cut=逐词切分（词面全覆盖 · CI 高频通道） / textrank=关键词 topK（主题集中 · 夜巡低频通道）
ALGOS = ("cut", "textrank")
DEFAULT_ALGO = os.environ.get("QCM_HOMOLOGY_ALGO", "cut")
TEXTRANK_TOPK = int(os.environ.get("QCM_HOMOLOGY_TEXTRANK_TOPK", 40))

# 短路开关（等效"模型断路器短路"）：环境已知无模型后端（ollama/lm_studio 不可达）时，
# 跳过 MCP 分词路径（避免无意义的 30s 模型调用超时等待与子进程拉起开销），直接走
# zerodep/regex 兜底。env 可控、可回滚（不设即恢复 MCP 路径，由 _recv 超时兜底保护）。
SKIP_MCP = os.environ.get("QCM_HOMOLOGY_SKIP_MCP", "").strip().lower() in ("1", "true", "yes", "on")


def _ensure_zerodep():
    """懒加载 zerodep 兜底模块（QCM 本地 vendored 副本优先，零依赖中文分词）。

    优先从 `scripts/infoseek_zerodep_nlp.py`（随 QCM 发行）加载，
    保证跨平台、infoseek 未安装时 zerodep 兜底依然可用。
    仅当本地副本缺失时才回退 `../infoseek` 同级目录。
    """
    global _ZERODEP, _ZERODEP_OK
    if _ZERODEP_OK or _ZERODEP is not None:
        return _ZERODEP_OK
    candidates = []
    if _LOCAL_ZERODEP.exists():      # ① QCM 本地 vendored（首选）
        candidates.append(str(ROOT / "scripts"))
    if _INFOSEEK_ROOT:               # ② infoseek 同级（回退）
        candidates.append(os.path.join(_INFOSEEK_ROOT, "scripts"))
    for p in candidates:
        try:
            sys.path.insert(0, p)
            import infoseek_zerodep_nlp  # noqa: F401
            _ZERODEP = infoseek_zerodep_nlp
            _ZERODEP_OK = True
            return True
        except Exception:
            continue
    return False


class _InfoseekMCPClient:
    """轻量 Infoseek MCP stdio 客户端（单连接复用，满足「jieba 走 MCP 调 infoseek 端」）。

    每次实例化启动一个长驻 infoseek server 子进程，握手 initialize 后，
    可发多个 tools/call（同连接），结束时 close()。避免每请求新 spawn 子进程
    导致的 O(n) subprocess 爆炸与资源耗尽。
    """

    def __init__(self, timeout_s: int = 30):
        if not _INFOSEEK_ROOT:
            raise RuntimeError("INFOSEEK_ROOT 未设置且同级 infoseek 不存在")
        server = os.path.join(_INFOSEEK_ROOT, "scripts", "infoseek_mcp_server.py")
        if not os.path.exists(server):
            raise RuntimeError(f"Infoseek MCP server 不存在: {server}")
        self.proc = subprocess.Popen(
            [sys.executable, server, "--transport", "stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
        )
        self.timeout = timeout_s
        self._id = 0
        # 握手 initialize
        self._send({"jsonrpc": "2.0", "id": self._next_id(),
                    "method": "initialize", "params": {}})
        self._recv()  # 丢弃 initialize 响应

    def _next_id(self):
        self._id += 1
        return self._id

    def _send(self, msg: dict):
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _recv(self, timeout: float = None) -> dict:
        """带超时读取一行 JSON-RPC 响应。

        子进程（infoseek_mcp_server）因模型后端不可用可能永久阻塞其响应。
        Windows 下 Thread.join(timeout) 对阻塞在原生管道 IO 的线程不可靠，
        故改用「看门狗线程 + 进程终止」强制超时：看门狗在 timeout 后 terminate
        子进程，管道 EOF 使 readline 返回，主线程据此抛 TimeoutError，
        由上层（_ensure_mcp / _zh_tokens）捕获后优雅降级到 zerodep/regex，
        避免 config_sync --check 等调用方无限挂起。
        """
        timeout = timeout if timeout is not None else self.timeout
        timed_out = {"v": False}

        def _watchdog():
            time.sleep(timeout)
            timed_out["v"] = True
            try:
                self.proc.terminate()
            except Exception:
                pass

        threading.Thread(target=_watchdog, daemon=True).start()
        try:
            line = self.proc.stdout.readline()  # 阻塞；看门狗超时杀进程 → 管道 EOF
        except Exception:
            line = ""
        if timed_out["v"]:
            raise TimeoutError(
                f"Infoseek MCP 响应超时（>{timeout:.0f}s），已终止子进程并降级跳过")
        if not line or not line.strip():
            raise RuntimeError("Infoseek MCP 连接断开（空响应）")
        return json.loads(line)

    def call(self, tool: str, arguments: dict) -> dict:
        self._send({"jsonrpc": "2.0", "id": self._next_id(),
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments}})
        resp = self._recv()
        if "error" in resp:
            raise RuntimeError(f"Infoseek error: {resp['error']}")
        result = resp.get("result", {})
        content = result.get("content", [])
        if content and isinstance(content, list):
            try:
                return json.loads(content[0]["text"])
            except (KeyError, IndexError, json.JSONDecodeError):
                pass
        return result

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.terminate()
        except Exception:
            pass


def _ensure_jieba():
    """懒加载本地 jieba（优先主路径）。不可用（未安装/import 失败）返回 False。"""
    global _JIEBA, _JIEBA_OK
    if _JIEBA_OK or _JIEBA is not None:
        return _JIEBA_OK
    try:
        import jieba  # noqa: F401
        _JIEBA = jieba
        _JIEBA_OK = True
    except Exception:
        _JIEBA_OK = False
    return _JIEBA_OK


def _ensure_mcp():
    """懒启动长驻 Infoseek MCP 连接（单例）。"""
    global _MCP_CLIENT, _MCP_OK
    if SKIP_MCP:
        # 短路：已知无模型后端，直接降级（不 spawn server、不空等超时）
        return False
    if _MCP_OK or _MCP_CLIENT is not None:
        return _MCP_OK
    try:
        _MCP_CLIENT = _InfoseekMCPClient(timeout_s=30)
        _MCP_OK = True
    except Exception:
        _MCP_OK = False
    return _MCP_OK


def _zh_tokens(text: str) -> Set[str]:
    """中文文本 → 词集合（四级降级）。

    ① jieba 本地 import（优先主路径）：最快、零进程开销，jieba 已随环境安装即可用；
    ② jieba via MCP：本地 jieba 不可用时，MCP 调 Infoseek 端
       summarize_content(prefer="jieba")，取 keywords 列表（连接复用避免 subprocess 爆炸）；
    ③ zerodep 兜底：本地 vendored infoseek_zerodep_nlp.extract_keywords(lang="zh")
       （纯标准库 + 共识投票，抗通用词噪声）；
    ④ 旧 regex 极端兜底：空格/标点切词（整句成词，保持旧行为）。
    任一路径失败/不可用均静默降级，保证不崩。
    """
    # ① jieba 本地 import（优先）
    if _ensure_jieba():
        try:
            toks = {w for w in _JIEBA.cut(text) if len(w) > 1}
            if toks:
                return toks
        except Exception:
            pass  # 降级到 MCP / zerodep
    # ② jieba via MCP（Infoseek 端，连接复用）
    if _ensure_mcp():
        try:
            res = _MCP_CLIENT.call(
                "summarize_content",
                {"text": text, "prefer": "jieba", "max_words": 60},
            )
            kws = res.get("keywords") if isinstance(res, dict) else None
            if kws and isinstance(kws, list):
                toks = set(str(w).strip() for w in kws if str(w).strip())
                if toks:
                    return toks
        except Exception:
            global _MCP_OK
            _MCP_OK = False  # MCP 不可用（含超时）：永久降级，避免重复阻塞
            pass  # 降级到 zerodep
    # ③ zerodep 本地兜底
    if _ensure_zerodep():
        try:
            kws = _ZERODEP.extract_keywords(text, max_kw=30, lang="zh")
            if kws:
                return set(w for w, _ in kws)
        except Exception:
            pass
    # ④ 旧 regex 极端兜底
    return set(t for t in re.split(r"[\s/·\-]+", text.lower()) if len(t) > 1)


def _textrank_tokens(text: str) -> Set[str]:
    """textrank 关键词通道（M-T1 · 主题集中互补召回）。

    与 cut 通道互补：cut 覆盖词面全量（宽召回），textrank 聚焦主题核心词 topK
    （窄而准）——两者在同一文本上命中面不同，构成并集互补。
    降级链与 cut 相同（本地 jieba.analyse.textrank → zerodep → regex），失败安全。
    """
    if not text or not text.strip():
        return set()
    # ① 本地 jieba.analyse.textrank（主路径 · 与 MCP 端 textrank 同算法）
    if _ensure_jieba():
        try:
            import jieba.analyse  # noqa: F401
            kws = jieba.analyse.textrank(text, topK=TEXTRANK_TOPK)
            toks = {str(w).strip() for w in kws if str(w).strip()}
            if toks:
                return toks
        except Exception:
            pass  # 降级 zerodep
    # ② zerodep 兜底（无 jieba 环境 · 本地 vendored 副本）
    if _ensure_zerodep():
        try:
            kws = _ZERODEP.extract_keywords(text, max_kw=TEXTRANK_TOPK, lang="zh")
            if kws:
                return set(w for w, _ in kws)
        except Exception:
            pass
    # ③ regex 极端兜底（保持旧行为不崩）
    return set(t for t in re.split(r"[\s/·\-]+", text.lower()) if len(t) > 1)


BASE_THRESHOLD = float(os.environ.get("QCM_HOMOLOGY_BASE", 0.6))
MIN_THRESHOLD = float(os.environ.get("QCM_HOMOLOGY_MIN", 0.45))

# 排除：索引目录、运行态、archive（已废弃）、知识库本身不做同根（自身是聚合）
EXCLUDE_DIRS = {"index", ".runtime", "automation_log", "archive", "__pycache__",
                "industry"}  # industry/ 行业知识包：平级模板化条目（模板开头重叠），不互比同根
EXCLUDE_STEMS = {"knowledge-base"}  # 知识库是总纲，不与子文档互比同根


def _load_confirmed() -> Dict[str, float]:
    """从 ref_heat.confirmed_pairs 读取已确认同根相似度（M0.5 动态校准源）。"""
    try:
        if REF_HEAT_PATH.exists():
            d = json.loads(REF_HEAT_PATH.read_text(encoding="utf-8"))
            return d.get("confirmed_pairs", {})
    except Exception:
        pass
    return {}


def _stem_of(path: Path) -> str:
    return path.stem


def _title_tokens(stem: str) -> Set[str]:
    """文件名拆词（驼峰/连字符/下划线）。"""
    s = stem.replace("-", " ").replace("_", " ")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    return set(t for t in s.lower().split() if len(t) > 1)


def _headings(text: str, algo: str = DEFAULT_ALGO) -> Set[str]:
    """提取 #/## 标题词集合（中文走对应算法分词通道）。"""
    out = set()
    toker = _textrank_tokens if algo == "textrank" else _zh_tokens
    for ln in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)$", ln.strip())
        if m:
            out |= toker(m.group(1))
    return out


def _anchors(text: str, algo: str = DEFAULT_ALGO) -> Set[str]:
    """锚点标题集合（与 corpus_loader.list_anchors 同源语义）。"""
    return _headings(text, algo)


def _first_para(text: str, n: int = 200, algo: str = DEFAULT_ALGO) -> str:
    """首段（去标题后前 n 字符），返回词串供 _similarity 的 .split() 使用。"""
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        return ""
    seg = " ".join(lines)[:n]
    toker = _textrank_tokens if algo == "textrank" else _zh_tokens
    return " ".join(toker(seg))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _similarity(a_text: str, a_stem: str, b_text: str, b_stem: str,
                fa=None, fb=None, algo: str = DEFAULT_ALGO) -> float:
    """加权相似度：标题词(0.4) + 首段词(0.3) + 锚点(0.3)。

    fa/fb 为预计算特征（dict: title/head/para），由 scan() 一次性算好，
    避免两两比较时重复触发 MCP 分词（O(n²) 调用爆炸）。缺省则即时计算。
    algo ∈ cut|textrank：特征一经预计算即与 algo 绑定，扫描全程使用同一通道。
    """
    if fa is None:
        fa = _features(a_text, a_stem, algo=algo)
    if fb is None:
        fb = _features(b_text, b_stem, algo=algo)
    s_title = _jaccard(fa["title"] | fa["head"], fb["title"] | fb["head"])
    s_para = _jaccard(fa["para"], fb["para"])
    s_anchor = _jaccard(fa["head"], fb["head"])
    return 0.4 * s_title + 0.3 * s_para + 0.3 * s_anchor


def _features(text: str, stem: str, algo: str = DEFAULT_ALGO) -> Dict[str, Set[str]]:
    """预计算单文件分词特征（每文件仅触发一次通道分词）。algo 绑定特征通道。"""
    return {
        "title": _title_tokens(stem),
        "head": _headings(text, algo=algo),
        "para": set(_first_para(text, algo=algo).split()),
    }


def _has_cross_ref(a_text: str, a_stem: str, b_text: str, b_stem: str) -> bool:
    """A↔B 是否双向交叉引用（文件名或 stem 互相出现）。"""
    a_in_b = (a_stem in b_text) or (f"{a_stem}.md" in b_text)
    b_in_a = (b_stem in a_text) or (f"{b_stem}.md" in a_text)
    return a_in_b and b_in_a


# ── M-T2 双算法并集（union）持久化 ─────────────────────────────
def _union_load() -> dict:
    """读 homology_union.json（不存在返回空模板）。"""
    try:
        if UNION_PATH.exists():
            return json.loads(UNION_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"generated_at": None, "counts": {"cut": 0, "textrank": 0, "merged": 0},
            "pairs": {}}


def union_scan(confirmed: Dict[str, float] = None) -> dict:
    """双算法各自扫描 → 并集去重 → 写 homology_union.json（M-T2）。

    结构 {pairs: {"a|b": {cut: sim|null, textrank: sim|null, merged: bool}}}。
    merged=true 仅当 cut 与 textrank 均在 ≥ 各自阈值命中（双中高置信）。
    """
    confirmed = confirmed if confirmed is not None else _load_confirmed()
    cut_f = scan(confirmed=confirmed, algo="cut")
    tr_f = scan(confirmed=confirmed, algo="textrank")
    pairs: Dict[str, dict] = {}
    for f in cut_f:
        k = f"{f['a']}|{f['b']}"
        pairs.setdefault(k, {"cut": None, "textrank": None, "merged": False})
        pairs[k]["cut"] = f["sim"]
    for f in tr_f:
        k = f"{f['a']}|{f['b']}"
        pairs.setdefault(k, {"cut": None, "textrank": None, "merged": False})
        pairs[k]["textrank"] = f["sim"]
    for k, v in pairs.items():
        v["merged"] = bool(v["cut"] is not None and v["textrank"] is not None)
    out = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "algorithms": {"cut": "词面全覆盖（jieba.cut / CI）",
                       "textrank": "关键词 topK（夜巡）"},
        "counts": {"cut": len(cut_f), "textrank": len(tr_f),
                   "merged": sum(1 for v in pairs.values() if v["merged"])},
        "pairs": pairs,
    }
    try:
        UNION_PATH.parent.mkdir(parents=True, exist_ok=True)
        UNION_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        pass  # 持久化失败不阻断（report-only）
    return out


def union_report() -> str:
    """M-T3 并集报告：cut 独有 / textrank 独有 / 双中。"""
    d = _union_load()
    pairs = d.get("pairs", {})
    lines = [f"双通道并集报告（{d.get('generated_at', '未生成')}）",
             f"  cut={d.get('counts', {}).get('cut', 0)} · "
             f"textrank={d.get('counts', {}).get('textrank', 0)} · "
             f"merged(双中)={d.get('counts', {}).get('merged', 0)}"]
    only_cut = [k for k, v in pairs.items() if v.get("cut") is not None and v.get("textrank") is None]
    only_tr = [k for k, v in pairs.items() if v.get("textrank") is not None and v.get("cut") is None]
    merged = [k for k, v in pairs.items() if v.get("merged")]
    for tag, ks in (("cut 独有", only_cut), ("textrank 独有", only_tr), ("双中(高置信)", merged)):
        if ks:
            lines.append(f"  [{tag}] {len(ks)} 对:")
            for k in ks[:12]:
                v = pairs[k]
                lines.append(f"    {k}  cut={v.get('cut')} textrank={v.get('textrank')}")
        else:
            lines.append(f"  [{tag}] 0 对")
    return "\n".join(lines)


# ── R-4b 废弃资产模板校验（g020b · report-only）──────────────────
DEPRECATED_PATTERN = re.compile(r"DEPRECATED", re.IGNORECASE)


def check_deprecated(issues: List[str], warnings: List[str],
                     ref_dir: Path = REF_DIR) -> None:
    """g020b 废弃资产守卫：DEPRECATED 头必须结构化模板（redirect_to 等）。

    校验规则（详见 references/governance/asset-lifecycle.md）：
      ① 含 DEPRECATED 的文件须以 > [!WARNING] 开头；
      ② 须含 redirect_to: 字段（可复数，; 分隔）；
      ③ 每个 redirect 目标（references/ 相对路径）必须真实存在。
    仅 report（M0.4 纪律）：不修改、不删除废弃文件。
    """
    try:
        for fpath in sorted(ref_dir.rglob("*.md")):
            rel = fpath.relative_to(ref_dir)
            if any(part in EXCLUDE_DIRS for part in rel.parts):
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception:
                continue
            head = text[:500]
            # 仅检测「头部 DEPRECATED 标记块」：> [!WARNING] 引用块含 DEPRECATED 标题，
            # 或标题行含明确废弃语义（⚡️/⚠️ 前缀 · DEPRECATED — · DEPRECATED STUB）。
            # 避免把规范文档章节名（如"何时标记 DEPRECATED"）误判为废弃资产头。
            dep_title = re.search(
                r"^#{1,3}\s+[^#\n]*(?:⚠️\s*DEPRECATED|DEPRECATED\s*[—-]|DEPRECATED\s+STUB)[^#\n]*$",
                head, re.IGNORECASE | re.MULTILINE)
            is_dep_block = (
                head.lstrip().startswith("> [!WARNING]") and "DEPRECATED" in head
            ) or bool(dep_title)
            if not is_dep_block:
                continue
            # ① 模板头
            if not head.lstrip().startswith("> [!WARNING]"):
                warnings.append(
                    f"⚠️  [废弃资产⑳b] {rel} 标 DEPRECATED 但缺 `> [!WARNING]` 模板头"
                    f"（规范见 governance/asset-lifecycle.md）")
                continue
            # ② redirect_to 字段
            m = re.search(r"^>\s*redirect_to:\s*(.+)$", head, re.MULTILINE)
            if not m or not m.group(1).strip():
                warnings.append(
                    f"⚠️  [废弃资产⑳b] {rel} DEPRECATED 头缺 `redirect_to:` 字段"
                    f"（规范见 governance/asset-lifecycle.md）")
                continue
            targets = [t.strip() for t in m.group(1).split(";") if t.strip()]
            # ③ 目标存在性：redirect_to 已是 references/ 相对路径 → 剥前缀再拼 ref_dir
            for tg in targets:
                tg = tg.lstrip("`").rstrip("`").strip()
                if not tg:
                    continue
                if tg.startswith("references/"):
                    tg = tg[len("references/"):]   # 相对 ref_dir（=references/）解析
                cand = ref_dir / tg
                if not cand.exists():
                    warnings.append(
                        f"⚠️  [废弃资产⑳b] {rel} redirect_to 目标不存在：{tg}"
                        f"（规范见 governance/asset-lifecycle.md）")
    except Exception as e:
        warnings.append(f"⚠️  [废弃资产⑳b] 检查异常（跳过）: {e}")


def scan(ref_dir: Path = REF_DIR, confirmed: Dict[str, float] = None,
         algo: str = DEFAULT_ALGO) -> List[dict]:
    """扫描 references 下 md，返回疑似同根未互链对 [{a,b,sim,reason}]。

    algo ∈ cut|textrank：cut=词面全覆盖（默认 · CI 高频通道）；textrank=关键词
    topK 主题集中（夜巡低频通道）。两通道召回面互补，供 union 并集消费。
    """
    if algo not in ALGOS:
        algo = DEFAULT_ALGO
    confirmed = confirmed if confirmed is not None else _load_confirmed()
    toker = _textrank_tokens if algo == "textrank" else _zh_tokens
    files = []
    for fpath in sorted(ref_dir.rglob("*.md")):
        rel = fpath.relative_to(ref_dir)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if fpath.stem in EXCLUDE_STEMS:
            continue
        try:
            text = fpath.read_text(encoding="utf-8")
        except Exception:
            continue
        # 排除废弃 STUB（DEPRECATED / .deprecated）：已物理废弃、内容重定向，
        # 不应参与同源聚类（避免与替代文件误报"疑似同根未互链"）。
        if "DEPRECATED" in text[:500].upper() or fpath.name.endswith(".deprecated"):
            continue
        files.append((fpath.stem, text))

    # ── 特征预计算：每文件仅分词一次（避免两两比较触发 O(n²) MCP 调用）──
    feats = []
    for stem, text in files:
        try:
            fa = _features(text, stem, algo=algo)
            # textrank 通道特征可能为空（短文件无关键词）→ 回退 cut 保证不塌
            if algo == "textrank" and not (fa["head"] or fa["para"] or fa["title"]):
                fa = _features(text, stem, algo="cut")
            feats.append((stem, text, fa))
        except Exception:
            # 分词异常不影响其他文件（降级到 regex 兜底已在通道内处理）
            feats.append((stem, text, _features(text, stem, algo=algo)))

    findings = []
    n = len(feats)
    for i in range(n):
        a_stem, a_text, fa = feats[i]
        for j in range(i + 1, n):
            b_stem, b_text, fb = feats[j]
            pair_key = f"{a_stem}|{b_stem}"
            # 动态校准：已确认同根 → 用确认相似度；若已互链则不报
            if pair_key in confirmed:
                sim = confirmed[pair_key]
                if _has_cross_ref(a_text, a_stem, b_text, b_stem):
                    continue  # 已互链 + 已确认 → 不报
                thr = MIN_THRESHOLD  # 已确认同根但失联 → 用下限，易触发修复告警
            else:
                sim = _similarity(a_text, a_stem, b_text, b_stem, fa=fa, fb=fb, algo=algo)
                thr = BASE_THRESHOLD
            if sim >= thr and not _has_cross_ref(a_text, a_stem, b_text, b_stem):
                findings.append({
                    "a": a_stem, "b": b_stem, "sim": round(sim, 3),
                    "threshold": thr, "reason": "疑似同根未互链",
                })
    findings.sort(key=lambda x: x["sim"], reverse=True)
    return findings


def check(issues: List[str], warnings: List[str], ref_dir: Path = REF_DIR) -> None:
    """守卫检查入口（被 config_sync 调用）。输出 [同源文件⑳] 前缀。"""
    try:
        confirmed = _load_confirmed()
        findings = scan(ref_dir, confirmed)
        for f in findings:
            warnings.append(
                f"⚠️  [同源文件⑳] 疑似同根未互链：{f['a']}.md ↔ {f['b']}.md "
                f"（相似度 {f['sim']} ≥ 阈值 {f['threshold']} · 建议双向引用或确认同根）")
    except Exception as e:
        warnings.append(f"⚠️  [同源文件⑳] 检查异常（跳过）: {e}")


def _main():
    import argparse
    global BASE_THRESHOLD
    ap = argparse.ArgumentParser(description="QCM 同源文件守卫（双通道并集可选）")
    ap.add_argument("--check", action="store_true", help="输出疑似同根未互链对")
    ap.add_argument("--threshold", type=float, default=BASE_THRESHOLD)
    ap.add_argument("--algo", choices=["cut", "textrank", "both"], default=None,
                    help="分词通道：cut（默认·词面全覆盖）| textrank（关键词 topK 主题集中）| both（并集写 union 文件）")
    ap.add_argument("--union", action="store_true",
                    help="双算法各自扫描 → 并集写 homology_union.json")
    ap.add_argument("--union-report", action="store_true",
                    help="读 homology_union.json 输出并集报告（cut独有/textrank独有/双中）")
    args = ap.parse_args()
    if args.threshold:
        BASE_THRESHOLD = args.threshold
    # 写并集优先：--union 与 --union-report 连用时先写再报（夜巡 M-T5 用法）
    if args.union or args.algo == "both":
        d = union_scan()
        print(f"双通道并集已写 {UNION_PATH}")
        print(f"  cut={d['counts']['cut']} · textrank={d['counts']['textrank']} · "
              f"merged(双中)={d['counts']['merged']}")
        if args.union_report:
            print()
            print(union_report())
        return 0
    if args.union_report:
        print(union_report())
        return 0
    algo = args.algo or DEFAULT_ALGO
    fs = scan(algo=algo)
    if args.check:
        if fs:
            for f in fs:
                print(f"  {f['a']}.md ↔ {f['b']}.md  sim={f['sim']} (≥{f['threshold']})")
        else:
            print("  ✅ 无疑似同根未互链对")
    else:
        print(f"扫描 {len(list(REF_DIR.rglob('*.md')))} 文件 · algo={algo} · 命中 {len(fs)} 对")
    # 关闭长驻 Infoseek MCP 连接（避免子进程残留）
    if _MCP_CLIENT is not None:
        try:
            _MCP_CLIENT.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    _main()
