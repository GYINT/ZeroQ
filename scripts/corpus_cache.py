#!/usr/bin/env python3
"""qcm_corpus_cache.py — QCM 运行态缓存（M1 · 动态自适应分类分层 + 全生命周期归一化轮转）

四支柱落地（2026-08-22 重构）：
  ① 动态自适应分类分层：多 root 扫描（references + docs/outputs/components/archive），
     按 路径类别 + 大小 + 修改时间 + 访问频度 推导 tier ∈ {hot, warm, cold}。
  ② 全生命周期动态自适应：容量上限(max_bytes) + 老化 TTL(ttl_days) + 轮转(rotate)
     + 漂移检测(drift_check) + 台账(file_tier 访问计数)。
  ③ 夜巡兜底：rotate()/drift_check() 供 word_evolution.sh [6.9/8] 调用（dry-run 安全）。
  ④ 归一化接入守卫：g019_runtime_cache（config_sync._check_runtime_cache 读本缓存台账）。

持久化（M0.2）：默认落 outputs/.runtime/corpus.db（受管子目录 · 环境变量 QCM_RUNTIME_DIR 可覆盖），
  取代旧 /tmp/qcm-cache（消除临时目录不可控 + 跨会话失缓存）。

向后兼容：CorpusCache(references_dir) 构造签名不变；get_all_files() 默认仅返回
  references 语料（保持 MCP corpus 语义），include_runtime=True 才含 docs/outputs 等运行态文件。

Schema:
  corpus_files (name PK, mtime, content, size, tier, abspath)
  file_tier    (name PK, tier, access_count, last_access, registered_at)
  cache_meta   (k PK, v)

用法：
  from corpus_cache import CorpusCache
  cache = CorpusCache(references_dir)        # 自动纳入 docs/outputs/components/archive
  cache.build()                              # 首次构建（多 root + 分类分层）
  files = cache.get_all_files()              # {name: content}（默认仅 references 语料）
  cache.rotate()                             # 容量上限 + 老化轮转（夜巡调用）
  drift = cache.drift_check()               # 漂移/缺失检测
"""
import os
import re
import sqlite3
import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 扫描排除（路径片段命中即跳过）
EXCLUDE_DIR_FRAGMENTS = {".git", ".runtime", "automation_log", "references/index",
                         "__pycache__", "node_modules"}
EXCLUDE_NAME_FRAGMENTS = {".deprecated"}

# 悬空检测噪音豁免（仅压制确证的占位/叙述性伪引用，非真实语料断链）
# - quarterly_health_report_YYYYQN：季度报告模板输出占位符（YYYYQN 为日期占位）
# - 原X：test-cases.md 明示「原X.md 为合并说明非引用」
# - 在tools：test-cases.md 叙述「在 tools.md 可解析」介词用法，非链接
DANGLING_IGNORE = {"quarterly_health_report_YYYYQN", "原X", "在tools"}


class CorpusCache:
    """SQLite-backed 运行态缓存（多 root · 分类分层 · 全生命周期轮转）"""

    def __init__(self, references_dir: str, db_path: Optional[str] = None,
                 extra_roots: Optional[List[str]] = None,
                 max_bytes: Optional[int] = None, ttl_days: Optional[int] = None):
        self.references_dir = Path(references_dir).resolve()
        self.skill_dir = self.references_dir.parent
        # M0.2：持久化目录（受管子目录 · 默认 outputs/.runtime/）
        self.runtime_dir = Path(os.environ.get(
            "QCM_RUNTIME_DIR", str(self.skill_dir / "outputs" / ".runtime"))).resolve()
        self.db_path = db_path or str(self.runtime_dir / "corpus.db")
        self.max_bytes = max_bytes or int(os.environ.get("QCM_CACHE_MAX_BYTES", 200 * 1024 * 1024))
        self.ttl_days = ttl_days or int(os.environ.get("QCM_CACHE_TTL_DAYS", 30))

        # ① 动态自适应分类分层：自动纳入 docs/outputs/components/archive（M0.1）
        roots = [self.references_dir]
        try:
            from paths import OUTPUTS, COMPONENTS, DOCS, ARCHIVE, DEPLOY
            for p in (OUTPUTS, COMPONENTS, DOCS, ARCHIVE, DEPLOY):
                if p and Path(p).exists():
                    roots.append(Path(p))
        except Exception:
            pass
        if extra_roots:
            for r in extra_roots:
                if r and Path(r).exists():
                    roots.append(Path(r))
        seen, self.roots = set(), []
        for r in roots:
            rp = Path(r).resolve()
            if rp not in seen:
                seen.add(rp)
                self.roots.append(rp)

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    # ── schema ──
    _SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS corpus_files (
            name TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            content TEXT NOT NULL,
            size INTEGER NOT NULL,
            tier TEXT DEFAULT 'warm',
            abspath TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cf_mtime ON corpus_files(mtime);
        CREATE INDEX IF NOT EXISTS idx_cf_tier ON corpus_files(tier);
        CREATE TABLE IF NOT EXISTS file_tier (
            name TEXT PRIMARY KEY,
            tier TEXT,
            access_count INTEGER DEFAULT 0,
            last_access REAL,
            registered_at REAL
        );
        CREATE TABLE IF NOT EXISTS cache_meta (
            k TEXT PRIMARY KEY,
            v TEXT
        );
    """

    def _init_db(self):
        def _create():
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(self._SCHEMA_SQL)

        def _try_delete():
            try:
                os.remove(self.db_path)
                return True
            except OSError:
                return False

        def _try_rename():
            try:
                bak = Path(self.db_path).with_name(
                    Path(self.db_path).name + f".corrupt.{int(time.time())}")
                os.replace(self.db_path, bak)
                return True
            except OSError:
                return False

        def _try_truncate():
            try:
                # 0 字节文件是合法空 SQLite 库（删除被禁时的兜底自愈）
                with open(self.db_path, "wb"):
                    pass
                return True
            except OSError:
                return False

        try:
            _create()
        except sqlite3.DatabaseError:
            # 运行态缓存库损坏自愈（M1.2 · 避免 CorpusCache() 构造即崩溃）：
            #   ① 删损坏文件 ② 改名 .corrupt.<ts> 保留现场 ③ 截断为空（合法空库）→ 重建
            for op in (_try_delete, _try_rename, _try_truncate):
                if op():
                    _create()
                    return
            raise RuntimeError(
                f"运行态缓存库损坏且无法自愈: {self.db_path}（请手动清理）") from None

    # ── 扫描 ──
    def _iter_files(self):
        """遍历全部 root 的 *.md，跳过排除目录/文件/运行态缓存自身"""
        for root in self.roots:
            try:
                for fpath in sorted(Path(root).rglob("*.md")):
                    rel = fpath.relative_to(root)
                    # 跳过隐藏目录（.runtime/.git 等）与排除片段
                    if any(part.startswith(".") for part in rel.parts):
                        continue
                    if any(frag in rel.parts for frag in EXCLUDE_DIR_FRAGMENTS):
                        continue
                    if fpath.name in EXCLUDE_NAME_FRAGMENTS or ".deprecated" in fpath.name:
                        continue
                    # 跳过运行态缓存目录自身（防递归缓存 DB）
                    if self.runtime_dir in fpath.parents or self.runtime_dir == fpath:
                        continue
                    # 键名：references 根用相对路径（兼容 MCP），其余加 root 前缀避免冲突
                    if root == self.references_dir:
                        name = rel.as_posix()
                    else:
                        name = f"{root.name}/{rel.as_posix()}"
                    yield fpath, name
            except Exception:
                continue

    # ── ① 动态自适应分类分层 ──
    def classify_tier(self, name: str, size: int, mtime: float) -> str:
        """推导 tier ∈ {hot, warm, cold}（hot 由访问频度在 record_access 中提升）"""
        age_days = (time.time() - mtime) / 86400
        is_runtime = name.startswith(("outputs/", "docs/", "components/", "archive/"))
        if age_days > self.ttl_days:
            return "cold"
        if size > 200 * 1024:
            return "warm"          # 大文件：缓存但低优先
        if is_runtime:
            return "warm"          # 运行态文件：中频缓存
        return "warm" if age_days < 7 else "cold"

    # ── 构建 / 增量 ──
    def ref_graph(self) -> dict:
        """R-1 引用快照：构建 references 内 md 的入/出引用图 → 落 runtime/ref_graph.json。

        nodes：全部参与引用登记的 md stem（含 reads/id= 锚点引用与裸文件名引用）。
        incoming[stem]：引用该 stem 的文件列表（反查被引用方）。
        outgoing[stem]：该文件引用的其他 stem 列表。
        dangling[stem]：引用了不存在目标文件的记录（供 R4R 悬空扫描）。
        排除：references/index、.runtime、archive、automation_log（索引/运行态/已退役不参与）。
        """
        ref_pat = re.compile(
            r"((?:[\w\-]+/)*[\w][\w\-]*\.md)"   # 裸文件名（路径前缀贪婪；放宽至 \w 容中文/大写首字符，如 Tolerance.md）
            r"|\[[^\]]*\]\(([^)]+\.md)\)"   # markdown 链接形态
            r"|reads:\s*\[([^\]]*)\]"
            r"|✔\s*\*\[\[?([\w\-]+\.md)")
        id_pat = re.compile(r"id:\s*([a-z0-9\-]+)")
        nodes, incoming, outgoing, dangling = set(), {}, {}, {}
        for fpath, name in self._iter_files():
            if not fpath.name.endswith(".md"):
                continue
            stem = fpath.stem
            # 排除索引/归档/运行态（维护/退役面不参与引用图）
            rel = str(fpath.relative_to(self.references_dir)) if self.references_dir in fpath.parents else ""
            if any(seg in ("index", ".runtime", "archive", "automation_log") for seg in rel.split("/")):
                continue
            nodes.add(stem)
            outgoing.setdefault(stem, [])
            incoming.setdefault(stem, [])
        # 仓库根文档（README/SKILL 等）纳入引用图节点域：其裸 .md 引用广泛存在于
        # references/ 文本，放宽 ref_pat 后须作为合法目标，避免误判悬空（dangling 真修法 F3）。
        REPO_DOC_WHITELIST = ["README.md", "SKILL.md"]
        for _doc in REPO_DOC_WHITELIST:
            _s = Path(_doc).stem
            if _s not in nodes:
                nodes.add(_s)
            incoming.setdefault(_s, [])
            outgoing.setdefault(_s, [])
        # 第二遍：扫描引用边（仅 references 根内文件参与；outputs/ 运行态报告不产生 dangling 边，
        # 其内部提及的示例文件名（xxx.md 等）不视为真实语料引用）
        for fpath, name in self._iter_files():
            if not fpath.name.endswith(".md"):
                continue
            if self.references_dir not in fpath.parents:
                continue
            stem = fpath.stem
            rel = str(fpath.relative_to(self.references_dir))
            if any(seg in ("index", ".runtime", "archive", "automation_log") for seg in rel.split("/")):
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
            except Exception:
                continue
            for m in id_pat.finditer(text):
                target = m.group(1)
                if target in nodes:
                    incoming.setdefault(target, []).append(stem)
                    if target not in outgoing[stem]:
                        outgoing.setdefault(stem, []).append(target)
            for m in ref_pat.finditer(text):
                orig = (m.group(1) or m.group(2) or m.group(3) or m.group(4) or "").strip()
                target = re.sub(r"^.*/", "", orig).replace(".md", "")  # 归一化路径→stem
                # 外部路径引用（非 references/ 内，如 qcm_tools_extend/t2.md）→ 非内部断链，跳过
                if "/" in orig and not orig.startswith("references/"):
                    continue
                if target in nodes:
                    if target != stem:
                        incoming.setdefault(target, []).append(stem)
                        if target not in outgoing[stem]:
                            outgoing.setdefault(stem, []).append(target)
                elif target:
                    # 跳过日期/纯数字型叙述引用（如 2026-08-28.md 非真实语料文件 stem）
                    if re.fullmatch(r"[\d\-]+", target):
                        continue
                    # 跳过确证的占位/叙述性伪引用（DANGLING_IGNORE）
                    if target in DANGLING_IGNORE:
                        continue
                    dangling.setdefault(target, []).append(stem)
        out = {
            "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "nodes": sorted(nodes),
            "incoming": {k: sorted(set(v)) for k, v in incoming.items()},
            "outgoing": {k: sorted(set(v)) for k, v in outgoing.items()},
            "dangling": {k: sorted(set(v)) for k, v in dangling.items()},
            "stats": {"nodes": len(nodes),
                      "references": sum(len(v) for v in outgoing.values()),
                      "dangling": sum(len(v) for v in dangling.values())},
        }
        try:
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            (self.runtime_dir / "ref_graph.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return out
    def build(self) -> float:
        """首次/全量构建（多 root + 分类分层）"""
        start = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM corpus_files")
            cur.execute("DELETE FROM file_tier")
            now = time.time()
            for fpath, name in self._iter_files():
                try:
                    mtime = fpath.stat().st_mtime
                    size = fpath.stat().st_size
                    content = fpath.read_text(encoding="utf-8")
                    tier = self.classify_tier(name, size, mtime)
                    cur.execute(
                        "INSERT OR REPLACE INTO corpus_files "
                        "(name, mtime, content, size, tier, abspath) VALUES (?,?,?,?,?,?)",
                        (name, mtime, content, size, tier, str(fpath)))
                    cur.execute(
                        "INSERT OR IGNORE INTO file_tier (name, tier, registered_at) VALUES (?,?,?)",
                        (name, tier, now))
                except Exception:
                    pass
            conn.commit()
        self.rotate()  # 构建后立即可用轮转收敛容量
        return time.time() - start

    def incremental_update(self) -> Dict[str, int]:
        """增量更新（基于 mtime + 漂移自愈）"""
        stats = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            current = {}
            for fpath, name in self._iter_files():
                try:
                    mtime = fpath.stat().st_mtime
                    size = fpath.stat().st_size
                    current[name] = (mtime, size, fpath)
                    row = cur.execute(
                        "SELECT mtime FROM corpus_files WHERE name=?", (name,)).fetchone()
                    if row is None:
                        content = fpath.read_text(encoding="utf-8")
                        tier = self.classify_tier(name, size, mtime)
                        cur.execute(
                            "INSERT INTO corpus_files "
                            "(name, mtime, content, size, tier, abspath) VALUES (?,?,?,?,?,?)",
                            (name, mtime, content, size, tier, str(fpath)))
                        cur.execute("INSERT OR IGNORE INTO file_tier (name, tier) VALUES (?,?)",
                                    (name, tier))
                        stats["added"] += 1
                    elif row[0] < mtime - 1.0:
                        content = fpath.read_text(encoding="utf-8")
                        tier = self.classify_tier(name, size, mtime)
                        cur.execute(
                            "UPDATE corpus_files SET mtime=?, content=?, size=?, tier=?, abspath=? "
                            "WHERE name=?", (mtime, content, size, tier, str(fpath), name))
                        cur.execute("UPDATE file_tier SET tier=? WHERE name=?", (tier, name))
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                except Exception:
                    pass
            # 检测删除（源已消失 → 移除缓存）
            cached = {r[0] for r in cur.execute("SELECT name FROM corpus_files").fetchall()}
            for cached_name in cached:
                if cached_name not in current:
                    cur.execute("DELETE FROM corpus_files WHERE name=?", (cached_name,))
                    cur.execute("DELETE FROM file_tier WHERE name=?", (cached_name,))
                    stats["removed"] += 1
            conn.commit()
        return stats

    # ── ② 全生命周期：轮转 / 漂移 / 访问 ──
    def rotate(self) -> int:
        """容量上限 + 老化轮转（返回驱逐条数）。失败安全：异常不抛。"""
        evicted = 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                now = time.time()
                # 1) 老化：cold 且超 TTL → 驱逐（内容可重读）
                rows = cur.execute("SELECT name, mtime FROM corpus_files").fetchall()
                for name, mtime in rows:
                    age = (now - mtime) / 86400
                    if age > self.ttl_days:
                        cur.execute("DELETE FROM corpus_files WHERE name=?", (name,))
                        evicted += 1
                # 2) 容量上限：超出则按优先级驱逐（cold 优先 → warm 低访问 → 旧）
                total = cur.execute("SELECT COALESCE(SUM(size),0) FROM corpus_files").fetchone()[0]
                if total > self.max_bytes:
                    cand = cur.execute(
                        "SELECT cf.name, cf.size, COALESCE(ft.access_count,0), "
                        "COALESCE(ft.last_access,0), cf.tier FROM corpus_files cf "
                        "LEFT JOIN file_tier ft ON cf.name=ft.name "
                        "ORDER BY (cf.tier='cold') DESC, COALESCE(ft.access_count,0) ASC, "
                        "COALESCE(ft.last_access,0) ASC"
                    ).fetchall()
                    for name, size, ac, la, tier in cand:
                        if total <= self.max_bytes:
                            break
                        cur.execute("DELETE FROM corpus_files WHERE name=?", (name,))
                        total -= size
                        evicted += 1
                conn.commit()
        except Exception:
            pass
        return evicted

    def drift_check(self) -> List[Tuple[str, str]]:
        """漂移检测：返回 [(name, reason)]，reason ∈ {missing, stale}"""
        drift = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                for name, mtime, abspath in conn.execute(
                        "SELECT name, mtime, abspath FROM corpus_files").fetchall():
                    fp = Path(abspath) if abspath else None
                    if fp is None or not fp.exists():
                        drift.append((name, "missing"))
                    elif abs(fp.stat().st_mtime - mtime) > 1.0:
                        drift.append((name, "stale"))
        except Exception:
            pass
        return drift

    def record_access(self, name: str) -> None:
        """访问计数（推导 hot tier）+ 访问计数异常自愈（M1 补齐）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR IGNORE INTO file_tier (name, access_count, last_access) "
                    "VALUES (?,0,?)", (name, time.time()))
                # M1：访问计数异常自愈——负值/超界/last_access 在未来 → 重置为合理基线，
                # 防止脏数据导致 tier 永久错配（cold/hot 误判）。
                row = cur.execute(
                    "SELECT access_count, last_access FROM file_tier WHERE name=?",
                    (name,)).fetchone()
                if row is None:
                    return
                cnt, la = row
                now = time.time()
                if cnt < 0 or cnt > 1_000_000 or la is None or la > now + 1.0:
                    cur.execute(
                        "UPDATE file_tier SET access_count=0, last_access=? WHERE name=?",
                        (now, name))
                    cnt = 0
                else:
                    cur.execute(
                        "UPDATE file_tier SET access_count=access_count+1, last_access=? "
                        "WHERE name=?", (now, name))
                    cnt = cur.execute("SELECT access_count FROM file_tier WHERE name=?",
                                      (name,)).fetchone()[0]
                if cnt >= 5:
                    cur.execute("UPDATE corpus_files SET tier='hot' WHERE name=?", (name,))
                conn.commit()
        except Exception:
            pass

    # ── ② 全生命周期：台账自愈（M1 补齐） ──
    def self_heal(self) -> Dict[str, int]:
        """访问计数/层级脏数据自愈：返回 {reset_tier, reset_count}。

        场景：file_tier.access_count 异常（负值/超界）或 corpus_files.tier 与
        访问计数严重不符（如 cnt>=5 但 tier≠hot）→ 重置修复。复用 adaptive 范式。
        """
        healed = {"tier_mismatch": 0, "count_anomaly": 0}
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                now = time.time()
                # 1) tier 与访问计数不符 → 修正 tier
                for name, cnt, tier in cur.execute(
                        "SELECT ft.name, COALESCE(ft.access_count,0), cf.tier "
                        "FROM corpus_files cf JOIN file_tier ft ON cf.name=ft.name").fetchall():
                    expect = "hot" if cnt >= 5 else tier
                    if expect != tier:
                        cur.execute("UPDATE corpus_files SET tier=? WHERE name=?", (expect, name))
                        healed["tier_mismatch"] += 1
                # 2) 访问计数异常 → 重置
                for name, cnt, la in cur.execute(
                        "SELECT name, access_count, last_access FROM file_tier").fetchall():
                    if cnt < 0 or cnt > 1_000_000 or la is None or la > now + 1.0:
                        cur.execute(
                            "UPDATE file_tier SET access_count=0, last_access=? WHERE name=?",
                            (now, name))
                        healed["count_anomaly"] += 1
                conn.commit()
        except Exception:
            pass
        return healed

    def export_tiers(self) -> Dict[str, str]:
        """② 动态分类分层增强（M2 前置）：导出 {name: tier} 供 corpus_loader 读取。

        直接读 corpus_files.tier（build/record_access 已推导），不重算。
        """
        out = {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                for name, tier in conn.execute("SELECT name, tier FROM corpus_files").fetchall():
                    out[name] = tier or "warm"
        except Exception:
            pass
        return out

    def get_content(self, name: str) -> Optional[str]:
        self.record_access(name)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT content FROM corpus_files WHERE name=?",
                               (name,)).fetchone()
            return row[0] if row else None

    # ── 读取 API ──
    def get_all_files(self, include_runtime: bool = False) -> Dict[str, str]:
        """获取缓存文件 {name: content}。

        include_runtime=False（默认）→ 仅 references 语料（保持 MCP corpus 语义）。
        include_runtime=True → 含 docs/outputs/components/archive 运行态文件。
        """
        out = {}
        with sqlite3.connect(self.db_path) as conn:
            for name, content in conn.execute("SELECT name, content FROM corpus_files").fetchall():
                if not include_runtime and name.startswith(
                        ("outputs/", "docs/", "components/", "archive/")):
                    continue
                out[name] = content
        return out

    def get_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            total = cur.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM corpus_files").fetchone()
            by_tier = {}
            for tier, cnt in cur.execute("SELECT tier, COUNT(*) FROM corpus_files GROUP BY tier"):
                by_tier[tier] = cnt
        return {
            "files": total[0] or 0,
            "total_size_bytes": total[1] or 0,
            "by_tier": by_tier,
            "db_path": self.db_path,
            "roots": [str(r) for r in self.roots],
            "max_bytes": self.max_bytes,
            "ttl_days": self.ttl_days,
        }

    def is_built(self) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM corpus_files").fetchone()[0] > 0

    def clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM corpus_files")
            conn.execute("DELETE FROM file_tier")
            conn.commit()


class CorpusWatcher:
    """Corpus 文件监控（mtime 检测 + 自动增量更新）"""

    def __init__(self, cache: CorpusCache, references_dir: str, interval_s: float = 5.0):
        self.cache = cache
        self.references_dir = references_dir
        self.interval_s = interval_s
        self._last_mtimes: Dict[str, float] = {}
        self._running = False

    def start(self):
        import threading
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                stats = self.cache.incremental_update()
                if stats["added"] or stats["updated"] or stats["removed"]:
                    print(f"[CorpusWatcher] Reloaded: {stats}", flush=True)
            except Exception as e:
                print(f"[CorpusWatcher] Error: {e}", flush=True)
            time.sleep(self.interval_s)

    def check_once(self) -> Dict[str, int]:
        return self.cache.incremental_update()


def _main():
    import argparse
    from paths import REFERENCES
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--rotate", action="store_true")
    ap.add_argument("--drift", action="store_true")
    ap.add_argument("--ref-graph", action="store_true", help="生成引用图快照 ref_graph.json")
    ap.add_argument("--scan", action="store_true", help="打印统计（不写）")
    ap.add_argument("--extra", nargs="*", default=[])
    args = ap.parse_args()

    cache = CorpusCache(str(REFERENCES), extra_roots=args.extra)
    if args.build:
        print(f"build 耗时 {cache.build():.3f}s")
        rg = cache.ref_graph()  # R-1：build 后同时刷新引用图快照
        print(f"ref_graph: nodes={rg['stats']['nodes']} refs={rg['stats']['references']} "
              f"dangling={rg['stats']['dangling']}")
    if args.ref_graph and not args.build:
        rg = cache.ref_graph()
        print(f"ref_graph: nodes={rg['stats']['nodes']} refs={rg['stats']['references']} "
              f"dangling={rg['stats']['dangling']}")
    if args.rotate:
        print(f"rotate 驱逐 {cache.rotate()} 条")
    if args.drift:
        print(f"drift: {cache.drift_check()}")
    st = cache.get_stats()
    print(f"files={st['files']} size={st['total_size_bytes']/1024:.1f}KB "
          f"tiers={st['by_tier']} db={st['db_path']}")


if __name__ == "__main__":
    _main()
